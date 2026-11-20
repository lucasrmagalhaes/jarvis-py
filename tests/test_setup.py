import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _git_clone(args):
    if len(args) >= 2 and args[1] == "clone":
        name = Path(args[0]).name.lower()
        if name in {"git", "git.exe"}:
            return True
    if len(args) >= 4 and args[1] == "/c" and args[3] == "clone":
        name = Path(args[2]).name.lower()
        if name in {"git.cmd", "git.bat"}:
            return True
    return False

from jarvis.autostart import Autostart
from jarvis.envfile import parse_env, write_env
from jarvis.setup import (
    SetupContext,
    describe_vault_path,
    is_inside,
    main,
    scrub_text,
)

TOKEN = "token-secreto"
PASSWORD = "abcd efgh ijkl mnop"
TELEGRAM_TOKEN = "999:TESTETOKEN"
REMOTE = "https://github.com/exemplo/vault-de-notas.git"
OPTIONAL_COUNT = 15


class Script:
    def __init__(self, answers):
        self.answers = list(answers)
        self.output = []

    def say(self, text=""):
        self.output.append(str(text))

    def ask(self, prompt):
        self.output.append("PERGUNTA " + prompt)
        if not self.answers:
            raise AssertionError("sem resposta para: " + prompt)
        return self.answers.pop(0)

    def secret(self, prompt):
        self.output.append("SEGREDO " + prompt)
        if not self.answers:
            raise AssertionError("sem segredo para: " + prompt)
        return self.answers.pop(0)

    def confirm(self, prompt, default=False):
        self.output.append("CONFIRMA " + prompt)
        if not self.answers:
            raise AssertionError("sem confirmação para: " + prompt)
        raw = self.answers.pop(0)
        if raw == "":
            return default
        return raw.casefold() in {"s", "sim", "y", "yes"}

    def text(self):
        return "\n".join(self.output)


