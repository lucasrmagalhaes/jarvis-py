import os
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.brain import Brain, BrainError
from jarvis.routines import classify, help_speech, offline_answer, run_routine
from jarvis.vault import SyncResult

ENV = (
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_WORKSPACE",
    "JARVIS_HOME",
    "JARVIS_PROMPT_FILE",
    "JARVIS_LOG",
)
NOW = datetime(2026, 10, 28, 8, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


class LocalVault:
    def __init__(self, path):
        self.path = path
        self.sync = False
        self.blocked = False

    def prepare(self):
        return SyncResult(True, "ready", "Vault local.")

    def publish(self, text):
        return SyncResult(True, "skipped", "ok")

    def agents_for_prompt(self):
        return "Convenções de teste."

    def hud_payload(self):
        return {"pending": 0}


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = {key: os.environ.get(key) for key in ENV}
        self._path = os.environ.get("PATH", "")
        for key in ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        from jarvis import config

        self._claude = config.CLAUDE_BIN
        config.CLAUDE_BIN = "jarvis-claude-ausente-9516"

    def tearDown(self):
        import shutil

        from jarvis import config

        config.CLAUDE_BIN = self._claude
        os.environ["PATH"] = self._path
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_help_lists_daily_commands_without_calling_claude(self):
        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        reply = brain.ask("Hey Jarvis, ajuda")
        folded = reply.casefold()
        self.assertIn("como foi meu dia", folded)
        self.assertIn("revisão do dia", folded)
        self.assertIn("retoma a revisão", folded)
        self.assertIn("acertei", folded)
        self.assertIn("silencia esse aviso hoje", folded)
        self.assertIn("pausa os alertas até amanhã", folded)
        self.assertIn("nos livros", folded)
        self.assertIn("nos vídeos", folded)
        self.assertIn("nos cursos", folded)
        self.assertIn("o que os assistentes mandaram", folded)
        self.assertIn("python -m jarvis.setup", reply)
        self.assertNotIn("PATH", reply)
        self.assertNotIn("\u2014", reply)
        self.assertNotIn("\u2013", reply)
        again = run_routine(self.tmp, classify("o que você faz?"), NOW)
        self.assertIn("me lembra", again)
        self.assertNotIn("python -m jarvis.setup", again)

    def test_free_question_searches_the_vault_and_explains_install(self):
        notes = self.tmp / "notas"
        notes.mkdir()
        hidden = notes / ".obsidian" / "segredo.md"
        hidden.parent.mkdir()
        hidden.write_text("# Segredo\n\nsenha-super-secreta do cofre\n", encoding="utf-8")
        (notes / "Farol.md").write_text(
            "# Farol\n\nO Farol e um app de musica local.\n",
            encoding="utf-8",
        )
        found = offline_answer("me explica o Farol", notes)
        self.assertIn("Farol", found)
        self.assertIn("musica", found.casefold())
        self.assertIn("jarvis-claude-ausente-9516", found)
        self.assertIn("login", found)
        self.assertNotIn("senha-super-secreta", found)
        self.assertNotIn("\u2014", found)

        empty = offline_answer("xyzzy blorg", notes)
        self.assertIn("bom dia", empty)
        self.assertIn("PATH", empty)
        self.assertNotIn("xyzzy", empty)

        brain = Brain()
        brain.vault = LocalVault(notes)
        reply = brain.ask("me explica o Farol")
        self.assertIn("musica", reply.casefold())
        self.assertIn("PATH", reply)
        self.assertTrue(any("musica" in text.casefold() for _who, text in brain.memory.turns))

    def test_claude_error_is_not_replaced_by_the_local_answer(self):
        bindir = self.tmp / "bin"
        bindir.mkdir()
        script = bindir / "falso-claude"
        script.write_text(
            "#!/usr/bin/env python3\nimport sys\nraise SystemExit(3)\n",
            encoding="utf-8",
            newline="\n",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        os.environ["PATH"] = str(bindir) + os.pathsep + self._path
        from jarvis import config

        config.CLAUDE_BIN = "falso-claude"
        brain = Brain()
        with self.assertRaises(BrainError) as caught:
            brain.ask("conta uma piada sobre o cafe")
        self.assertNotIn("PATH", str(caught.exception))
        self.assertNotIn("bom dia", str(caught.exception))

    def test_help_speech_stays_short_without_dashes(self):
        text = help_speech(True).casefold()
        self.assertIn("como foi minha semana", text)
        self.assertIn("revisão do dia", text)
        self.assertIn("silencia sempre", text)
        self.assertIn("nos cursos", text)
        self.assertNotIn("setup", text)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)
