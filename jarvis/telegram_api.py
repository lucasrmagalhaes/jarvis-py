"""Cliente mínimo da Bot API. O token não entra em mensagem de erro."""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


class TelegramError(Exception):
    pass


def redact(text, token=""):
    cleaned = str(text or "")
    if token:
        cleaned = cleaned.replace(token, "***")
    return TOKEN_RE.sub("bot***", cleaned)


class Api:
    def __init__(self, token, transport=None):
        self.token = token or ""
        self.transport = transport

    def call(self, method, payload=None, timeout=35):
        body = payload or {}
        if self.transport is not None:
            return self.transport(method, body, timeout)
        return self._http(method, body, timeout)

    def download(self, relative, dest, max_bytes=8_000_000, timeout=30):
        safe = _safe_file_path(relative)
        if self.transport is not None:
            data = self.transport("download", {"file_path": safe}, timeout)
            if not isinstance(data, (bytes, bytearray)):
                raise TelegramError("download sem conteúdo")
            if len(data) > max_bytes:
                raise TelegramError("áudio grande demais")
            Path(dest).write_bytes(data)
            return Path(dest)
        url = f"https://api.telegram.org/file/bot{self.token}/{safe}"
        request = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                chunks = []
                total = 0
                while True:
                    block = response.read(65536)
                    if not block:
                        break
                    total += len(block)
                    if total > max_bytes:
                        raise TelegramError("áudio grande demais")
                    chunks.append(block)
        except TelegramError:
            raise
        except Exception as error:
            raise TelegramError(redact(error, self.token)) from None
        Path(dest).write_bytes(b"".join(chunks))
        return Path(dest)

    def send_audio(self, path, chat_id, timeout=40):
        if self.transport is not None:
            return self.transport(
                "sendAudio",
                {"chat_id": chat_id, "audio": str(path)},
                timeout,
            )
        return self._multipart(path, chat_id, timeout)

    def _http(self, method, payload, timeout):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except Exception as error:
            raise TelegramError(redact(error, self.token)) from None
        return _result(raw, self.token)

    def _multipart(self, path, chat_id, timeout):
        boundary = "----JarvisAudio"
        file_bytes = Path(path).read_bytes()
        filename = Path(path).name.replace('"', "")
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{chat_id}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        body = head + file_bytes + tail
        url = f"https://api.telegram.org/bot{self.token}/sendAudio"
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except Exception as error:
            raise TelegramError(redact(error, self.token)) from None
        return _result(raw, self.token)


def _result(raw, token):
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise TelegramError("resposta inválida do Telegram") from None
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        detail = ""
        if isinstance(parsed, dict):
            detail = parsed.get("description") or ""
        raise TelegramError(redact(detail or "falha no Telegram", token))
    return parsed.get("result")


def _safe_file_path(relative):
    from .paths import windows_drive

    text = str(relative or "").strip().replace("\\", "/")
    if (
        windows_drive(text)
        or not text
        or text.startswith("/")
        or ".." in text.split("/")
        or "://" in text
    ):
        raise TelegramError("caminho de arquivo recusado")
    return text
