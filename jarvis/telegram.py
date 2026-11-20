"""Bot do Telegram. Só fala com o dono, na conversa autorizada."""

import tempfile
import threading
from pathlib import Path

from . import config
from .log import LOG
from .state import update
from .telegram_api import Api, TelegramError, redact

START_TEXT = "Sistemas online. Às suas ordens, senhor."
EMPTY_TEXT = "Concluí a tarefa, senhor, mas não há nada a reportar."
AUDIO_FAIL = "Não consegui ouvir o áudio, senhor."
AUDIO_EMPTY = "Não entendi o áudio, senhor."


class TelegramRefused(Exception):
    pass


def route(update, allowed_user_id, allowed_chat_id=None):
    if not isinstance(update, dict):
        return _ignore("sem mensagem")
    consulta = update.get("callback_query")
    if isinstance(consulta, dict):
        message = consulta.get("message") if isinstance(consulta.get("message"), dict) else None
        if message is None:
            return _ignore("sem mensagem")
        usuario = consulta.get("from")
    elif isinstance(update.get("message"), dict):
        message = update.get("message")
        usuario = message.get("from")
        consulta = None
    else:
        return _ignore("sem mensagem")
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    if chat.get("type") != "private":
        return _ignore("nao privado")
    user = usuario if isinstance(usuario, dict) else {}
    try:
        user_id = int(user.get("id"))
        chat_id = int(chat.get("id"))
        permitido = int(allowed_user_id)
        conversa = int(permitido if allowed_chat_id is None else allowed_chat_id)
    except (TypeError, ValueError):
        return _ignore("nao autorizado")
    if permitido <= 0 or conversa <= 0 or user_id != permitido or chat_id != conversa:
        return _ignore("nao autorizado")
    if consulta is not None:
        return {
            "action": "callback",
            "data": str(consulta.get("data") or "")[:64],
            "callback_id": str(consulta.get("id") or "")[:80],
        }
    text = message.get("text")
    if isinstance(text, str) and text.strip():
        cleaned = " ".join(text.split())
        command = cleaned.split()[0].split("@", 1)[0].lower()
        if command == "/start":
            return {"action": "start"}
        if command in {"/ajuda", "/help"}:
            return {"action": "help"}
        if command == "/sair":
            return {"action": "sair"}
    else:
        cleaned = ""
    photo = _largest_photo(message.get("photo"))
    if photo:
        from .capture import split_title_tags

        caption = message.get("caption") if isinstance(message.get("caption"), str) else ""
        title, tags = split_title_tags(caption)
        return {
            "action": "photo",
            "file_id": photo,
            "title": title,
            "tags": tags,
        }
    if cleaned:
        from .capture import parse_link_capture

        parsed = parse_link_capture(cleaned[:4000])
        if parsed:
            if parsed.get("blocked"):
                return {"action": "link", "blocked": True}
            if not (parsed.get("title") or parsed.get("tags")):
                return {"action": "confirm_link", "url": parsed.get("url") or ""}
            return {
                "action": "link",
                "url": parsed.get("url") or "",
                "title": parsed.get("title") or "",
                "tags": parsed.get("tags") or [],
            }
        return {"action": "text", "text": cleaned[:4000]}
    voice = message.get("voice") or message.get("audio")
    if isinstance(voice, dict) and voice.get("file_id"):
        return {"action": "audio", "file_id": str(voice.get("file_id"))[:200]}
    return _ignore("sem texto")


def _ignore(reason):
    return {"action": "ignore", "reason": reason}


def _largest_photo(photos):
    if not isinstance(photos, list):
        return ""
    best = ""
    best_size = -1
    for item in photos:
        if not isinstance(item, dict) or not item.get("file_id"):
            continue
        try:
            size = int(item.get("file_size") or 0)
        except (TypeError, ValueError):
            size = 0
        if size >= best_size:
            best_size = size
            best = str(item.get("file_id"))[:200]
    return best


def _linhas_botoes(linhas):
    teclado = []
    for linha in linhas or []:
        fila = []
        for rotulo, dado in linha:
            fila.append({"text": str(rotulo)[:40], "callback_data": str(dado)[:64]})
        if fila:
            teclado.append(fila)
    return teclado


