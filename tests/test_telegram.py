import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.bridge import InboxService
from jarvis.reminders import ReminderService
from jarvis.telegram import TelegramBot, TelegramRefused, route
from jarvis.telegram_api import Api, TelegramError, redact
from jarvis.vault import SyncResult

TZ = ZoneInfo("America/Sao_Paulo")
TOKEN = "999:TESTETOKEN"
ALLOWED = 42


class FakeApi:
    def __init__(self, updates=None):
        self.calls = []
        self.updates = list(updates or [])
        self.token = TOKEN

    def call(self, method, payload=None, timeout=None):
        payload = dict(payload or {})
        self.calls.append((method, payload))
        if method == "getUpdates":
            offset = int(payload.get("offset") or 0)
            return [item for item in self.updates if int(item["update_id"]) >= offset]
        if method == "getFile":
            file_id = str(payload.get("file_id") or "")
            if file_id.startswith("foto"):
                return {"file_path": "photos/file.jpg"}
            return {"file_path": "voice/file.ogg"}
        if method == "sendMessage":
            return {"message_id": 1}
        return {}

    def download(self, relative, dest, max_bytes=8_000_000, timeout=30):
        self.calls.append(("download", {"file_path": relative}))
        if ".." in str(relative).split("/"):
            raise TelegramError("caminho de arquivo recusado")
        payload = b"\xff\xd8\xff\xd9" if str(relative).endswith(".jpg") else b"ogg"
        Path(dest).write_bytes(payload)
        return Path(dest)

    def send_audio(self, path, chat_id, timeout=40):
        self.calls.append(("sendAudio", {"chat_id": chat_id, "path": str(path)}))
        return {}


def private(user_id, text=None, voice=None, chat_id=None, chat_type="private", photo=None, caption=None):
    message = {
        "chat": {"id": user_id if chat_id is None else chat_id, "type": chat_type},
        "from": {"id": user_id},
    }
    if text is not None:
        message["text"] = text
    if voice is not None:
        message["voice"] = {"file_id": voice}
    if photo is not None:
        message["photo"] = [
            {"file_id": photo, "file_size": 10},
            {"file_id": photo + "-big", "file_size": 2000},
        ]
    if caption is not None:
        message["caption"] = caption
    return {"update_id": 1, "message": message}


class TelegramTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = {}
        chaves = (
            "JARVIS_HOME",
            "JARVIS_STATE",
            "JARVIS_VAULT",
            "JARVIS_REVISAO",
            "JARVIS_REVISAO_LIMITE",
            "JARVIS_REVISAO_NOVOS",
            "JARVIS_PASTAS_PRIVADAS",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ALLOWED_USER_ID",
            "TELEGRAM_CHAT_ID",
            "TELEGRAM_LIMITE",
            "TELEGRAM_VOICE_REPLY",
        )
        for key in chaves:
            self._env[key] = os.environ.get(key)
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_STATE"] = str(self.tmp / "home" / "state.json")
        for key in chaves:
            if key in {"JARVIS_HOME", "JARVIS_STATE"}:
                continue
            os.environ.pop(key, None)

    def tearDown(self):
        import shutil

        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        from jarvis.catalogo import limpar_catalogo
        from jarvis.privacidade import sair_modo_privado

        sair_modo_privado()
        limpar_catalogo()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_route_rejects_anyone_but_the_allowed_private_chat(self):
        self.assertEqual(route(private(7, "oi"), ALLOWED)["action"], "ignore")
        self.assertEqual(route(private(ALLOWED, "oi", chat_type="group"), ALLOWED)["action"], "ignore")
        self.assertEqual(route(private(ALLOWED, "oi", chat_id=7), ALLOWED)["action"], "ignore")
        self.assertEqual(route({"channel_post": {"text": "oi"}}, ALLOWED)["action"], "ignore")
        self.assertEqual(
            route({"edited_message": private(ALLOWED, "oi")["message"]}, ALLOWED)["action"],
            "ignore",
        )
        self.assertEqual(route(private(ALLOWED, "/start"), ALLOWED)["action"], "start")
        self.assertEqual(route(private(ALLOWED, "bom dia"), ALLOWED)["action"], "text")

    def test_bot_never_messages_a_third_party(self):
        api = FakeApi()
        seen = []
        bot = TelegramBot(api, ALLOWED, lambda text: seen.append(text) or "eco", lambda path: "audio")
        bot.handle(private(7, "invasao"))
        bot.handle(private(ALLOWED, "oi grupo", chat_type="supergroup"))
        bot.handle(private(ALLOWED, "oi", chat_id=99))
        bot.handle({"edited_message": private(ALLOWED, "editado")["message"]})
        bot.handle(private(7, voice="segredo"))
        self.assertEqual(api.calls, [])
        self.assertEqual(seen, [])
        bot.handle(private(ALLOWED, "anota que cafe"))
        self.assertEqual(seen, ["anota que cafe"])
        self.assertEqual(api.calls, [("sendMessage", {"chat_id": ALLOWED, "text": "eco"})])

    def test_audio_is_transcribed_and_voice_reply_is_optional(self):
        api = FakeApi()
        heard = []
        bot = TelegramBot(
            api,
            ALLOWED,
            lambda text: heard.append(text) or "Anotei, senhor.",
            lambda path: "anota que comprar cafe",
            voice_reply=False,
        )
        bot.handle(private(ALLOWED, voice="abc"))
        self.assertEqual(heard, ["anota que comprar cafe"])
        methods = [name for name, _payload in api.calls]
        self.assertEqual(methods, ["getFile", "download", "sendMessage"])
        self.assertEqual(api.calls[-1][1]["chat_id"], ALLOWED)
        self.assertNotIn(TOKEN, str(api.calls))

        spoken = self.tmp / "voz.mp3"
        spoken.write_bytes(b"mp3")
        api.calls.clear()
        bot.voice_reply = True
        bot.synthesize = lambda text: spoken
        bot.handle(private(ALLOWED, "repete"))
        audio = [payload for name, payload in api.calls if name == "sendAudio"]
        self.assertEqual(audio, [{"chat_id": ALLOWED, "path": str(spoken)}])
        self.assertTrue(all(payload.get("chat_id") == ALLOWED for name, payload in api.calls if "chat_id" in payload))

    def test_refuses_to_start_without_an_allowed_user(self):
        with self.assertRaises(TelegramRefused):
            TelegramBot(FakeApi(), None, lambda text: "x", lambda path: None)

    def test_postpone_text_uses_the_same_routine_as_voice(self):
        vault = self.tmp / "vault"
        vault.mkdir()
        note = vault / "lembretes.md"
        note.write_text("- [ ] pagar o boleto @ 2026-10-29 09:00\n", encoding="utf-8")
        from jarvis.routines import classify, run_routine

        moment = datetime(2026, 10, 28, 8, 0, tzinfo=TZ)

        def on_text(text):
            return run_routine(vault, classify(text), moment)

        bot = TelegramBot(FakeApi(), ALLOWED, on_text, lambda path: None)
        bot.handle(private(ALLOWED, "adia o lembrete para amanhã às 11"))
        sent = [payload for name, payload in bot.api.calls if name == "sendMessage"][-1]["text"]
        self.assertIn("Adiei", sent)
        self.assertIn("11", sent)
        self.assertNotIn("\u2014", sent)
        self.assertIn("@ 2026-10-29 11:00", note.read_text(encoding="utf-8"))

    def test_poll_advances_offset_and_does_not_replay(self):
        update = private(ALLOWED, "bom dia")
        update["update_id"] = 3
        api = FakeApi([update])
        bot = TelegramBot(api, ALLOWED, lambda text: "Bom dia, senhor.", lambda path: None)
        self.assertEqual(bot.poll_once(), 1)
        self.assertEqual(bot.offset, 4)
        self.assertEqual(bot.poll_once(), 0)
        sends = [payload for name, payload in api.calls if name == "sendMessage"]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["chat_id"], ALLOWED)

    def test_redact_removes_the_token_from_errors(self):
        leaked = f"https://api.telegram.org/bot{TOKEN}/getMe"
        cleaned = redact(leaked, TOKEN)
        self.assertNotIn(TOKEN, cleaned)
        self.assertNotIn("TESTETOKEN", cleaned)

    def test_download_rejects_escape_and_huge_files(self):
        def transport(method, payload, timeout):
            if method == "download":
                return b"x" * 40
            return {}

        api = Api(TOKEN, transport=transport)
        with self.assertRaises(TelegramError):
            api.download("../segredo", self.tmp / "fora")
        with self.assertRaises(TelegramError):
            api.download("voice/a.ogg", self.tmp / "grande", max_bytes=10)
        self.assertFalse((self.tmp / "grande").exists())

    def test_reminder_is_relayed_only_to_the_allowed_user(self):
        note = self.tmp / "notas.md"
        note.write_text("- [ ] buscar o carro @ 2020-01-01 09:00\n", encoding="utf-8")
        api = FakeApi()
        bot = TelegramBot(api, ALLOWED, lambda text: "x", lambda path: None)

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = True
                self.blocked = False

            def resync_snapshot(self):
                return None

            def publish(self, text):
                return SyncResult(True, "pushed", "ok", committed=True, pushed=True)

            def hud_payload(self):
                return {"pending": 0}

        class Bus:
            def transcript(self, role, text):
                return None

            def state(self, value):
                return None

        service = ReminderService(
            Vault(self.tmp),
            speak=None,
            bus=Bus(),
            lock=threading.Lock(),
            also=bot.send_text,
        )
        service.tick(datetime(2026, 10, 28, 12, 0, tzinfo=TZ))
        self.assertEqual(api.calls[0][0], "sendMessage")
        self.assertEqual(api.calls[0][1]["chat_id"], ALLOWED)
        self.assertIn("buscar o carro", api.calls[0][1]["text"])
        self.assertNotIn(TOKEN, str(api.calls))

    def test_inbox_note_is_relayed_only_to_the_allowed_user(self):
        folder = self.tmp / "Jarvis" / "Inbox"
        folder.mkdir(parents=True)
        (folder / "codex.md").write_text(
            "---\nde: Codex\npara: usuario\ndata: 2026-10-28\nstatus: novo\n---\n\nOlha o PR.\n",
            encoding="utf-8",
        )
        api = FakeApi()
        bot = TelegramBot(api, ALLOWED, lambda text: "x", lambda path: None)

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False

            def resync_snapshot(self):
                return None

            def publish(self, text):
                return SyncResult(True, "local", "ok")

            def hud_payload(self):
                return {"pending": 0}

        class Bus:
            def transcript(self, role, text):
                return None

            def state(self, value):
                return None

        service = InboxService(
            Vault(self.tmp),
            speak=None,
            bus=Bus(),
            lock=threading.Lock(),
            also=bot.send_text,
        )
        service.tick()
        service.tick()
        sends = [payload for name, payload in api.calls if name == "sendMessage"]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["chat_id"], ALLOWED)
        self.assertIn("Codex", sends[0]["text"])
        self.assertNotIn("Olha o PR", sends[0]["text"])
        self.assertIn("avisado", (folder / "codex.md").read_text(encoding="utf-8"))

    def test_photo_and_link_become_notes_only_for_the_allowed_user(self):
        from jarvis.capture import save_drop

        vault = self.tmp / "vault"
        vault.mkdir()
        obs = vault / ".obsidian"
        obs.mkdir()
        (obs / "app.json").write_text("{}\n", encoding="utf-8")
        (vault / "AGENTS.md").write_text(
            "inbox de notas: `Caixa/Rapidas`\n",
            encoding="utf-8",
        )
        moment = datetime(2026, 10, 30, 8, 5, tzinfo=TZ)
        heard = []
        api = FakeApi()

        def on_drop(spec):
            return save_drop(vault, spec, moment)

        bot = TelegramBot(
            api,
            ALLOWED,
            lambda text: heard.append(text) or "eco",
            lambda path: "",
            on_drop=on_drop,
        )
        bot.handle(private(7, photo="foto-alheia", caption="Segredo #casa"))
        bot.handle(private(ALLOWED, photo="foto-grupo", caption="Segredo", chat_type="group"))
        self.assertEqual(api.calls, [])
        self.assertFalse((vault / "Caixa").exists())

        bot.handle(private(ALLOWED, photo="foto1", caption="Recibo do aluguel #casa #financeiro"))
        note = vault / "Caixa" / "Rapidas" / "2026-10-30-080500-recibo-do-aluguel.md"
        self.assertTrue(note.is_file())
        body = note.read_text(encoding="utf-8")
        self.assertIn("titulo: Recibo do aluguel", body)
        self.assertIn("  - inbox", body)
        self.assertIn("  - casa", body)
        self.assertIn("  - financeiro", body)
        self.assertNotIn("senhor", body.casefold())
        self.assertIn("![[Caixa/Rapidas/anexos/2026-10-30-080500.jpg]]", body)
        image = vault / "Caixa" / "Rapidas" / "anexos" / "2026-10-30-080500.jpg"
        self.assertEqual(image.read_bytes(), b"\xff\xd8\xff\xd9")
        self.assertEqual((obs / "app.json").read_text(encoding="utf-8"), "{}\n")
        self.assertEqual(list(obs.rglob("*.md")), [])
        sent = [payload["text"] for name, payload in api.calls if name == "sendMessage"]
        self.assertTrue(any("Recibo do aluguel" in text for text in sent))
        self.assertTrue(all(payload.get("chat_id") == ALLOWED for name, payload in api.calls if "chat_id" in payload))

        heard.clear()
        bot.handle(private(ALLOWED, "https://example.com/docs Farol #produto"))
        link = vault / "Caixa" / "Rapidas" / "2026-10-30-080500-farol.md"
        text = link.read_text(encoding="utf-8")
        self.assertIn("https://example.com/docs", text)
        self.assertIn("# Farol", text)
        self.assertIn("  - produto", text)
        self.assertNotIn("senhor", text.casefold())
        self.assertEqual(heard, [])

        bot.handle(private(ALLOWED, "https://example.com/docs o que é isso?"))
        self.assertEqual(heard, ["https://example.com/docs o que é isso?"])

        before = sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*") if path.is_file())
        bot.handle(private(ALLOWED, "https://user:secret@example.com/a"))
        after = sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*") if path.is_file())
        self.assertEqual(before, after)
        blob = "\n".join(payload.get("text", "") for name, payload in api.calls if name == "sendMessage")
        self.assertIn("senha", blob)
        self.assertNotIn("secret", blob)
        self.assertNotIn("secret", "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in vault.rglob("*.md")))

    def test_registry_phrases_stay_on_the_text_path(self):
        from jarvis.comandos import COMANDOS

        for comando in COMANDOS:
            exemplo = comando.exemplos[0]
            decision = route(private(ALLOWED, exemplo), ALLOWED)
            self.assertEqual(decision["action"], "text", comando.nome)
            self.assertEqual(decision["text"], " ".join(exemplo.split())[:4000])

    def test_voice_uses_stt_and_the_registry(self):
        from jarvis.comandos import classificar

        heard = []

        def on_text(text):
            heard.append(classificar(text).kind)
            return "Anotei o pedido, senhor."

        bot = TelegramBot(
            FakeApi(),
            ALLOWED,
            on_text,
            lambda path: "desliga o telegram hoje",
            voice_reply=False,
        )
        bot.handle(private(ALLOWED, voice="nota-de-voz"))
        self.assertEqual(heard, ["remote_off"])
        methods = [name for name, _payload in bot.api.calls]
        self.assertEqual(methods, ["getFile", "download", "sendMessage"])
        self.assertIn("Anotei o pedido", bot.api.calls[-1][1]["text"])

    def test_build_bot_uses_configured_stt_and_voice_setting(self):
        from unittest import mock

        from jarvis.telegram import build_bot, synthesize_speech

        os.environ["TELEGRAM_BOT_TOKEN"] = TOKEN
        os.environ["TELEGRAM_ALLOWED_USER_ID"] = str(ALLOWED)
        os.environ["TELEGRAM_VOICE_REPLY"] = "on"
        with mock.patch("jarvis.transcribe.transcribe_file", return_value="bom dia") as fn:
            bot = build_bot(lambda text: "Bom dia, senhor.")
            self.assertTrue(bot.voice_reply)
            self.assertIs(bot.synthesize, synthesize_speech)
            self.assertEqual(bot.allowed_chat_id, ALLOWED)
            self.assertEqual(bot.transcribe(self.tmp / "a.ogg"), "bom dia")
            fn.assert_called_once()
        os.environ["TELEGRAM_CHAT_ID"] = "abc"
        with self.assertRaises(TelegramRefused):
            build_bot(lambda text: "x")

    def test_only_the_owner_chat_is_accepted_and_the_log_has_no_content(self):
        import io
        import logging

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        logger = logging.getLogger("jarvis")
        nivel = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            bot = TelegramBot(
                FakeApi(),
                ALLOWED,
                lambda text: "eco",
                lambda path: "eco",
                allowed_chat_id=77,
            )
            bot.handle(private(ALLOWED, "NAO-LOGAR-77"))
            bot.handle(private(7, "NAO-LOGAR-77", chat_id=77))
            bot.handle(
                {
                    "update_id": 2,
                    "callback_query": {
                        "id": "cb-alheio",
                        "from": {"id": 7},
                        "data": "NAO-LOGAR-77",
                        "message": {"chat": {"id": 77, "type": "private"}},
                    },
                }
            )
            self.assertEqual(bot.api.calls, [])
            bot.handle(private(ALLOWED, "bom dia", chat_id=77))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(nivel)
        registro = buf.getvalue()
        self.assertIn("nao autorizado", registro)
        self.assertNotIn("NAO-LOGAR-77", registro)
        self.assertEqual(bot.api.calls[-1][1]["chat_id"], 77)
        self.assertEqual(bot.api.calls[-1][1]["text"], "eco")

    def test_rate_limit_and_sair_block_the_remote_until_tomorrow(self):
        os.environ["TELEGRAM_LIMITE"] = "1"
        momento = {"atual": datetime(2026, 11, 11, 9, 0, tzinfo=TZ)}
        relogio = {"t": 80.0}
        seen = []
        bot = TelegramBot(
            FakeApi(),
            ALLOWED,
            lambda text: seen.append(text) or "eco",
            lambda path: None,
            agora=lambda: momento["atual"],
            relogio=lambda: relogio["t"],
        )
        bot.handle(private(ALLOWED, "bom dia"))
        bot.handle(private(ALLOWED, "outra frase"))
        self.assertEqual(seen, ["bom dia"])
        self.assertIn("Devagar", bot.api.calls[-1][1]["text"])
        bot.handle(private(ALLOWED, "/sair"))
        self.assertIn("Remoto desligado", bot.api.calls[-1][1]["text"])
        antes = len(bot.api.calls)
        bot.handle(private(ALLOWED, "bom dia"))
        self.assertEqual(len(bot.api.calls), antes)
        self.assertEqual(seen, ["bom dia"])
        momento["atual"] = datetime(2026, 11, 12, 8, 0, tzinfo=TZ)
        relogio["t"] = 200.0
        bot.handle(private(ALLOWED, "agenda de amanha"))
        self.assertEqual(seen[-1], "agenda de amanha")

    def test_bare_link_waits_for_confirm_and_then_uses_the_registry(self):
        from jarvis.comandos import classificar

        seen = []
        bot = TelegramBot(
            FakeApi(),
            ALLOWED,
            lambda text: seen.append(text) or "Salvei o resumo, senhor.",
            lambda path: None,
        )
        bot.handle(private(ALLOWED, "https://www.youtube.com/watch?v=Abcdefghijk"))
        self.assertEqual(seen, [])
        markup = bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"]
        self.assertEqual(markup[0][0]["text"], "Salvar")
        self.assertIn("vídeo", bot.api.calls[-1][1]["text"])
        salvar = markup[0][0]["callback_data"]
        bot.handle(_callback(ALLOWED, salvar))
        self.assertEqual(seen, ["salva esse vídeo https://www.youtube.com/watch?v=Abcdefghijk"])
        self.assertEqual(classificar(seen[0]).kind, "capture_video")

        bot.handle(private(ALLOWED, "https://exemplo.test/nota"))
        artigo = bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual(artigo[1]["text"], "Agora não")
        bot.handle(_callback(ALLOWED, artigo[1]["callback_data"]))
        self.assertEqual(len(seen), 1)
        self.assertIn("Não salvei", bot.api.calls[-1][1]["text"])

        bot.handle(private(ALLOWED, "https://podcasts.apple.com/br/podcast/episodio/id9"))
        dados = bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        bot.handle(_callback(ALLOWED, dados))
        self.assertEqual(classificar(seen[-1]).kind, "capture_podcast")
        self.assertTrue(seen[-1].startswith("salva esse podcast "))

    def test_review_draft_and_private_buttons_skip_secret_notes(self):
        from jarvis.brain import Brain
        from jarvis.vault import SyncResult

        os.environ["JARVIS_REVISAO"] = str(self.tmp / "home" / "revisao.json")
        os.environ["JARVIS_REVISAO_LIMITE"] = "5"
        os.environ["JARVIS_REVISAO_NOVOS"] = "5"
        os.environ["JARVIS_PASTAS_PRIVADAS"] = "Cofre"
        vault = self.tmp / "vault"
        vault.mkdir()
        obs = vault / ".obsidian"
        obs.mkdir()
        (obs / "app.json").write_text("{}\n", encoding="utf-8")
        (vault / "Estudo").mkdir()
        (vault / "Estudo" / "fita.md").write_text(
            "# Fita\n\nQual a cor da fita sintetica? ::: amarela\n",
            encoding="utf-8",
        )
        (vault / "Estudo" / "sigilo.md").write_text(
            "# Sigilo\n\n#sigiloso\nQual o selo da caixa sintetica? ::: violeta-sintetica\n",
            encoding="utf-8",
        )
        cofre = vault / "Cofre"
        cofre.mkdir()
        (cofre / "porta.md").write_text(
            "# Porta\n\nQual o codigo da porta sintetica? ::: porta-sintetica\n",
            encoding="utf-8",
        )
        (vault / "Estudo" / "rascunho.md").write_text(
            "# Rascunho\n\n[rascunho] Qual a peca sintetica? ::: parafuso\n",
            encoding="utf-8",
        )
        (cofre / "rascunho.md").write_text(
            "# Rascunho oculto\n\n[rascunho] Qual o selo oculto? ::: oculto-sintetico\n",
            encoding="utf-8",
        )

        brain = Brain()

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False

            def prepare(self):
                return SyncResult(True, "ready", "Vault local.")

            def publish(self, text):
                return SyncResult(True, "skipped", "ok")

            def resync_snapshot(self):
                return None

            def agents_for_prompt(self):
                return "Convenções de teste."

            def hud_payload(self):
                return {"pending": 0}

        brain.vault = Vault(vault)
        brain.clock = lambda: datetime(2026, 11, 11, 9, 0, tzinfo=TZ)
        bot = TelegramBot(FakeApi(), ALLOWED, brain.ask, lambda path: None)

        bot.handle(private(ALLOWED, "revisão do dia"))
        texto = bot.api.calls[-1][1]["text"]
        botoes = bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"]
        self.assertIn("fita sintetica", texto)
        self.assertNotIn("violeta-sintetica", texto)
        self.assertNotIn("porta-sintetica", texto)
        self.assertEqual(botoes[0][0]["text"], "Revelar")
        bot.handle(_callback(ALLOWED, botoes[0][0]["callback_data"]))
        revelada = bot.api.calls[-1][1]["text"]
        notas = bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0]
        self.assertIn("amarela", revelada)
        self.assertNotIn("violeta-sintetica", revelada)
        self.assertEqual([item["text"] for item in notas], ["Errei", "Difícil", "Bom", "Fácil"])
        bot.handle(_callback(ALLOWED, notas[2]["callback_data"]))
        self.assertIn("bom", bot.api.calls[-1][1]["text"].casefold())

        bot.handle(private(ALLOWED, "revisa rascunhos"))
        lista = bot.api.calls[-1][1]["text"]
        acoes = bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0]
        self.assertIn("peca sintetica", lista)
        self.assertNotIn("oculto-sintetico", lista)
        self.assertEqual([item["text"] for item in acoes], ["Aceitar", "Descartar"])
        bot.handle(_callback(ALLOWED, acoes[0]["callback_data"]))
        corpo = (vault / "Estudo" / "rascunho.md").read_text(encoding="utf-8")
        self.assertNotIn("[rascunho]", corpo)
        self.assertIn("parafuso", corpo)
        self.assertIn("oculto-sintetico", (cofre / "rascunho.md").read_text(encoding="utf-8"))
        self.assertEqual((obs / "app.json").read_text(encoding="utf-8"), "{}\n")

        bot.handle(private(ALLOWED, "modo privado"))
        privado = bot.api.calls[-1][1]
        self.assertIn("Modo privado", privado["text"])
        self.assertEqual(privado["reply_markup"]["inline_keyboard"][0][0]["text"], "Sair do modo privado")
        antes = len(bot.api.calls)
        bot.handle(private(ALLOWED, "revisão do dia"))
        self.assertEqual(len(bot.api.calls), antes)
        bot.handle(_callback(ALLOWED, privado["reply_markup"]["inline_keyboard"][0][0]["callback_data"]))
        self.assertIn("Saí do modo privado", bot.api.calls[-1][1]["text"])
        self.assertEqual(
            bot.api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["text"],
            "Ativar modo privado",
        )


def _callback(user_id, data, chat_id=None):
    return {
        "update_id": 9,
        "callback_query": {
            "id": "cb-" + str(data)[:12],
            "from": {"id": user_id},
            "data": data,
            "message": {
                "message_id": 3,
                "chat": {"id": user_id if chat_id is None else chat_id, "type": "private"},
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
