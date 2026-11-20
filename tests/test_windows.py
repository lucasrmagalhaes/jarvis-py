"""Caminhos, codificação e processos no Windows, sem hardware e sem nota real."""

import os
import re
import shutil
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

from jarvis.autostart import Autostart
from jarvis.config import jarvis_home
from jarvis.guardas import escrever
from jarvis.panel import STATIC_DIR
from jarvis.paths import windows_drive
from jarvis.procutil import command_argv, resolve_executable
from jarvis.routines import _note_file

ENV_CALL = re.compile(
    r"""(?:environ(?:\.get)?|source\.get|_flag|_bounded_int)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
)
SKIP_ENV = {"PATH", "APPDATA", "USERNAME", "HF_HUB_OFFLINE"}


class WindowsPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._home = os.environ.get("JARVIS_HOME")

    def tearDown(self):
        if self._home is None:
            os.environ.pop("JARVIS_HOME", None)
        else:
            os.environ["JARVIS_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_windows_drive_is_not_a_note_path(self):
        self.assertTrue(windows_drive("C:/Windows/nota.md"))
        self.assertTrue(windows_drive(r"D:\vault\nota.md"))
        self.assertFalse(windows_drive("notas/sintetica.md"))
        self.assertFalse(windows_drive(""))
        vault = self.tmp / "vault"
        vault.mkdir()
        note = vault / "nota.md"
        note.write_text("texto sintetico\n", encoding="utf-8", newline="\n")
        self.assertIsNone(_note_file(vault, "C:/Windows/nota.md"))
        self.assertIsNone(_note_file(vault, r"C:\Windows\nota.md"))
        self.assertEqual(_note_file(vault, "nota.md"), note.resolve())

    def test_home_uses_path_home(self):
        os.environ.pop("JARVIS_HOME", None)
        with mock.patch("jarvis.ajustes.Path.home", return_value=self.tmp):
            found = jarvis_home()
        self.assertEqual(found, self.tmp / ".jarvis")
        self.assertEqual(found.anchor, self.tmp.anchor)

    def test_utf8_write_keeps_lf(self):
        path = self.tmp / "nota.md"
        escrever(path, "ação\n")
        self.assertEqual(path.read_bytes(), "ação\n".encode("utf-8"))
        self.assertNotIn(b"\r\n", path.read_bytes())

    def test_windows_launcher_uses_crlf_once(self):
        service = Autostart(
            platform_name="Windows",
            home=self.tmp,
            project=self.tmp / "projeto",
            python=sys.executable,
            runner=lambda *_args, **_kwargs: None,
        )
        service._write_launcher()
        data = service.launcher_path.read_bytes()
        self.assertTrue(data.startswith("@echo off\r\n".encode("ascii")))
        self.assertNotIn(b"\r\r\n", data)
        self.assertIn("PYTHONUTF8=1".encode("ascii"), data)

    def test_panel_static_is_a_path(self):
        self.assertIsInstance(STATIC_DIR, Path)
        self.assertTrue((STATIC_DIR / "index.html").is_file())
        source = (ROOT / "jarvis" / "panel.py").read_text(encoding="utf-8")
        self.assertNotIn("rsplit", source)
        self.assertNotIn('f"{STATIC_DIR}', source)

    def test_command_argv_resolves_git_and_wraps_cmd_without_shell(self):
        git = command_argv("git", "status")
        resolved = shutil.which("git")
        self.assertIsNotNone(git)
        self.assertIsNotNone(resolved)
        if resolved.lower().endswith((".cmd", ".bat")):
            self.assertEqual(git[1], "/c")
            self.assertEqual(git[2], resolved)
            self.assertEqual(git[-1], "status")
        else:
            self.assertEqual(git[0], resolved)
            self.assertEqual(git[1], "status")
        self.assertNotIn("shell", git)
        script = self.tmp / "claude.cmd"
        script.write_text("@echo off\r\n", encoding="utf-8", newline="\n")
        argv = command_argv(script, "-p", "olá")
        self.assertEqual(argv[1], "/c")
        self.assertEqual(argv[2], str(script))
        self.assertEqual(argv[-1], "olá")
        self.assertEqual(resolve_executable(script), str(script))
        self.assertIsNone(command_argv(self.tmp / "ausente.exe", "status"))
        fake = self.tmp / "gh"
        fake.write_text(
            "#!/usr/bin/env python3\nraise SystemExit(0)\n",
            encoding="utf-8",
            newline="\n",
        )
        wrapped = command_argv(fake, "auth", "status", platform_name="nt")
        self.assertEqual(wrapped[0], sys.executable)
        self.assertEqual(wrapped[1], str(fake))
        self.assertEqual(wrapped[2:], ["auth", "status"])

    def test_sources_avoid_shell_and_declare_text_writes(self):
        for path in (ROOT / "jarvis").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", text, path.name)
            self.assertNotIn("\u2014", text, path.name)
            self.assertNotIn("\u2013", text, path.name)
            start = 0
            while True:
                index = text.find("write_text(", start)
                if index < 0:
                    break
                window = text[index : index + 400]
                self.assertIn("encoding=", window, path.name)
                self.assertIn('newline="\\n"', window, path.name)
                start = index + len("write_text(")

    def test_example_env_lists_used_variables_and_is_not_ignored(self):
        example = (ROOT / ".env.exemplo").read_text(encoding="utf-8")
        self.assertNotIn("\u2014", example)
        self.assertNotIn("\u2013", example)
        found = set()
        for path in (ROOT / "jarvis").glob("*.py"):
            found.update(ENV_CALL.findall(path.read_text(encoding="utf-8")))
        missing = sorted(name for name in found - SKIP_ENV if name not in example)
        self.assertEqual(missing, [])
        for secret in ("READWISE_TOKEN", "TELEGRAM_BOT_TOKEN", "JIRA_TOKEN", "GMAIL_APP_PASSWORD"):
            self.assertIn(secret, example)
        self.assertNotIn("token-secreto", example)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(ignored.returncode, 0)
        for name in (".env.exemplo", ".env.example"):
            visible = subprocess.run(
                ["git", "check-ignore", "-q", name],
                cwd=ROOT,
                check=False,
            )
            self.assertNotEqual(visible.returncode, 0, name)
        other = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertEqual(other, example)

    def test_setup_scripts_are_one_command_and_in_portuguese(self):
        shell = (ROOT / "scripts" / "instalar.sh").read_text(encoding="utf-8")
        powershell = (ROOT / "scripts" / "instalar.ps1").read_text(encoding="utf-8")
        for text in (shell, powershell):
            self.assertIn("python -m jarvis doctor", text)
            self.assertIn("requirements.txt", text)
            self.assertIn("requirements-wake.txt", text)
            self.assertIn("Próximos passos", text)
            self.assertIn("python -m jarvis.chat", text)
            self.assertNotIn("\u2014", text)
            self.assertNotIn("Invoke-Expression", text)
            self.assertNotIn("token-secreto", text)
        self.assertIn("--wake", shell)
        self.assertIn("-Wake", powershell)
        self.assertIn("venv", shell)
        self.assertIn(".venv", powershell)
        self.assertTrue(shell.startswith("#!/usr/bin/env bash"))
        if os.name != "nt":
            mode = (ROOT / "scripts" / "instalar.sh").stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