class TelegramBot:
    def __init__(
        self,
        api,
        allowed_user_id,
        on_text,
        transcribe,
        synthesize=None,
        voice_reply=False,
        on_drop=None,
        allowed_chat_id=None,
        agora=None,
        relogio=None,
    ):
        if allowed_user_id is None:
            raise TelegramRefused("Telegram sem usuário autorizado. Não vou conectar.")
        self.api = api
        self.allowed_user_id = int(allowed_user_id)
        if allowed_chat_id is None:
            self.allowed_chat_id = self.allowed_user_id
        else:
            self.allowed_chat_id = int(allowed_chat_id)
        if self.allowed_chat_id <= 0 or self.allowed_user_id <= 0:
            raise TelegramRefused("Telegram sem conversa autorizada. Não vou conectar.")
        self.on_text = on_text
        self.transcribe = transcribe
        self.synthesize = synthesize
        self.voice_reply = bool(voice_reply)
        self.on_drop = on_drop
        from .remoto import Limitador, agora_local

        self.agora = agora or agora_local
        self.limitador = Limitador(relogio)
        self._capturas = {}
        self.offset = _load_offset()

    def send_text(self, text, botoes=None, mesmo_privado=False):
        from .privacidade import modo_privado_ativo, texto_para_telegram

        if modo_privado_ativo() and not mesmo_privado:
            return False
        if mesmo_privado:
            cleaned = " ".join((text or "").split())
        else:
            cleaned = texto_para_telegram(text)
            cleaned = " ".join((cleaned or "").split())
        if not cleaned:
            return False
        if len(cleaned) > 4000:
            cleaned = cleaned[:3997].rstrip() + "..."
        payload = {"chat_id": self.allowed_chat_id, "text": cleaned}
        if botoes and not cleaned.startswith("Há conteúdo sigiloso"):
            payload["reply_markup"] = {"inline_keyboard": _linhas_botoes(botoes)}
        self.api.call("sendMessage", payload)
        return True

    def handle(self, update):
        decision = route(update, self.allowed_user_id, self.allowed_chat_id)
        if decision["action"] == "ignore":
            LOG.info("telegram ignorado: %s", decision.get("reason"))
            return decision
        if not self._remoto_ligado():
            LOG.info("telegram ignorado: remoto desligado")
            self._ack(decision)
            return decision
        if self._bloqueio_privado(decision):
            LOG.info("telegram ignorado: modo privado")
            self._ack(decision)
            return decision
        if decision["action"] == "sair":
            from .remoto import FALA_SAIR, desligar_hoje

            self._ack(decision)
            self.send_text(FALA_SAIR)
            desligar_hoje(self.agora())
            return decision
        if not self.limitador.permite(config.telegram_limite()):
            LOG.info("telegram ignorado: limite")
            self._avisar_limite(decision)
            return decision
        if decision["action"] == "start":
            self.send_text(START_TEXT)
            return decision
        if decision["action"] == "help":
            from .chat import HELP

            self.send_text(HELP)
            return decision
        if decision["action"] == "text":
            self._reply(self._em_telegram(decision["text"]), decision["text"])
            return decision
        if decision["action"] == "confirm_link":
            self._confirmar_link(decision.get("url") or "")
            return decision
        if decision["action"] == "link":
            self._link(decision)
            return decision
        if decision["action"] == "photo":
            self._photo(decision)
            return decision
        if decision["action"] == "audio":
            self._audio(decision["file_id"])
            return decision
        if decision["action"] == "callback":
            self._callback(decision)
            return decision
        return decision

    def poll_once(self):
        updates = self.api.call(
            "getUpdates",
            {"offset": self.offset, "timeout": 0},
            timeout=40,
        )
        if not isinstance(updates, list):
            return 0
        count = 0
        for item in updates:
            if not isinstance(item, dict):
                continue
            try:
                update_id = int(item.get("update_id"))
            except (TypeError, ValueError):
                continue
            try:
                self.handle(item)
            except Exception as error:
                LOG.error("telegram: %s", redact(error, getattr(self.api, "token", "")))
            self.offset = update_id + 1
            count += 1
        if count:
            _store_offset(self.offset)
        return count

    def _remoto_ligado(self):
        from .remoto import remoto_ligado

        try:
            return remoto_ligado(self.agora())
        except Exception:
            return False

    def _bloqueio_privado(self, decision):
        from .privacidade import modo_privado_ativo

        if not modo_privado_ativo():
            return False
        acao = decision.get("action")
        if acao == "text":
            from .comandos import classificar

            try:
                return classificar(decision.get("text") or "").kind != "private_off"
            except Exception:
                return True
        if acao == "callback":
            return (decision.get("data") or "") != "prv:off"
        return True

    def _ack(self, decision, texto=""):
        if decision.get("action") != "callback":
            return
        cid = decision.get("callback_id") or ""
        if not cid:
            return
        payload = {"callback_query_id": cid}
        aviso = " ".join(str(texto or "").split())
        if aviso:
            payload["text"] = aviso[:180]
        try:
            self.api.call("answerCallbackQuery", payload)
        except Exception as error:
            LOG.error("telegram: %s", redact(error, getattr(self.api, "token", "")))

    def _avisar_limite(self, decision):
        from .remoto import LIMITE_TEXTO

        if decision.get("action") == "callback":
            self._ack(decision, LIMITE_TEXTO)
            return
        self.send_text(LIMITE_TEXTO)

    def _em_telegram(self, text):
        from .privacidade import definir_destino, restaurar_destino

        token = definir_destino("telegram")
        try:
            return self.on_text(text)
        finally:
            restaurar_destino(token)

    def _reply(self, reply, entrada=""):
        from .comandos import classificar
        from .privacidade import modo_privado_ativo, texto_para_telegram

        try:
            privacidade = classificar(entrada or "").kind in {"private_on", "private_off"}
        except Exception:
            privacidade = False
        if modo_privado_ativo() and not privacidade:
            return
        text = " ".join((reply or "").split()) or EMPTY_TEXT
        botoes = None
        if entrada:
            try:
                from .remoto import teclado_da_resposta

                botoes = teclado_da_resposta(entrada)
            except Exception:
                botoes = None
        self.send_text(text, botoes, mesmo_privado=privacidade)
        if modo_privado_ativo() or not self.voice_reply or self.synthesize is None:
            return
        falado = " ".join((texto_para_telegram(text) or "").split())
        if not falado or falado.startswith("Há conteúdo sigiloso"):
            return
        try:
            path = self.synthesize(falado)
        except Exception as error:
            LOG.error("audio da resposta: %s", redact(error, getattr(self.api, "token", "")))
            return
        if not path:
            return
        try:
            self.api.send_audio(path, self.allowed_chat_id)
        except Exception as error:
            LOG.error("envio de audio: %s", redact(error, getattr(self.api, "token", "")))

    def _audio(self, file_id):
        directory = None
        try:
            directory = tempfile.mkdtemp(prefix="jarvis-audio-")
            info = self.api.call("getFile", {"file_id": file_id})
            relative = info.get("file_path") if isinstance(info, dict) else ""
            dest = Path(directory) / "audio"
            self.api.download(relative, dest)
            heard = self.transcribe(dest)
        except Exception as error:
            LOG.error("audio recebido: %s", redact(error, getattr(self.api, "token", "")))
            self.send_text(AUDIO_FAIL)
            return
        finally:
            if directory:
                _cleanup(directory)
        if not heard:
            self.send_text(AUDIO_EMPTY)
            return
        self._reply(self._em_telegram(heard), heard)

    def _confirmar_link(self, url):
        from .remoto import preparar_captura

        texto, linhas, token, frase = preparar_captura(url)
        if not frase:
            self.send_text("Não gravei o link, senhor.")
            return
        self._capturas[token] = frase
        while len(self._capturas) > 20:
            self._capturas.pop(next(iter(self._capturas)))
        self.send_text(texto, linhas)

    def _callback(self, decision):
        from .remoto import frase_do_botao

        self._ack(decision)
        frase = frase_do_botao(decision.get("data") or "", self._capturas)
        if frase == "cancelar-captura":
            self.send_text("Não salvei, senhor.")
            return
        if not frase:
            self.send_text("Não entendi o botão, senhor.")
            return
        self._reply(self._em_telegram(frase), frase)

    def _link(self, decision):
        if decision.get("blocked"):
            self.send_text("Não gravei o link, senhor. Ele traz usuário ou senha.")
            return
        if self.on_drop is None:
            self.send_text("Não gravei o link, senhor.")
            return
        spec = {
            "kind": "link",
            "url": decision.get("url") or "",
            "title": decision.get("title") or "",
            "tags": decision.get("tags") or [],
        }
        self._deliver_drop(spec)

    def _photo(self, decision):
        directory = tempfile.mkdtemp(prefix="jarvis-foto-")
        try:
            try:
                info = self.api.call("getFile", {"file_id": decision["file_id"]})
                relative = info.get("file_path") if isinstance(info, dict) else ""
                suffix = Path(str(relative)).suffix.lower()
                if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                    suffix = ".jpg"
                dest = Path(directory) / f"foto{suffix}"
                self.api.download(relative, dest)
            except Exception as error:
                LOG.error("foto recebida: %s", redact(error, getattr(self.api, "token", "")))
                self.send_text("Não consegui baixar a foto, senhor.")
                return
            if self.on_drop is None:
                self.send_text("Não gravei a foto, senhor.")
                return
            self._deliver_drop(
                {
                    "kind": "photo",
                    "path": dest,
                    "suffix": suffix,
                    "title": decision.get("title") or "",
                    "tags": decision.get("tags") or [],
                }
            )
        finally:
            _cleanup(directory)

    def _deliver_drop(self, spec):
        try:
            reply = self.on_drop(spec)
        except Exception as error:
            LOG.error("captura: %s", redact(error, getattr(self.api, "token", "")))
            self.send_text("Não gravei a nota, senhor.")
            return
        self._reply(reply)


