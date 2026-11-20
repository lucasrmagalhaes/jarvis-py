import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis import doctor
from jarvis.autostart import AutoState


class FakeAuto:
    def __init__(self, state):
        self._state = state

    def status(self):
        return self._state


class DoctorConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        doctor.results.clear()

    def tearDown(self):
        import shutil

        doctor.results.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def capture(self, callback):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            callback()
        return buffer.getvalue()

    def test_env_file_warning_does_not_print_secrets(self):
        path = self.tmp / ".env"
        path.write_text(
            "JIRA_TOKEN=token-secreto\nGMAIL_APP_PASSWORD=senha secreta\n",
            encoding="utf-8",
        )
        if os.name == "nt":
            with unittest.mock.patch(
                "jarvis.doctor.permissions_restricted", return_value=False
            ):
                text = self.capture(lambda: doctor.check_env_file(path))
        else:
            os.chmod(path, 0o644)
            text = self.capture(lambda: doctor.check_env_file(path))
        self.assertIn("AVISO", text)
        self.assertIn("python -m jarvis.setup", text)
        self.assertNotIn("token-secreto", text)
        self.assertNotIn("senha secreta", text)

        private = self.tmp / ".jarvis" / ".env"
        private.parent.mkdir()
        private.write_text("JIRA_TOKEN=token-secreto\n", encoding="utf-8")
        doctor.results.clear()
        if os.name == "nt":
            with unittest.mock.patch(
                "jarvis.doctor.permissions_restricted", return_value=True
            ):
                ok_text = self.capture(lambda: doctor.check_env_file(private))
        else:
            os.chmod(private, 0o600)
            ok_text = self.capture(lambda: doctor.check_env_file(private))
            self.assertEqual(stat.S_IMODE(private.stat().st_mode) & 0o077, 0)
        self.assertIn("OK", ok_text)
        self.assertNotIn("token-secreto", ok_text)

    def test_missing_env_file_points_at_setup(self):
        missing = self.tmp / "ausente.env"
        text = self.capture(lambda: doctor.check_env_file(missing))
        self.assertIn("ausente", text)
        self.assertIn("python -m jarvis.setup", text)

    def test_integrations_show_state_without_secrets(self):
        env = {
            "JIRA_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "pessoa@example.com",
            "JIRA_TOKEN": "token-secreto",
            "GMAIL_EMAIL": "pessoa@example.com",
            "GMAIL_APP_PASSWORD": "senha secreta",
        }
        text = self.capture(
            lambda: doctor.check_integrations(github_state="ok", env=env)
        )
        self.assertIn("Jira: configurado em example.atlassian.net", text)
        self.assertEqual(
            doctor._public_host(
                "https://pessoa:token-secreto@example.atlassian.net:443/jira"
            ),
            "example.atlassian.net",
        )
        self.assertIn("Gmail: configurado", text)
        self.assertIn("gh autenticado", text)
        self.assertNotIn("token-secreto", text)
        self.assertNotIn("senha secreta", text)
        self.assertNotIn("pessoa@example.com", text)

        doctor.results.clear()
        partial = {
            "JIRA_URL": "https://example.atlassian.net",
            "JIRA_TOKEN": "token-secreto",
        }
        warning = self.capture(
            lambda: doctor.check_integrations(github_state="anonymous", env=partial)
        )
        self.assertIn("incompleto, falta JIRA_EMAIL", warning)
        self.assertIn("gh sem login", warning)
        self.assertIn("gh auth login", warning)
        self.assertNotIn("token-secreto", warning)
        self.assertNotIn("https://example.atlassian.net", warning)

        doctor.results.clear()
        absent = self.capture(
            lambda: doctor.check_integrations(github_state="missing", env={})
        )
        self.assertIn("Jira: não configurado", absent)
        self.assertIn("Gmail: não configurado", absent)
        self.assertIn("gh não instalado", absent)

        doctor.results.clear()
        broken = self.capture(
            lambda: doctor.check_integrations(github_state="error", env={})
        )
        self.assertIn("gh auth status", broken)

    def test_autostart_line(self):
        text = self.capture(
            lambda: doctor.check_autostart(
                FakeAuto(AutoState(True, "ativo, LaunchAgent"))
            )
        )
        self.assertIn("Início automático: ativo, LaunchAgent", text)
        doctor.results.clear()
        off = self.capture(
            lambda: doctor.check_autostart(FakeAuto(AutoState(False, "desligado")))
        )
        self.assertIn("Início automático: desligado", off)
        self.assertIn("OK", off)

    def test_help_explains_corrigir_without_touching_the_machine(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = doctor.main(["--help"])
        text = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("--corrigir", text)
        self.assertIn("Não grava chave", text)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.main(["--outro"]), 2)

    def test_corrigir_creates_a_private_env_and_installs_only_what_is_missing(self):
        target = self.tmp / ".jarvis" / ".env"
        obsidian = self.tmp / ".obsidian" / "app.json"
        obsidian.parent.mkdir()
        obsidian.write_text("{}\n", encoding="utf-8")
        before = obsidian.read_bytes()
        installed = []

        def installer(packages):
            installed.extend(packages)
            return True

        created = doctor.apply_fixes(
            env_file=target,
            missing=["faster-whisper"],
            installer=installer,
            probe=lambda _package: True,
        )
        text = "\n".join(created)
        self.assertIn("arquivo de ambiente", text)
        self.assertIn("Instalei as dependências: faster-whisper.", text)
        self.assertEqual(installed, ["faster-whisper"])
        self.assertTrue(target.is_file())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o077, 0)
        stored = target.read_text(encoding="utf-8")
        self.assertNotIn("JIRA_TOKEN", stored)
        self.assertNotIn("=", stored)
        self.assertEqual(obsidian.read_bytes(), before)

        installed.clear()
        again = doctor.apply_fixes(env_file=target, missing=[], installer=installer)
        self.assertEqual(installed, [])
        self.assertIn("Nada automático", " ".join(again))
        self.assertEqual(target.read_text(encoding="utf-8"), stored)

    def test_corrigir_tightens_permissions_without_printing_the_secret(self):
        target = self.tmp / ".env"
        target.write_text("JIRA_TOKEN=token-secreto\n", encoding="utf-8")
        os.chmod(target, 0o644)
        text = "\n".join(
            doctor.apply_fixes(env_file=target, missing=[], installer=lambda _packages: False)
        )
        self.assertNotIn("token-secreto", text)
        self.assertIn("token-secreto", target.read_text(encoding="utf-8"))
        if os.name != "nt":
            self.assertIn("Restringi", text)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o077, 0)

    def test_corrigir_does_not_claim_success_when_pip_exits_nonzero(self):
        target = self.tmp / ".env"
        target.write_text("\n", encoding="utf-8")
        os.chmod(target, 0o600)

        def installer(_packages):
            return 1

        text = "\n".join(
            doctor.apply_fixes(
                env_file=target,
                missing=["sounddevice"],
                installer=installer,
                probe=lambda _package: False,
            )
        )
        self.assertNotIn("Instalei as dependências", text)
        self.assertIn("Não instalei as dependências (sounddevice).", text)
        self.assertIn("código 1", text)
        self.assertIn("python -m jarvis.setup", text)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)

    def test_corrigir_checks_what_actually_imports(self):
        target = self.tmp / ".env"
        target.write_text("\n", encoding="utf-8")
        os.chmod(target, 0o600)
        text = "\n".join(
            doctor.apply_fixes(
                env_file=target,
                missing=["sounddevice", "edge-tts"],
                installer=lambda _packages: 0,
                probe=lambda _package: False,
            )
        )
        self.assertNotIn("Instalei as dependências", text)
        self.assertIn("não importam", text)
        self.assertIn("sounddevice", text)
        self.assertIn("edge-tts", text)
        self.assertIn("python -m jarvis.setup", text)

    def test_corrigir_installs_audio_and_voice_when_wake_pip_fails(self):
        target = self.tmp / ".env"
        target.write_text("\n", encoding="utf-8")
        os.chmod(target, 0o600)
        calls = []

        def installer(packages):
            calls.append(list(packages))
            if any("openwakeword" in item for item in packages):
                return 1
            return 0

        def missing(mapping):
            values = list(mapping.values())
            if "edge-tts" in values:
                return ["edge-tts", "soundfile"]
            if "sounddevice" in values:
                return ["sounddevice"]
            return []

        with (
            unittest.mock.patch("jarvis.doctor.missing_packages", side_effect=missing),
            unittest.mock.patch("jarvis.doctor.wakeword_usable", return_value=False),
            unittest.mock.patch("jarvis.deps.tflite_unavailable", return_value=True),
        ):
            text = "\n".join(
                doctor.apply_fixes(
                    env_file=target,
                    installer=installer,
                    probe=lambda package: "openwakeword" not in package,
                )
            )
        self.assertIn("Instalei as dependências: sounddevice.", text)
        self.assertIn("Instalei as dependências: edge-tts.", text)
        self.assertIn("Instalei as dependências: soundfile.", text)
        self.assertNotIn("Instalei as dependências: openwakeword", text)
        self.assertIn("Não instalei as dependências (openwakeword>=0.6).", text)
        self.assertIn("código 1", text)
        self.assertIn("python -m jarvis.chat", text)
        self.assertIn("ONNX", text)
        self.assertIn("tflite-runtime", text)
        wake = next(call for call in calls if any("openwakeword" in item for item in call))
        self.assertNotIn("sounddevice", wake)
        self.assertNotIn("edge-tts", wake)
        self.assertNotIn("soundfile", wake)

    def test_wakeword_warning_explains_the_text_mode(self):
        with (
            unittest.mock.patch("jarvis.doctor.wakeword_usable", return_value=False),
            unittest.mock.patch("jarvis.deps.tflite_unavailable", return_value=True),
        ):
            text = self.capture(doctor.check_wakeword)
        self.assertIn("AVISO", text)
        self.assertIn("python -m jarvis.chat", text)
        self.assertIn("ONNX", text)
        self.assertIn("tflite-runtime", text)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)

        doctor.results.clear()
        with unittest.mock.patch("jarvis.doctor.wakeword_usable", return_value=True):
            ready = self.capture(doctor.check_wakeword)
        self.assertIn("backend ONNX", ready)
        self.assertIn("OK", ready)

    def test_pip_install_uses_the_process_exit_code(self):
        def fake_run(args, **_kwargs):
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "ERROR: No matching distribution found for tflite-runtime<3,>=2.8.0",
            )

        with unittest.mock.patch("jarvis.doctor.subprocess.run", side_effect=fake_run):
            code = doctor._pip_install(["sounddevice", "edge-tts", "soundfile"])
        self.assertEqual(code, 1)

        calls = []

        def wake_run(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")

        with unittest.mock.patch("jarvis.doctor.subprocess.run", side_effect=wake_run):
            wake_code = doctor._pip_install(["openwakeword>=0.6"])
        self.assertEqual(wake_code, 0)
        joined = "\n".join(" ".join(call) for call in calls)
        self.assertIn("requirements-wake-deps.txt", joined)
        self.assertIn("requirements-wake.txt", joined)
        self.assertIn("--no-deps", joined)
        self.assertNotIn("tflite", joined)
        self.assertNotIn("sounddevice", joined)
        self.assertNotIn("edge-tts", joined)
        self.assertNotIn("soundfile", joined)

    def test_radar_line_follows_the_flag(self):
        saved = os.environ.get("JARVIS_RADAR")
        os.environ["JARVIS_RADAR"] = "off"
        try:
            text = self.capture(doctor.check_radar)
        finally:
            if saved is None:
                os.environ.pop("JARVIS_RADAR", None)
            else:
                os.environ["JARVIS_RADAR"] = saved
        self.assertIn("JARVIS_RADAR=off", text)
        self.assertIn("AVISO", text)


if __name__ == "__main__":
    unittest.main()
