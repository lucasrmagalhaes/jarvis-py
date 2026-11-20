import json
import queue
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 8192
MAX_MESSAGE_CHARS = 2000
MAX_SUBSCRIBERS = 8
SUBSCRIBER_BACKLOG = 200
INBOX_LIMIT = 32
HISTORY_LIMIT = 80
CLOSE = object()
_SERVIDOR = None

CSP = (
    "default-src 'none'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "script-src 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


class PanelBus:
    def __init__(self):
        self.token = secrets.token_urlsafe(24)
        self.inbox = queue.Queue(maxsize=INBOX_LIMIT)
        self.history = []
        self.subscribers = []
        self.lock = threading.Lock()
        self._sequence = 0

    def publish(self, event):
        with self.lock:
            self._sequence += 1
            event = dict(event, id=self._sequence, ts=time.time())
            self.history.append(event)
            del self.history[:-HISTORY_LIMIT]
            subscribers = list(self.subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                self.drop(subscriber)

    def subscribe(self):
        subscriber = queue.Queue(maxsize=SUBSCRIBER_BACKLOG)
        evicted = None
        with self.lock:
            if len(self.subscribers) >= MAX_SUBSCRIBERS:
                evicted = self.subscribers.pop(0)
            self.subscribers.append(subscriber)
            snapshot = list(self.history)
        if evicted is not None:
            self._signal_close(evicted)
        return subscriber, snapshot

    def drop(self, subscriber):
        self.unsubscribe(subscriber)
        self._signal_close(subscriber)

    @staticmethod
    def _signal_close(subscriber):
        try:
            subscriber.put_nowait(CLOSE)
        except queue.Full:
            try:
                subscriber.get_nowait()
                subscriber.put_nowait(CLOSE)
            except (queue.Empty, queue.Full):
                pass

    def unsubscribe(self, subscriber):
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def state(self, value):
        self.publish({"type": "state", "value": value})

    def transcript(self, role, text):
        self.publish({"type": role, "text": text})

    def submit(self, message):
        try:
            self.inbox.put_nowait(message)
            return True
        except queue.Full:
            return False

    def has_message(self):
        return not self.inbox.empty()

    def take_message(self):
        try:
            return self.inbox.get_nowait()
        except queue.Empty:
            return None


class PanelHandler(BaseHTTPRequestHandler):
    bus = None
    protocol_version = "HTTP/1.1"
    timeout = 10

    def log_message(self, fmt, *args):
        pass

    def _authorized(self, token):
        if not isinstance(token, str) or not token.isascii() or not token:
            return False
        return secrets.compare_digest(token, self.bus.token)

    def _valid_host(self):
        host = (self.headers.get("Host") or "").lower()
        return host in {
            f"127.0.0.1:{config.PANEL_PORT}",
            f"localhost:{config.PANEL_PORT}",
            f"[::1]:{config.PANEL_PORT}",
        }

    def _respond(self, status, body=b"", content_type=None, close=True, store=True):
        if close:
            self.close_connection = True
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        if not store:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        if close:
            self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _token_from_query(self, parsed):
        values = parse_qs(parsed.query).get("t") or []
        return values[0] if values else None

    def do_GET(self):
        if not self._valid_host():
            return self._respond(403)
        parsed = urlparse(self.path)
        token = self._token_from_query(parsed)
        if parsed.path in ("/", "/index.html"):
            if not self._authorized(token):
                return self._respond(
                    403,
                    "Acesso negado. Abra o painel pelo link completo com o token "
                    "exibido no terminal do Jarvis.".encode("utf-8"),
                    "text/plain; charset=utf-8",
                )
            self._serve_index()
        elif parsed.path == "/events":
            if not self._authorized(token):
                return self._respond(403)
            self._serve_events()
        else:
            extra = handle_extra(parsed.path, parse_qs(parsed.query), token, self.bus)
            if extra is None:
                return self._respond(404)
            status, body, content_type = extra
            self._respond(status, body, content_type, store=False)

    def do_POST(self):
        if not self._valid_host():
            return self._respond(403)
        if urlparse(self.path).path != "/send":
            return self._respond(404)

        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
            return self._respond(403)

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return self._respond(400)
        if length <= 0:
            return self._respond(400)
        if length > MAX_BODY_BYTES:
            return self._respond(413)

        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            token = data.get("token")
            message = (data.get("message") or "").strip()[:MAX_MESSAGE_CHARS]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError):
            return self._respond(400)

        if not self._authorized(token):
            return self._respond(403)
        if not message:
            return self._respond(400)
        self._respond(204 if self.bus.submit(message) else 503, close=False)

    def _serve_index(self):
        try:
            body = (STATIC_DIR / "index.html").read_bytes()
        except OSError:
            return self._respond(500)
        from .__version__ import __version__
        from .privacidade import garantir_token

        body = preparar_html(body, self.bus.token, garantir_token(), __version__)
        self._respond(200, body, "text/html; charset=utf-8", close=False)

    def _serve_events(self):
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        subscriber, snapshot = self.bus.subscribe()
        try:
            self._emit({"type": "hello", "history": snapshot})
            while True:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if event is CLOSE:
                    break
                self._emit(event)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            self.bus.unsubscribe(subscriber)

    def _emit(self, event):
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        self.wfile.write(b"data: " + payload + b"\n\n")
        self.wfile.flush()


class QuietPanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def preparar_html(body, token, arquivo, versao):
    """Troca os marcadores do painel. A versão só entra se for semver."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    texto = token if isinstance(token, str) and token.isascii() else ""
    nota = arquivo if isinstance(arquivo, str) and arquivo.isascii() else ""
    marca = versao if isinstance(versao, str) and re.fullmatch(r"\d+\.\d+\.\d+", versao) else ""
    body = body.replace(b"__PANEL_TOKEN__", texto.encode("ascii"))
    body = body.replace(b"__PAINEL_ARQUIVO__", nota.encode("ascii"))
    body = body.replace(b"__JARVIS_VERSION__", marca.encode("ascii"))
    return body


def handle_extra(path, query, token, bus):
    if path not in {"/resumo", "/resumo.json", "/relacionadas", "/progresso", "/progresso.json"}:
        return None
    if not isinstance(token, str) or not token.isascii() or not token:
        return _denied()
    if not secrets.compare_digest(token, bus.token):
        return _denied()
    if path == "/relacionadas":
        from .privacidade import token_confere

        values = query.get("p") if isinstance(query, dict) else None
        arquivo = values[0] if values else ""
        if not token_confere(arquivo):
            return _denied()
        return _related_http(query)
    if path in {"/progresso", "/progresso.json"}:
        return _progresso_http(path, bus.token)
    from . import config
    from .resumo import build_resumo, render_resumo

    payload = build_resumo(config.vault_dir())
    if path == "/resumo.json":
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return 200, body, "application/json; charset=utf-8"
    return 200, render_resumo(payload, bus.token).encode("utf-8"), "text/html; charset=utf-8"


def _progresso_http(path, token):
    from .andamento import montar, render_progresso
    from .resumo import current_moment

    root = config.vault_dir()
    payload = montar(root, current_moment(root))
    if path == "/progresso.json":
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return 200, body, "application/json; charset=utf-8"
    return 200, render_progresso(payload, token).encode("utf-8"), "text/html; charset=utf-8"


def _denied():
    return (
        403,
        "Acesso negado. Abra o painel pelo link completo com o token "
        "exibido no terminal do Jarvis.".encode("utf-8"),
        "text/plain; charset=utf-8",
    )


def _related_http(query):
    from . import config
    from .relacionadas import related_notes

    values = query.get("q") if isinstance(query, dict) else None
    text = " ".join(((values or [""])[0] or "").split())[:200]
    if not text:
        return 400, "Informe o tema.".encode("utf-8"), "text/plain; charset=utf-8"
    root = config.vault_dir()
    notes = []
    if root is not None:
        try:
            from .consult import default_embedder

            embedder = default_embedder()
        except Exception:
            embedder = None
        try:
            notes = related_notes(root, text, embedder=embedder, limit=5)
        except Exception:
            notes = []
    from .privacidade import pode_enviar

    clean = []
    for item in notes:
        titulo = item.get("titulo") or ""
        caminho = item.get("caminho") or ""
        if not titulo or not caminho:
            continue
        if root is not None and not pode_enviar(root, caminho, "painel"):
            continue
        clean.append({"titulo": titulo, "caminho": caminho})
    body = json.dumps({"notas": clean}, ensure_ascii=False).encode("utf-8")
    return 200, body, "application/json; charset=utf-8"


def parar():
    global _SERVIDOR
    server = _SERVIDOR
    _SERVIDOR = None
    if server is None:
        return
    try:
        server.shutdown()
    except Exception:
        pass
    try:
        server.server_close()
    except Exception:
        pass


def start(bus):
    global _SERVIDOR
    from .privacidade import garantir_token

    garantir_token()
    handler = type("BoundPanelHandler", (PanelHandler,), {"bus": bus})
    host = config.panel_bind()
    server = QuietPanelServer((host, config.PANEL_PORT), handler)
    _SERVIDOR = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{config.PANEL_PORT}/?t={bus.token}"
    if config.panel_open():
        timer = threading.Timer(0.8, webbrowser.open, args=[url])
        timer.daemon = True
        timer.start()
    return server, url
