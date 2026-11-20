"""Persona, Ollama, fontes, resumo de domingo e cérebro no doctor."""

import io
import os
import shutil
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis import config, doctor
from jarvis.brain import UNTRUSTED, VAULT_RULES, Brain, stable_prefix
from jarvis.cerebro import (
    Backend,
    CerebroError,
    choose_backend,
    complete,
    model_ready,
    pergunta_simples,
    register_backend,
    report_status,
    reset_backends,
)
from jarvis.chat import HELP
from jarvis.checkins import digest_due
from jarvis.companion import Companion
from jarvis.fontes import sources_speech
from jarvis.persona import PERSONA, persona_speech, persona_text
from jarvis.routines import classify, help_speech, run_routine
from jarvis.telegram import TelegramBot
from jarvis.vault import SyncResult

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 11, 0, tzinfo=TZ)
SUNDAY = datetime(2026, 11, 1, 19, 0, tzinfo=TZ)
ENV = (
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_WORKSPACE",
    "JARVIS_HOME",
    "JARVIS_STATE",
    "JARVIS_PROMPT_FILE",
    "JARVIS_PERSONA",
    "JARVIS_CEREBRO",
    "JARVIS_OLLAMA_URL",
    "JARVIS_OLLAMA_MODEL",
    "JARVIS_OLLAMA_TIMEOUT",
    "JARVIS_DIGEST",
    "JARVIS_DIGEST_AT",
    "JARVIS_CHECKIN",
    "JARVIS_CHECKIN_MORNING",
    "JARVIS_CHECKIN_EVENING",
    "JARVIS_CHECKIN_EVENING_AT",
    "JARVIS_READWISE_PASTA",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
)


class LocalVault:
    def __init__(self, path):
        self.path = path
        self.sync = False
        self.blocked = False

    def prepare(self):
        return SyncResult(True, "ready", "ok")

    def publish(self, text):
        return SyncResult(True, "skipped", "ok")

    def resync_snapshot(self):
        return None

    def hud_payload(self):
        return {}

    def agents_for_prompt(self):
        return "Convenções fixas."


