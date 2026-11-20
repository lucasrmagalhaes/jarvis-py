import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.envfile import (
    acl_private,
    dump_env,
    env_path,
    load_env,
    merge_env,
    parse_env,
    permissions_restricted,
    quote_value,
    windows_restrict_commands,
    write_env,
)


class EnvFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {}

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_ignores_comments_and_roundtrips_secrets(self):
        text = "\n".join(
            [
                "# comentario",
                "export JARVIS_VAULT=/tmp/vault pessoal",
                'JIRA_TOKEN="abc def"',
                "GMAIL_APP_PASSWORD='ab cd'",
                "linha sem igual",
                "JARVIS_MODEL=opus",
                "1INVALID=nao",
                "",
            ]
        )
        values = parse_env(text)
        self.assertEqual(values["JARVIS_VAULT"], "/tmp/vault pessoal")
        self.assertEqual(values["JIRA_TOKEN"], "abc def")
        self.assertEqual(values["GMAIL_APP_PASSWORD"], "ab cd")
        self.assertEqual(values["JARVIS_MODEL"], "opus")
        self.assertNotIn("1INVALID", values)
        again = parse_env(dump_env(values))
        self.assertEqual(again["JIRA_TOKEN"], "abc def")
        self.assertEqual(again["JARVIS_VAULT"], "/tmp/vault pessoal")
        self.assertIn("\\", quote_value("a\\b"))
        self.assertEqual(parse_env("X=" + quote_value('aspas "aqui"'))["X"], 'aspas "aqui"')

    def test_load_does_not_override_the_environment(self):
        path = self.tmp / ".env"
        path.write_text(
            "JIRA_TOKEN=do-arquivo\nJARVIS_MODEL=opus\n",
            encoding="utf-8",
        )
        environ = {"JIRA_TOKEN": "do-shell"}
        self.assertTrue(load_env(path, environ))
        self.assertEqual(environ["JIRA_TOKEN"], "do-shell")
        self.assertEqual(environ["JARVIS_MODEL"], "opus")
        missing = self.tmp / "nao-existe.env"
        self.assertFalse(load_env(missing, {}))

    def test_merge_removes_empty_and_keeps_extra_keys(self):
        merged = merge_env(
            {"JARVIS_MODEL": "opus", "JIRA_TOKEN": "velho"},
            {"JIRA_TOKEN": "", "JIRA_URL": "https://example.atlassian.net"},
        )
        self.assertEqual(merged["JARVIS_MODEL"], "opus")
        self.assertNotIn("JIRA_TOKEN", merged)
        self.assertEqual(merged["JIRA_URL"], "https://example.atlassian.net")

    def test_write_env_is_private_even_with_open_umask(self):
        if os.name == "nt":
            self.skipTest("modo POSIX")
        path = self.tmp / ".jarvis" / ".env"
        old = os.umask(0)
        try:
            write_env(path, {"JIRA_TOKEN": "token-secreto", "JARVIS_VAULT": "/tmp/vault"})
        finally:
            os.umask(old)
        mode = stat.S_IMODE(path.stat().st_mode)
        parent = stat.S_IMODE(path.parent.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(parent, 0o700)
        self.assertTrue(permissions_restricted(path))
        self.assertIn("token-secreto", path.read_text(encoding="utf-8"))

    def test_windows_restrict_does_not_put_the_secret_on_the_command_line(self):
        path = self.tmp / ".jarvis" / ".env"
        calls = []

        def runner(args, timeout=20):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")

        write_env(
            path,
            {"JIRA_TOKEN": "token-secreto"},
            system="Windows",
            runner=runner,
            user="usuario",
        )
        flat = " ".join(" ".join(command) for command in calls)
        self.assertNotIn("token-secreto", flat)
        self.assertIn(["icacls", str(path), "/inheritance:r"], calls)
        self.assertTrue(any("usuario:(R,W)" in command for command in calls))
        self.assertEqual(
            windows_restrict_commands(path, "usuario")[1][-1],
            "usuario:(R,W)",
        )

    def test_acl_private_rejects_broad_groups(self):
        self.assertTrue(acl_private(r"C:\Users\Usuario\.env USUARIO\Usuario:(R,W)"))
        self.assertFalse(acl_private(r"C:\Users\Usuario\.env Everyone:(R)"))
        self.assertFalse(acl_private(r"C:\Users\Usuario\.env BUILTIN\Users:(R)"))
        self.assertFalse(acl_private("pasta Todos:(R)"))

    def test_default_path_is_outside_the_repository(self):
        with mock.patch("jarvis.envfile.Path.home", return_value=Path("/home/usuario")):
            path = env_path({})
        self.assertEqual(path, Path("/home/usuario/.jarvis/.env"))
        self.assertFalse(str(path).startswith(str(ROOT)))
        custom = env_path({"JARVIS_ENV_FILE": str(self.tmp / "custom.env")})
        self.assertEqual(custom, self.tmp / "custom.env")

    def test_gitignore_covers_dotenv(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", text)
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_config_loads_the_file_without_overriding_the_shell(self):
        path = self.tmp / "jarvis.env"
        path.write_text(
            "JARVIS_VAULT=/from-file\nJARVIS_MODEL=opus\n",
            encoding="utf-8",
        )
        script = (
            "import os\n"
            "from jarvis.config import vault_dir\n"
            "print(vault_dir())\n"
            "print(os.environ.get('JARVIS_MODEL', ''))\n"
        )
        overridden = os.environ.copy()
        overridden["JARVIS_ENV_FILE"] = str(path)
        overridden["JARVIS_VAULT"] = "/from-shell"
        overridden.pop("JARVIS_MODEL", None)
        first = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=overridden,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.splitlines(), ["/from-shell", "opus"])

        fresh = os.environ.copy()
        fresh["JARVIS_ENV_FILE"] = str(path)
        fresh.pop("JARVIS_VAULT", None)
        fresh.pop("JARVIS_MODEL", None)
        second = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=fresh,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.splitlines(), ["/from-file", "opus"])


if __name__ == "__main__":
    unittest.main()