def _load_offset():
    from .state import load

    try:
        return int(load().get("telegram_offset") or 0)
    except (TypeError, ValueError):
        return 0


def _store_offset(offset):
    def mutate(data):
        data["telegram_offset"] = int(offset)

    update(mutate)


def _cleanup(directory):
    path = Path(directory)
    for child in path.glob("*"):
        try:
            child.unlink()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass


def synthesize_speech(text):
    import asyncio

    import edge_tts

    from .voice import clean

    spoken = clean(text)
    if not spoken:
        return None
    dest = Path(tempfile.mkdtemp(prefix="jarvis-voz-")) / "resposta.mp3"

    async def synth():
        communicate = edge_tts.Communicate(
            spoken,
            config.EDGE_VOICE,
            rate=config.EDGE_RATE,
        )
        await communicate.save(str(dest))

    asyncio.run(asyncio.wait_for(synth(), timeout=config.EDGE_TIMEOUT))
    if dest.is_file() and dest.stat().st_size:
        return dest
    return None


class TelegramService:
    def __init__(self, bot, interval=2):
        self.bot = bot
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="jarvis-telegram", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.bot.poll_once()
            except TelegramError as error:
                LOG.error("telegram: %s", redact(error, getattr(self.bot.api, "token", "")))
            except Exception as error:
                LOG.error("telegram: %s", redact(error, getattr(self.bot.api, "token", "")))
            self._stop.wait(self.interval)


def build_bot(on_text, transcribe=None, on_drop=None):
    if not config.telegram_ready():
        raise TelegramRefused(
            "Telegram sem token, sem usuário ou sem conversa autorizada. Não vou conectar."
        )
    voice = config.telegram_voice_reply()
    return TelegramBot(
        Api(config.telegram_token()),
        config.telegram_allowed_user_id(),
        on_text,
        transcribe or _transcribe,
        synthesize=synthesize_speech if voice else None,
        voice_reply=voice,
        on_drop=on_drop,
        allowed_chat_id=config.telegram_chat_id(),
    )


def _transcribe(path):
    from .transcribe import transcribe_file

    return transcribe_file(path)


def run():
    import sys

    from .companion import run_background

    sys.exit(run_background())


if __name__ == "__main__":
    run()
