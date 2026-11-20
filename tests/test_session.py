import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from jarvis.barge import is_stop_phrase
from jarvis.log import LOG, failure_speech, setup
from jarvis.main import ends_conversation, listen_window
from jarvis.voice import _wait_proc, bind_stop

ENV_KEYS = (
    "JARVIS_VAULT",
    "JARVIS_VAULT_REMOTE",
    "JARVIS_VAULT_SYNC",
    "JARVIS_PROMPT_FILE",
    "JARVIS_WORKSPACE",
    "JARVIS_LOG",
    "JARVIS_ALLOWED_TOOLS",
    "JARVIS_HOME",
)


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        for handler in list(LOG.handlers):
            LOG.removeHandler(handler)
            handler.close()

    def tearDown(self):
        for handler in list(LOG.handlers):
            LOG.removeHandler(handler)
            handler.close()
        bind_stop(None)
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dismiss_skips_claude_and_memory_reaches_followup(self):
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        from jarvis.brain import Brain

        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        self.assertEqual(brain.ask("Valeu, Jarvis"), "À disposição, senhor.")
        self.assertIsNone(brain.vault)
        fresh = Brain()
        bare = fresh._compose("e amanha?", None)
        self.assertIn("Pedido do senhor: e amanha?", bare)
        self.assertIn("WebFetch", bare)
        self.assertIn("Jarvis/Inbox", bare)
        fresh.memory.remember("o que tenho amanha", "Nada marcado, senhor.")
        text = fresh._compose("e amanha?", None)
        self.assertIn("Contexto recente desta sessão", text)
        self.assertIn("o que tenho amanha", text)
        self.assertIn("Nada marcado, senhor.", text)
        self.assertIn("Pedido do senhor: e amanha?", text)
        fresh.pending = {"kind": "week", "relative": "semana.md", "body": "resumo"}
        calls = []

        def answer(message, _session, read_only=False):
            calls.append(message)
            return "Certo, senhor."

        fresh._ask = answer
        fresh.ask("e amanha?")
        self.assertIsNone(fresh.pending)
        self.assertEqual(len(calls), 1)
        self.assertIn("o que tenho amanha", calls[0])

    def test_listen_window_and_stop_phrases(self):
        from jarvis import config

        self.assertIsNone(listen_window(False))
        self.assertEqual(listen_window(True), config.FOLLOWUP_NO_SPEECH_SECONDS)
        self.assertTrue(ends_conversation("valeu, jarvis"))
        self.assertTrue(ends_conversation("Valeu, Jarvis"))
        self.assertFalse(ends_conversation("bom dia"))
        self.assertTrue(is_stop_phrase("para"))
        self.assertTrue(is_stop_phrase("jarvis para"))
        self.assertTrue(is_stop_phrase("Jarvis, para"))
        self.assertTrue(is_stop_phrase("hey jarvis"))
        self.assertTrue(is_stop_phrase("Hey Jarvis"))
        self.assertTrue(is_stop_phrase("Hey Jarvis, para"))
        self.assertFalse(is_stop_phrase("pode continuar com o resumo"))

    def test_failure_speech_maps_known_failures(self):
        self.assertIn(
            "passou do tempo",
            failure_speech("a consulta demorou demais e foi cancelada"),
        )
        self.assertIn(
            "microfone",
            failure_speech("não consegui acessar o microfone; verifique a permissão"),
        )
        self.assertIn(
            "Claude Code",
            failure_speech("não encontrei o executável 'claude' no PATH"),
        )
        self.assertIn(
            "Sem rede",
            failure_speech("Não consegui falar com o GitHub. As notas locais foram mantidas."),
        )
        generic = failure_speech("algo estranho aconteceu")
        self.assertIn("tentar de novo", generic)
        self.assertNotIn("Claude", generic)
        self.assertNotIn("rede", generic)
        vault = failure_speech("A pasta do vault não existe: /tmp/segredo")
        self.assertIn("python -m jarvis.setup", vault)
        self.assertNotIn("/tmp/segredo", vault)
        missing = failure_speech(
            "não há áudio disponível; use o modo texto ou instale as dependências de voz"
        )
        self.assertIn("python -m jarvis.doctor --corrigir", missing)
        self.assertIn("jarvis.chat", missing)
        key = failure_speech("senha de app ausente")
        self.assertIn("python -m jarvis.setup", key)
        self.assertIn("não leio o valor", key)

    def test_log_setup_writes_and_stays_idempotent(self):
        path = self.tmp / "jarvis.log"
        os.environ["JARVIS_LOG"] = str(path)
        setup()
        setup()
        self.assertEqual(len(LOG.handlers), 1)
        LOG.info("linha de teste")
        self.assertIn("linha de teste", path.read_text(encoding="utf-8"))

    def test_wait_proc_stops_when_event_is_set(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        stop = threading.Event()
        bind_stop(stop)
        timer = threading.Timer(0.05, stop.set)
        timer.start()
        try:
            started = time.monotonic()
            result = _wait_proc(proc)
            self.assertEqual(result, "stop")
            self.assertLess(time.monotonic() - started, 5)
            proc.wait(timeout=2)
        finally:
            timer.cancel()
            bind_stop(None)
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