class Rodada16Test(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_STATE"] = str(self.tmp / "home" / "state.json")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        self._claude = config.CLAUDE_BIN
        reset_backends()
        doctor.results.clear()

    def tearDown(self):
        config.CLAUDE_BIN = self._claude
        reset_backends()
        doctor.results.clear()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _brain(self):
        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        return brain

    def test_persona_padrao_e_nota_no_prefixo_estavel(self):
        self.assertEqual(classify("Mostra sua persona.").kind, "persona")
        self.assertEqual(classify("mostrar a sua persona").kind, "persona")
        self.assertNotEqual(classify("mostra sua personalidade").kind, "persona")
        brain = self._brain()
        padrao = brain.ask("mostra sua persona")
        self.assertIn("persona padrão", padrao)
        self.assertIn("português do Brasil", padrao)
        self.assertNotIn("\u2014", padrao)
        self.assertIn("mostra sua persona", help_speech(True))
        self.assertIn("mostra sua persona", HELP)

        root = self.tmp / "vault"
        note = root / "Jarvis" / "Persona.md"
        note.parent.mkdir(parents=True)
        note.write_text(
            "---\natualizado: 2026-01-01\n---\r\nFale como mordomo calmo.\r\n",
            encoding="utf-8",
        )
        self.assertEqual(persona_text(root), "Fale como mordomo calmo.")
        self.assertNotIn("2026-01-01", persona_text(root))
        said = persona_speech(root)
        self.assertIn("Jarvis/Persona.md", said)
        self.assertIn("mordomo calmo", said)
        self.assertNotIn("2026-01-01", said)
        self.assertNotIn("\u2014", said)

        class Fake:
            def __init__(self, path):
                self.path = path

            def agents_for_prompt(self):
                return "Convenções fixas."

        brain.vault = Fake(root)
        brain._write_prompt()
        first = Path(os.environ["JARVIS_PROMPT_FILE"]).read_text(encoding="utf-8")
        brain._write_prompt()
        second = Path(os.environ["JARVIS_PROMPT_FILE"]).read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("Fale como mordomo calmo.\n\nConvenções fixas."))
        self.assertLess(first.index("mordomo calmo"), first.index("Convenções fixas."))
        self.assertLess(first.index("Convenções fixas."), first.index("linguagem direta"))
        self.assertLess(first.index("linguagem direta"), first.index("dado-nao-confiavel"))
        self.assertNotIn("Tony Stark", first)
        self.assertNotIn("2026-01-01", first)
        self.assertNotRegex(first, r"\d{2}:\d{2}")
        expected = stable_prefix(
            "Fale como mordomo calmo.",
            "Convenções fixas.",
            VAULT_RULES,
            UNTRUSTED,
        )
        self.assertEqual(first, expected)
        asked = brain.ask("mostra sua persona")
        self.assertIn("mordomo calmo", asked)
        self.assertNotIn("2026-01-01", asked)

        os.environ["JARVIS_PERSONA"] = "Notas/Tom.md"
        custom = root / "Notas" / "Tom.md"
        custom.parent.mkdir(parents=True)
        custom.write_text("Tom seco e curto.\n", encoding="utf-8")
        self.assertEqual(persona_text(root), "Tom seco e curto.")
        brain._write_prompt()
        rewritten = Path(os.environ["JARVIS_PROMPT_FILE"]).read_text(encoding="utf-8")
        self.assertIn("Tom seco e curto.", rewritten)
        self.assertNotIn("mordomo calmo", rewritten)

        outside = self.tmp / "segredo.md"
        outside.write_text("TEXTO_FORA_DO_VAULT\n", encoding="utf-8")
        hidden = root / ".obsidian" / "Persona.md"
        hidden.parent.mkdir(parents=True)
        hidden.write_text("TEXTO_OBSIDIAN\n", encoding="utf-8")
        for unsafe in ("../segredo.md", ".obsidian/Persona.md", "/tmp/Persona.md"):
            os.environ["JARVIS_PERSONA"] = unsafe
            self.assertEqual(persona_text(root), PERSONA)
            self.assertIn("persona padrão", persona_speech(root))
        brain._write_prompt()
        safe = Path(os.environ["JARVIS_PROMPT_FILE"]).read_text(encoding="utf-8")
        self.assertIn("Tony Stark", safe)
        self.assertNotIn("TEXTO_FORA_DO_VAULT", safe)
        self.assertNotIn("TEXTO_OBSIDIAN", safe)

        huge = root / "Jarvis" / "Persona.md"
        os.environ["JARVIS_PERSONA"] = "Jarvis/Persona.md"
        huge.write_text("a" * 5000 + " FIMUNICO", encoding="utf-8")
        loaded = persona_text(root)
        self.assertLessEqual(len(loaded), 4000)
        self.assertNotIn("FIMUNICO", loaded)
        self.assertEqual(loaded, persona_text(root))

    def test_ollama_responde_pergunta_simples_e_cai_para_o_claude(self):
        self.assertTrue(pergunta_simples("qual a capital da franca?"))
        self.assertFalse(pergunta_simples("cria uma nota sobre paris"))
        self.assertFalse(pergunta_simples("a" * 241))
        self.assertTrue(pergunta_simples("a" * 240))
        os.environ["JARVIS_CEREBRO"] = "ollama"

        def transport(method, url, payload, timeout):
            self.assertEqual(method, "POST")
            self.assertEqual(url, "http://127.0.0.1:11434/api/chat")
            self.assertEqual(payload["model"], "llama3.2")
            self.assertFalse(payload["stream"])
            self.assertIn("Tony Stark", payload["messages"][0]["content"])
            self.assertIn("capital da franca", payload["messages"][1]["content"])
            return {"message": {"content": "Paris\u2014senhor."}}

        brain = self._brain()
        brain.ollama_transport = transport
        reply = brain.ask("qual a capital da franca?")
        self.assertEqual(reply, "Paris, senhor.")
        self.assertNotIn("\u2014", reply)
        self.assertIsNone(brain.session_id)

        calls = []

        def down(method, url, payload, timeout):
            calls.append(method)
            raise CerebroError("off")

        brain.ollama_transport = down
        brain._ask = lambda *_args, **_kwargs: "Pelo Claude, senhor."
        fallback = brain.ask("qual a capital da franca?")
        self.assertEqual(fallback, "Pelo Claude, senhor.")
        self.assertEqual(calls, ["POST"])

        skipped = []

        def forbidden(method, url, payload, timeout):
            skipped.append(method)
            raise AssertionError("ollama")

        brain.ollama_transport = forbidden
        brain._ask = lambda *_args, **_kwargs: "Escrita no Claude, senhor."
        complex_reply = brain.ask("cria uma nota sobre paris")
        self.assertEqual(complex_reply, "Escrita no Claude, senhor.")
        self.assertEqual(skipped, [])

        seen = {}

        class Fake(Backend):
            name = "ollama"

            def answer(self, system, user, transport=None):
                seen["user"] = user
                return "Pelo modelo local, senhor."

        register_backend("ollama", lambda: Fake())
        brain._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("claude"))
        plugged = brain.ask("que horas o mercado fecha?")
        self.assertEqual(plugged, "Pelo modelo local, senhor.")
        self.assertIn("mercado fecha", seen["user"])

        os.environ["JARVIS_OLLAMA_URL"] = "http://127.0.0.1:11435"
        os.environ["JARVIS_OLLAMA_MODEL"] = "qwen2.5"
        captured = {}

        def custom(method, url, payload, timeout):
            captured["url"] = url
            captured["model"] = payload["model"]
            return {"message": {"content": "Certo, senhor."}}

        self.assertEqual(complete("sistema", "pergunta", transport=custom), "Certo, senhor.")
        self.assertEqual(captured["url"], "http://127.0.0.1:11435/api/chat")
        self.assertEqual(captured["model"], "qwen2.5")
        self.assertTrue(
            model_ready(
                "http://127.0.0.1:11434",
                "llama3.2",
                5,
                transport=lambda *_args: {"models": [{"name": "llama3.2:latest"}]},
            )
        )

    def test_ollama_indisponivel_busca_no_vault(self):
        os.environ["JARVIS_CEREBRO"] = "ollama"
        root = self.tmp / "vault"
        folder = root / "Notas"
        folder.mkdir(parents=True)
        (folder / "Franca.md").write_text(
            "# Franca\n\nParis fica na Franca de teste.\n",
            encoding="utf-8",
        )
        config.CLAUDE_BIN = "jarvis-claude-ausente-9516"
        brain = Brain()
        brain.vault = LocalVault(root)

        def down(method, url, payload, timeout):
            raise CerebroError("off")

        brain.ollama_transport = down
        reply = brain.ask("onde fica Paris na Franca?")
        self.assertIn("Franca", reply)
        self.assertIn("jarvis-claude-ausente-9516", reply)
        self.assertNotIn("\u2014", reply)

    def test_doctor_diz_o_backend(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            doctor.check_cerebro(transport=lambda *_args: (_ for _ in ()).throw(AssertionError("rede")))
        self.assertIn("Claude Code", buffer.getvalue())

        os.environ["JARVIS_CEREBRO"] = "desconhecido"
        doctor.results.clear()
        status, detail, _fix = report_status(transport=lambda *_args: (_ for _ in ()).throw(AssertionError("rede")))
        self.assertEqual(status, "warn")
        self.assertIn("Claude Code", detail)

        os.environ["JARVIS_CEREBRO"] = "ollama"
        os.environ["JARVIS_OLLAMA_MODEL"] = "llama3.2"

        def tags(method, url, payload, timeout):
            self.assertEqual(method, "GET")
            self.assertTrue(url.endswith("/api/tags"))
            return {"models": [{"name": "llama3.2"}]}

        status, detail, _fix = report_status(transport=tags)
        self.assertEqual(status, "ok")
        self.assertIn("llama3.2", detail)

        def down(method, url, payload, timeout):
            raise CerebroError("off")

        status, detail, fix = report_status(transport=down)
        self.assertEqual(status, "warn")
        self.assertIn("busca do vault", detail)
        self.assertIn("JARVIS_OLLAMA_URL", fix)

        status, detail, _fix = report_status(
            transport=lambda *_args: {"models": [{"name": "outro"}]}
        )
        self.assertEqual(status, "warn")
        self.assertIn("sem o modelo", detail)

        os.environ["JARVIS_OLLAMA_URL"] = "http://user:segredo@127.0.0.1:11434"
        status, detail, _fix = report_status(
            transport=lambda *_args: (_ for _ in ()).throw(AssertionError("rede"))
        )
        self.assertEqual(status, "warn")
        self.assertNotIn("segredo", detail)
        self.assertEqual(choose_backend("qual a capital da franca?").name, "ollama")

        doctor.results.clear()
        text = io.StringIO()
        with redirect_stdout(text):
            doctor.check_digest()
        self.assertIn("desligado", text.getvalue())
        os.environ["JARVIS_DIGEST"] = "on"
        os.environ["TELEGRAM_BOT_TOKEN"] = "token-de-teste"
        os.environ["TELEGRAM_ALLOWED_USER_ID"] = "42"
        doctor.results.clear()
        ready = io.StringIO()
        with redirect_stdout(ready):
            doctor.check_digest()
        shown = ready.getvalue()
        self.assertIn("domingo", shown)
        self.assertIn("18:30", shown)
        self.assertNotIn("token-de-teste", shown)

    def test_quais_fontes_conta_sem_texto(self):
        self.assertEqual(classify("Quais fontes tenho?").kind, "sources")
        self.assertNotEqual(classify("quais fontes tenho hoje").kind, "sources")
        root = self.tmp / "vault"
        self._note(
            root / "Tecnologia" / "Livros" / "hortela.md",
            "---\ntipo: livro\n---\n# Hortela de teste\n\n"
            "corpo do livro que nao pode sair\n\n"
            "O que e hortela ::: uma planta de teste\n",
        )
        self._note(
            root / "Tecnologia" / "Vídeos" / "farol.md",
            "---\nfonte: video\n---\n# Farol ficticio\n\ntexto de video que nao sai\n",
        )
        self._note(
            root / "Tecnologia" / "Cursos" / "oficina.md",
            "# Oficina de teste\n\nO que e um teste ::: uma prova curta\n",
        )
        self._note(
            root / "Diario" / "solta.md",
            "---\ntipo: livro\npergunta: isto ::: nao e cartao\n---\n"
            "# Nota solta\n\nparagrafo secreto da nota solta\n",
        )
        self._note(
            root / "Diario" / "extra.md",
            "---\ntype: curso\n---\n# Extra de teste\n\nlinha interna do extra\n",
        )
        self._note(
            root / "Leituras" / "Readwise" / "artigo.md",
            "# Artigo sintetico\n\ndestaque que nao sai\n",
        )
        self._note(
            root / ".obsidian" / "secreta.md",
            "# Segredo\n\ntexto obsidian secreto ::: nao contar\n",
        )
        speech = sources_speech(root)
        self.assertIn("2 em Diario, 1 em Leituras e 3 em Tecnologia", speech)
        self.assertIn("Livros, 2", speech)
        self.assertIn("Vídeos, 1", speech)
        self.assertIn("Cursos, 2", speech)
        self.assertIn("Readwise, 1", speech)
        self.assertIn("Cartões de pergunta e resposta, 2", speech)
        for hidden in (
            "corpo do livro que nao pode sair",
            "texto de video que nao sai",
            "paragrafo secreto da nota solta",
            "linha interna do extra",
            "destaque que nao sai",
            "texto obsidian secreto",
            "nao e cartao",
            "Hortela de teste",
        ):
            self.assertNotIn(hidden, speech)
        self.assertNotIn("\u2014", speech)
        self.assertNotIn(".obsidian", speech)
        routed = run_routine(root, classify("quais fontes tenho?"), NOW)
        self.assertEqual(routed, speech)
        self.assertIn("quais fontes tenho", help_speech(True))
        brain = self._brain()
        brain.vault = LocalVault(root)
        self.assertEqual(brain.ask("quais fontes tenho?"), speech)
        self.assertIn("não está configurado", sources_speech(self.tmp / "vazio"))
        (self.tmp / "vazio").mkdir()
        self.assertIn("Não há nota", sources_speech(self.tmp / "vazio"))

    def test_digest_de_domingo_so_no_telegram_do_usuario(self):
        self.assertFalse(digest_due(SUNDAY.replace(hour=17), {}, (18, 30)))
        self.assertTrue(digest_due(SUNDAY, {}, (18, 30)))
        self.assertFalse(digest_due(SUNDAY, {"digest": "2026-11-01"}, (18, 30)))
        monday = datetime(2026, 11, 2, 19, 0, tzinfo=TZ)
        self.assertFalse(digest_due(monday, {}, (18, 30)))
        self.assertFalse(config.digest_enabled())

        root = self.tmp / "vault"
        note = root / "Estudos" / "Farol.md"
        self._note(
            note,
            "# Farol de teste\n\n## Lampada\n\nO corpo secreto nao pode sair.\n",
        )
        os.environ["JARVIS_DIGEST"] = "on"
        os.environ["JARVIS_CHECKIN"] = "off"
        api = _Api()
        bot = TelegramBot(api, 42, lambda text: text, lambda path: "")
        brain = type("B", (), {})()
        brain.vault = LocalVault(root)
        brain.pending = None
        companion = Companion(brain, speak=lambda text: None, lock=threading.RLock())
        companion._held = True
        companion.bot = bot
        early = companion.tick(SUNDAY.replace(hour=17))
        self.assertIsNone(early)
        self.assertEqual(api.calls, [])
        sent = companion.tick(SUNDAY)
        self.assertIn("Farol de teste", sent)
        self.assertIn("Lampada", sent)
        self.assertNotIn("corpo secreto", sent)
        self.assertNotIn("\u2014", sent)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0][0], "sendMessage")
        self.assertEqual(api.calls[0][1]["chat_id"], 42)
        self.assertIsNone(companion.tick(SUNDAY))
        self.assertEqual(len(api.calls), 1)
        self.assertIsNone(companion.tick(monday))

        class Boom:
            def send_text(self, text):
                raise RuntimeError("rede")

        later = datetime(2026, 11, 15, 19, 0, tzinfo=TZ)
        companion.bot = Boom()
        self.assertIsNone(companion.tick(later))
        companion.bot = bot
        retried = companion.tick(later)
        self.assertIn("Farol de teste", retried)
        self.assertNotIn("corpo secreto", retried)
        self.assertEqual(api.calls[-1][1]["chat_id"], 42)

        os.environ["JARVIS_DIGEST"] = "off"
        quiet = Companion(brain, speak=lambda text: None, lock=threading.RLock())
        quiet._held = True
        quiet.bot = bot
        self.assertIsNone(quiet.tick(datetime(2026, 11, 8, 19, 0, tzinfo=TZ)))
        self.assertEqual(len(api.calls), 2)

    def _note(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class _Api:
    def __init__(self):
        self.calls = []

    def call(self, method, payload, timeout=30):
        self.calls.append((method, dict(payload)))
        return {}


if __name__ == "__main__":
    unittest.main()
