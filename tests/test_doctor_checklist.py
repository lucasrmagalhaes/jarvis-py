"""Checklist do diagnóstico, sem rede, sem microfone e sem nota real."""

import io
import os
import shutil
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

from jarvis import doctor
from jarvis.procutil import command_argv

ENV_KEYS = (
    "JARVIS_VAULT",
    "JARVIS_VAULT_REMOTE",
    "JARVIS_VAULT_SYNC",
    "JARVIS_VAULT_BRANCH",
    "JARVIS_GIT_BIN",
    "JARVIS_DOCTOR_GIT_TIMEOUT",
    "JARVIS_SKIP_HARDWARE",
    "READWISE_TOKEN",
)


class DoctorChecklistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        doctor.results.clear()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        doctor.results.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def capture(self, callback):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            callback()
        return buffer.getvalue()

    def test_python_version_gate(self):
        status, detail, fix = doctor.python_status((3, 9, 1))
        self.assertEqual(status, doctor.FAIL)
        self.assertEqual(detail, "3.9.1")
        self.assertIn("3.10", fix)
        status, detail, fix = doctor.python_status((3, 12, 3))
        self.assertEqual(status, doctor.OK)
        self.assertEqual(detail, "3.12.3")
        self.assertEqual(fix, "")
        text = self.capture(doctor.check_python)
        self.assertIn("Python:", text)
        self.assertNotIn("\u2014", text)

    def test_readwise_presence_never_prints_the_token(self):
        secret = "super-segredo-readwise"
        absent = self.capture(
            lambda: doctor.check_integrations(github_state="missing", env={})
        )
        self.assertIn("Readwise: token ausente", absent)
        self.assertIn("READWISE_TOKEN", absent)
        self.assertNotIn(secret, absent)
        doctor.results.clear()
        present = self.capture(
            lambda: doctor.check_integrations(
                github_state="missing",
                env={"READWISE_TOKEN": secret},
            )
        )
        self.assertIn("Readwise: token presente", present)
        self.assertNotIn(secret, present)

    def test_ollama_is_optional(self):
        missing = self.capture(lambda: doctor.check_ollama(which=lambda _name: None))
        self.assertIn("AVISO", missing)
        self.assertIn("opcional, comando ausente", missing)
        self.assertIn("ollama", missing.casefold())
        doctor.results.clear()
        found = self.capture(
            lambda: doctor.check_ollama(which=lambda _name: r"C:\Ollama\ollama.exe")
        )
        self.assertIn("comando encontrado", found)
        self.assertIn("OK", found)

    def test_claude_cmd_is_invoked_without_shell(self):
        script = self.tmp / "claude.cmd"
        script.write_text("@echo off\r\n", encoding="utf-8", newline="\n")
        seen = []

        def runner(command):
            seen.append(list(command))
            return subprocess.CompletedProcess(command, 0, "", "")

        text = self.capture(
            lambda: doctor.check_claude(which=lambda _name: str(script), runner=runner)
        )
        self.assertEqual(seen[0][1:], ["/c", str(script), "-p", "--output-format", "json"])
        self.assertEqual(seen[0], command_argv(script, "-p", "--output-format", "json"))
        self.assertIn("Claude Code", text)
        self.assertIn("Login do Claude", text)
        self.assertNotIn("shell=True", text)

    def test_microphone_skips_without_hardware_or_library(self):
        os.environ["JARVIS_SKIP_HARDWARE"] = "1"
        skipped = self.capture(doctor.check_microphone)
        self.assertIn("checagem pulada", skipped)
        self.assertIn("JARVIS_SKIP_HARDWARE", skipped)
        os.environ.pop("JARVIS_SKIP_HARDWARE", None)
        doctor.results.clear()
        with mock.patch.dict(sys.modules, {"sounddevice": None}):
            missing = self.capture(doctor.check_microphone)
        self.assertIn("dependências de áudio ausentes", missing)
        self.assertIn("AVISO", missing)

    def test_vault_exists_is_a_repo_and_remote_times_out(self):
        missing = self.tmp / "nao-existe"
        os.environ["JARVIS_VAULT"] = str(missing)
        text = self.capture(doctor.check_vault)
        self.assertIn("FALHA", text)
        self.assertIn("não existe", text)
        doctor.results.clear()

        loose = self.tmp / "solta"
        loose.mkdir()
        os.environ["JARVIS_VAULT"] = str(loose)
        text = self.capture(doctor.check_vault)
        self.assertIn("não é um repositório git", text)
        doctor.results.clear()

        repo, bare = self._repo()
        os.environ["JARVIS_VAULT"] = str(repo)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        os.environ["JARVIS_DOCTOR_GIT_TIMEOUT"] = "2"
        ready = self.capture(doctor.check_vault)
        self.assertIn("acesso ao git concluído", ready)
        self.assertNotIn("FALHA", ready)
        doctor.results.clear()

        real = subprocess.run

        def expire(args, **kwargs):
            if "fetch" in args:
                raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 2))
            return real(args, **kwargs)

        with mock.patch("jarvis.procutil.subprocess.run", side_effect=expire):
            timed = self.capture(doctor.check_vault)
        self.assertIn("tempo esgotado", timed)
        self.assertIn("AVISO", timed)
        self.assertIn("2s", timed)

    def test_module_doctor_command_prints_help(self):
        from jarvis.__main__ import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["doctor", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--corrigir", buffer.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["falar"]), 2)

    def _repo(self):
        repo = self.tmp / "vault"
        bare = self.tmp / "remote.git"
        repo.mkdir()
        self._git("init", "-b", "main", str(repo))
        self._git("-C", str(repo), "config", "user.email", "teste@example.com")
        self._git("-C", str(repo), "config", "user.name", "Teste")
        (repo / "AGENTS.md").write_text("convenção de teste\n", encoding="utf-8", newline="\n")
        (repo / "CLAUDE.md").write_text("# teste\n", encoding="utf-8", newline="\n")
        (repo / "nota.md").write_text("texto sintetico\n", encoding="utf-8", newline="\n")
        self._git("-C", str(repo), "add", "-A")
        self._git("-C", str(repo), "commit", "-m", "base")
        self._git("init", "--bare", "-b", "main", str(bare))
        self._git("-C", str(repo), "remote", "add", "origin", str(bare))
        self._git("-C", str(repo), "push", "-u", "origin", "HEAD:main")
        return repo, bare

    def _git(self, *args):
        subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


if __name__ == "__main__":
    unittest.main()