class Runner:
    def __init__(self, codes=None, stderr="", sequence=None):
        self.calls = []
        self.timeouts = []
        self.codes = codes or {}
        self.stderr = stderr
        self.sequence = list(sequence) if sequence is not None else None

    def __call__(self, args, timeout=60):
        listed = list(args)
        self.calls.append(listed)
        self.timeouts.append(timeout)
        if self.sequence:
            code = self.sequence.pop(0)
        else:
            code = self.codes.get(self._key(listed), 0)
        if _git_clone(listed) and code == 0:
            dest = Path(listed[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / ".git").mkdir()
        return subprocess.CompletedProcess(listed, code, "", self.stderr)

    @staticmethod
    def _key(args):
        if _git_clone(args):
            return "clone"
        if len(args) > 2 and args[1] == "-m" and args[2] == "pip":
            joined = " ".join(args)
            if "--no-deps" in args or "requirements-wake" in joined:
                return "pip-wake"
            return "pip"
        if args[:2] == ["schtasks", "/Create"]:
            return "task"
        return args[0] if args else ""


def make_context(root, home, runner, **kwargs):
    service = Autostart(
        platform_name=kwargs.get("platform_name", "Darwin"),
        home=home,
        project=root,
        python="/usr/bin/python3",
        runner=runner,
        uid="501",
        appdata=str(home / "AppData" / "Roaming"),
        path_env="/usr/bin:/bin",
    )
    return SetupContext(
        root=root,
        home=home,
        environ=kwargs.get("environ", {}),
        env_file=home / ".jarvis" / ".env",
        python="/usr/bin/python3",
        runner=runner,
        autostart_service=service,
        remote=REMOTE,
        has_git=kwargs.get("has_git", True),
        github_state=kwargs.get("github_state", "missing"),
        missing_required=kwargs.get("missing_required", lambda: []),
        missing_optional=kwargs.get("missing_optional", lambda: []),
        python_ok=True,
        python_label="3.12.3",
        claude_present=kwargs.get("claude_present", True),
        wake_ready=kwargs.get("wake_ready", lambda: True),
    )


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "jarvis"
        self.home = self.tmp / "home"
        self.root.mkdir()
        self.home.mkdir()
        (self.root / "requirements.txt").write_text("numpy\n", encoding="utf-8")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_no_secrets(self, text):
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(PASSWORD, text)

    def test_guided_setup_clones_saves_a_private_env_and_arms_login(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner, github_state="anonymous")
        script = Script(
            [
                "",
                "s",
                "https://example.atlassian.net",
                "pessoa@example.com",
                TOKEN,
                *([""] * (OPTIONAL_COUNT - 3)),
                "s",
            ]
        )
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        self.assertFalse(script.answers)
        text = script.text()
        self.assert_no_secrets(text)
        self.assertIn("Dependências presentes.", text)
        self.assertIn("gh sem login", text)
        self.assertIn("Vault clonado.", text)
        self.assertIn("LaunchAgent", text)
        self.assertIn("python -m jarvis.setup --desativar-inicio", text)
        env_file = context.env_path
        self.assertTrue(env_file.is_file())
        self.assertFalse(str(env_file).startswith(str(ROOT)))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        values = parse_env(env_file.read_text(encoding="utf-8"))
        vault = self.home / "Documents" / "vault-de-notas"
        self.assertEqual(values["JARVIS_VAULT"], str(vault))
        self.assertEqual(values["JIRA_TOKEN"], TOKEN)
        self.assertEqual(values["JIRA_EMAIL"], "pessoa@example.com")
        self.assertNotIn("GMAIL_APP_PASSWORD", values)
        self.assertTrue((vault / ".git").is_dir())
        clone = next(call for call in runner.calls if _git_clone(call))
        parts = clone[2:] if len(clone) >= 4 and clone[1] == "/c" else clone
        self.assertEqual(parts[2], REMOTE)
        self.assertEqual(Path(parts[3]), vault)
        self.assertIn(300, runner.timeouts)
        plist = context.autostart.plist_path.read_text(encoding="utf-8")
        self.assert_no_secrets(plist)
        joined = [" ".join(call) for call in runner.calls]
        self.assertFalse(any("bootstrap" in item or "kickstart" in item for item in joined))
        self.assertTrue(all(TOKEN not in item for item in joined))

    def test_rerun_edits_keys_and_can_disable_autostart(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner)
        repo = self.home / "Documents" / "vault-de-notas"
        (repo / ".git").mkdir(parents=True)
        write_env(
            context.env_path,
            {
                "JARVIS_VAULT": str(repo),
                "JIRA_URL": "https://example.atlassian.net",
                "JIRA_EMAIL": "pessoa@example.com",
                "JIRA_TOKEN": TOKEN,
                "JARVIS_MODEL": "opus",
            },
        )
        context.autostart.enable()
        runner.calls.clear()
        script = Script(
            [
                "",
                "",
                "",
                "limpar",
                "pessoa@example.com",
                PASSWORD,
                *([""] * (OPTIONAL_COUNT - 5)),
                "n",
                "s",
            ]
        )
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        text = script.text()
        self.assert_no_secrets(text)
        self.assertIn("GMAIL_APP_PASSWORD: definido", text)
        self.assertIn("JIRA_TOKEN: removido", text)
        self.assertIn("desligado", text.casefold())
        values = parse_env(context.env_path.read_text(encoding="utf-8"))
        self.assertEqual(values["JARVIS_VAULT"], str(repo))
        self.assertEqual(values["JARVIS_MODEL"], "opus")
        self.assertEqual(values["GMAIL_EMAIL"], "pessoa@example.com")
        self.assertEqual(values["GMAIL_APP_PASSWORD"], PASSWORD)
        self.assertNotIn("JIRA_TOKEN", values)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(context.env_path.stat().st_mode), 0o600)
        self.assertFalse(any(_git_clone(call) for call in runner.calls))
        self.assertFalse(context.autostart.plist_path.exists())

    def test_clear_vault_and_refuse_folder_inside_the_project(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner)
        repo = self.home / "vault-ok"
        (repo / ".git").mkdir(parents=True)
        write_env(context.env_path, {"JARVIS_VAULT": str(repo), "JIRA_URL": "https://x"})
        inside = self.root / "vault"
        script = Script([str(inside), *([""] * OPTIONAL_COUNT), "n"])
        self.assertEqual(main([], context, script), 0, script.text())
        self.assertIn("dentro da pasta do Jarvis", script.text())
        self.assertIn("Mantive o clone anterior.", script.text())
        values = parse_env(context.env_path.read_text(encoding="utf-8"))
        self.assertEqual(values["JARVIS_VAULT"], str(repo))
        self.assertTrue(is_inside(self.root, inside))
        self.assertFalse(is_inside(self.root, repo))

        script = Script(["limpar", *([""] * OPTIONAL_COUNT), "n"])
        self.assertEqual(main([], context, script), 0, script.text())
        values = parse_env(context.env_path.read_text(encoding="utf-8"))
        self.assertNotIn("JARVIS_VAULT", values)
        self.assertEqual(values["JIRA_URL"], "https://x")
        self.assertFalse(any(_git_clone(call) for call in runner.calls))

    def test_occupied_folder_is_not_overwritten(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner)
        occupied = self.home / "notes"
        occupied.mkdir()
        (occupied / "nota.md").write_text("oi", encoding="utf-8")
        self.assertEqual(describe_vault_path(occupied), "occupied")
        script = Script([str(occupied), "n", *([""] * OPTIONAL_COUNT), "n"])
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        self.assertIn("Não vou clonar por cima.", script.text())
        self.assertFalse((occupied / ".git").exists())
        self.assertFalse(context.env_path.read_text(encoding="utf-8").count("JARVIS_VAULT"))
        self.assertFalse(any(_git_clone(call) for call in runner.calls))

    def test_clone_failure_scrubs_secrets_and_keeps_other_keys(self):
        runner = Runner(
            codes={"clone": 1},
            stderr="fatal: https://pessoa:ghp_supersecreto@github.com/privado " + TOKEN,
        )
        context = make_context(self.root, self.home, runner)
        script = Script(
            [
                "",
                "s",
                "",
                "",
                TOKEN,
                *([""] * (OPTIONAL_COUNT - 3)),
                "n",
            ]
        )
        code = main([], context, script)
        self.assertEqual(code, 1, script.text())
        text = script.text()
        self.assert_no_secrets(text)
        self.assertNotIn("ghp_supersecreto", text)
        self.assertIn("://github.com/privado", text)
        self.assertIn("Autentique o git", text)
        values = parse_env(context.env_path.read_text(encoding="utf-8"))
        self.assertNotIn("JARVIS_VAULT", values)
        self.assertEqual(values["JIRA_TOKEN"], TOKEN)
        self.assertEqual(
            scrub_text("https://user:segredo@github.com/a", ["segredo"]),
            "https://github.com/a",
        )

    def test_missing_git_does_not_clone(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner, has_git=False)
        script = Script(["", *([""] * OPTIONAL_COUNT), "n"])
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        self.assertIn("git não encontrado", script.text())
        self.assertFalse(any(_git_clone(call) for call in runner.calls))
        values = parse_env(context.env_path.read_text(encoding="utf-8"))
        self.assertNotIn("JARVIS_VAULT", values)

    def test_pip_install_and_failure_hide_secrets(self):
        state = {"left": 1}

        def missing():
            if state["left"]:
                state["left"] -= 1
                return ["numpy"]
            return []

        runner = Runner()
        context = make_context(
            self.root,
            self.home,
            runner,
            missing_required=missing,
        )
        script = Script(["s", "limpar", *([""] * OPTIONAL_COUNT), "n"])
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        self.assertIn("Dependências instaladas.", script.text())
        pip = next(call for call in runner.calls if call[1:3] == ["-m", "pip"])
        self.assertEqual(pip[0], "/usr/bin/python3")
        self.assertIn(str(self.root / "requirements.txt"), pip)
        self.assertIn(600, runner.timeouts)

        runner = Runner(
            codes={"pip": 1},
            stderr="ERROR " + TOKEN + "\n",
        )
        context = make_context(
            self.root,
            self.home,
            runner,
            environ={"JIRA_TOKEN": TOKEN},
            missing_required=lambda: ["numpy"],
        )
        script = Script(["s", "limpar", *([""] * OPTIONAL_COUNT), "n"])
        code = main([], context, script)
        self.assertEqual(code, 1, script.text())
        self.assertNotIn(TOKEN, script.text())
        self.assertIn("A instalação falhou.", script.text())
        self.assertNotIn("Dependências instaladas.", script.text())
        self.assertNotIn("Instalei o restante", script.text())

    def test_core_install_continues_when_the_requirements_file_fails(self):
        runner = Runner(
            sequence=[1, 0],
            stderr="ERROR: No matching distribution found for tflite-runtime<3,>=2.8.0\n",
        )
        state = {"left": 1}

        def missing():
            if state["left"]:
                state["left"] -= 1
                return ["sounddevice"]
            return []

        context = make_context(
            self.root,
            self.home,
            runner,
            missing_required=missing,
            wake_ready=lambda: False,
        )
        script = Script(["s", "limpar", *([""] * OPTIONAL_COUNT), "n"])
        with mock.patch("jarvis.deps.tflite_unavailable", return_value=True):
            code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        text = script.text()
        self.assertIn("Instalei o restante das dependências.", text)
        self.assertIn("python -m jarvis.chat", text)
        self.assertIn("ONNX", text)
        self.assertNotIn("A instalação falhou.", text)
        self.assertNotIn("Dependências instaladas.", text)
        pip_calls = [call for call in runner.calls if len(call) > 2 and call[1:3] == ["-m", "pip"]]
        self.assertGreaterEqual(len(pip_calls), 2)
        self.assertIn(str(self.root / "requirements.txt"), pip_calls[0])
        joined = "\n".join(" ".join(call) for call in pip_calls)
        self.assertIn("requirements-wake", joined)
        self.assertNotIn("tflite-runtime", pip_calls[0][-1])

    def test_wake_pip_failure_does_not_block_the_rest(self):
        runner = Runner(
            codes={"pip-wake": 1},
            stderr="ERROR: No matching distribution found for tflite-runtime<3,>=2.8.0\n",
        )
        state = {"left": 1}

        def missing():
            if state["left"]:
                state["left"] -= 1
                return ["sounddevice"]
            return []

        context = make_context(
            self.root,
            self.home,
            runner,
            missing_required=missing,
            wake_ready=lambda: False,
        )
        script = Script(["s", "limpar", *([""] * OPTIONAL_COUNT), "n"])
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        text = script.text()
        self.assertIn("Instalei o restante das dependências.", text)
        self.assertIn("python -m jarvis.chat", text)
        self.assertIn("tflite-runtime", text)
        self.assertNotIn(TOKEN, text)
        core = next(
            call
            for call in runner.calls
            if len(call) > 2 and call[1:3] == ["-m", "pip"] and "requirements-wake" not in " ".join(call)
        )
        self.assertIn(str(self.root / "requirements.txt"), core)

    def test_disable_command_is_idempotent(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner)
        context.autostart.enable()
        script = Script([])
        code = main(["--desativar-inicio"], context, script)
        self.assertEqual(code, 0, script.text())
        self.assertIn("desligado", script.text().casefold())
        self.assertFalse(context.autostart.plist_path.exists())
        self.assertFalse(script.answers)
        again = main(["--desativar-inicio"], context, Script([]))
        self.assertEqual(again, 0)

    def test_help_is_portuguese_and_has_no_em_dash(self):
        result = subprocess.run(
            [sys.executable, "-m", "jarvis.setup", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--desativar-inicio", result.stdout)
        self.assertIn("início automático", result.stdout)
        self.assertNotIn("\u2014", result.stdout)
        self.assertNotIn("\u2013", result.stdout)

    def test_docs_and_sources_avoid_em_dash(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Instalação guiada", 1)[1].split("## Instalação manual", 1)[0]
        self.assertIn("~/.jarvis/.env", section)
        self.assertNotIn("\u2014", section)
        self.assertNotIn("\u2013", section)
        decisions = (ROOT / "mapa" / "Decisões.md").read_text(encoding="utf-8")
        block = decisions.split("## Configuração fora do repositório", 1)[1].split(
            "## Relacionado", 1
        )[0]
        self.assertNotIn("\u2014", block)
        self.assertNotIn("\u2013", block)
        for name in (
            "jarvis/setup.py",
            "jarvis/envfile.py",
            "jarvis/autostart.py",
            "jarvis/deps.py",
            "jarvis/doctor.py",
            "jarvis/radar.py",
            "tests/test_setup.py",
            "tests/test_envfile.py",
            "tests/test_autostart.py",
            "tests/test_doctor_config.py",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)

    def test_remote_section_has_no_em_dash(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## De qualquer lugar", 1)[1].split("## Diagnóstico", 1)[0]
        self.assertIn("jarvis.main", section)
        self.assertIn("jarvis.telegram", section)
        self.assertNotIn("\u2014", section)
        self.assertNotIn("\u2013", section)

    def test_telegram_and_checkins_stay_in_the_env_and_out_of_the_launcher(self):
        runner = Runner()
        context = make_context(self.root, self.home, runner)
        script = Script(
            [
                "limpar",
                "",
                "",
                "",
                "",
                "",
                TELEGRAM_TOKEN,
                "42",
                "off",
                "",
                "",
                "on",
                "on",
                "on",
                "18:30",
                "",
                "s",
            ]
        )
        code = main([], context, script)
        self.assertEqual(code, 0, script.text())
        self.assertFalse(script.answers)
        text = script.text()
        self.assertNotIn(TELEGRAM_TOKEN, text)
        self.assertNotIn("TESTETOKEN", text)
        self.assertIn("TELEGRAM_BOT_TOKEN: definido", text)
        self.assertIn("TELEGRAM_ALLOWED_USER_ID: 42", text)
        self.assertIn("JARVIS_CHECKIN_EVENING_AT: 18:30", text)
        env_file = context.env_path
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
        values = parse_env(env_file.read_text(encoding="utf-8"))
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], TELEGRAM_TOKEN)
        self.assertEqual(values["TELEGRAM_ALLOWED_USER_ID"], "42")
        self.assertEqual(values["TELEGRAM_VOICE_REPLY"], "off")
        self.assertEqual(values["JARVIS_CHECKIN"], "on")
        self.assertEqual(values["JARVIS_CHECKIN_MORNING"], "on")
        self.assertEqual(values["JARVIS_CHECKIN_EVENING"], "on")
        self.assertEqual(values["JARVIS_CHECKIN_EVENING_AT"], "18:30")
        self.assertNotIn("JARVIS_VAULT", values)
        plist = context.autostart.plist_path.read_text(encoding="utf-8")
        self.assertIn("jarvis.main", plist)
        self.assertNotIn("jarvis.telegram", plist)
        self.assertNotIn(TELEGRAM_TOKEN, plist)
        joined = [" ".join(call) for call in runner.calls]
        self.assertTrue(all(TELEGRAM_TOKEN not in item for item in joined))

    def test_env_load_keeps_shell_telegram_token(self):
        from jarvis.envfile import load_env

        path = self.tmp / "local.env"
        path.write_text(
            "export TELEGRAM_ALLOWED_USER_ID=42\n"
            'JARVIS_CHECKIN_EVENING_AT="19:05"\n'
            "TELEGRAM_BOT_TOKEN=" + TELEGRAM_TOKEN + "\n",
            encoding="utf-8",
        )
        environ = {"TELEGRAM_BOT_TOKEN": "ja-definido"}
        self.assertTrue(load_env(path, environ))
        self.assertEqual(environ["TELEGRAM_ALLOWED_USER_ID"], "42")
        self.assertEqual(environ["JARVIS_CHECKIN_EVENING_AT"], "19:05")
        self.assertEqual(environ["TELEGRAM_BOT_TOKEN"], "ja-definido")

    def test_doctor_hides_the_telegram_token(self):
        from jarvis.doctor import telegram_report

        leaked = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/getMe"

        def probe(_token):
            raise RuntimeError(leaked)

        status, detail, _fix = telegram_report(TELEGRAM_TOKEN, None, "", probe)
        self.assertEqual(status, "FALHA")
        self.assertNotIn(TELEGRAM_TOKEN, detail)
        self.assertNotIn("TESTETOKEN", detail)
        status, detail, _fix = telegram_report(TELEGRAM_TOKEN, 42, "42", probe)
        self.assertEqual(status, "AVISO")
        self.assertNotIn(TELEGRAM_TOKEN, detail)
        self.assertNotIn("TESTETOKEN", detail)


class ConsoleTest(unittest.TestCase):
    def test_confirm_and_secret_do_not_echo_the_secret(self):
        from jarvis.setup import Console

        answers = iter(["", "s"])
        lines = []
        console = Console(
            input_fn=lambda _prompt: next(answers),
            output_fn=lines.append,
            secret_fn=lambda _prompt: TOKEN,
        )
        self.assertFalse(console.confirm("Seguir", default=False))
        self.assertTrue(console.confirm("Seguir", default=False))
        self.assertEqual(console.secret("Token"), TOKEN)
        self.assertNotIn(TOKEN, "\n".join(lines))

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            noisy = Console(
                input_fn=lambda _prompt: TOKEN,
                output_fn=print,
                secret_fn=lambda _prompt: (_ for _ in ()).throw(OSError("sem tty")),
            )
            value = noisy.secret("Token")
        self.assertEqual(value, TOKEN)
        self.assertNotIn(TOKEN, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
