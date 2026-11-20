"""PWA local da consulta. Só lê o vault e não aceita comando de escrita."""

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .consult import answer, resolve_bind

STATIC_DIR = Path(__file__).resolve().parent / "static" / "consult"
MAX_BODY_BYTES = 8192
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/app.css": "app.css",
    "/sw.js": "sw.js",
    "/manifest.webmanifest": "manifest.webmanifest",
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
}
CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "manifest-src 'self'; "
    "connect-src 'self'; "
    "worker-src 'self'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class Limiter:
    def __init__(self, limit=30, window=60, clock=None):
        self.limit = limit
        self.window = window
        self.clock = clock or time.monotonic
        self.times = []
        self._lock = threading.Lock()

    def allow(self):
        now = self.clock()
        with self._lock:
            self.times = [item for item in self.times if now - item < self.window]
            if len(self.times) >= self.limit:
                return False
            self.times.append(now)
            return True


class App:
    def __init__(self, root, token, host, port, embedder, limiter):
        self.root = Path(root).resolve()
        self.token = token
        self.host = host
        self.port = port
        self.embedder = embedder
        self.limiter = limiter

    def cookie(self):
        parts = [
            "jarvis_consult=" + self.token,
            "HttpOnly",
            "SameSite=Strict",
            "Path=/",
        ]
        if self.host in {"127.0.0.1", "::1"}:
            parts.append("Secure")
        return "; ".join(parts)

    def allowed_hosts(self):
        port = str(self.port)
        hosts = {
            "127.0.0.1:" + port,
            "localhost:" + port,
            "[::1]:" + port,
        }
        if self.host not in {"127.0.0.1", "::1"}:
            hosts.add(self.host + ":" + port)
        return hosts

    def origin_hosts(self):
        names = {"127.0.0.1", "localhost"}
        if self.host == "::1":
            names.add("::1")
        elif self.host not in {"127.0.0.1", "::1"}:
            names.add(self.host)
        return names


class ConsultHandler(BaseHTTPRequestHandler):
    app = None
    protocol_version = "HTTP/1.1"
    timeout = 10

    def log_message(self, fmt, *args):
        pass

    def version_string(self):
        return "Jarvis"

    def do_GET(self):
        if not self._valid_host():
            return self._text(403, "Acesso negado.")
        parsed = urlparse(self.path)
        if parsed.path == "/entrar":
            return self._enter(parsed)
        if parsed.path == "/consultar":
            return self._text(405, "Use POST.")
        if parsed.path in STATIC_FILES:
            return self._static(parsed.path)
        return self._text(404, "Não encontrado.")

    def do_POST(self):
        if not self._valid_host():
            return self._text(403, "Acesso negado.")
        if urlparse(self.path).path != "/consultar":
            return self._text(404, "Não encontrado.")
        if not self._origin_ok() or self.headers.get("X-Jarvis-Consult") != "1":
            return self._text(403, "Acesso negado.")
        if not _same(self._cookie_token(), self.app.token):
            return self._text(
                403,
                "Acesso negado. Abra o link impresso no terminal desta execução.",
            )
        if not self.app.limiter.allow():
            return self._text(429, "Muitas consultas em sequência. Espere um instante.")
        payload = self._json_body()
        if payload is None:
            return None
        query = payload.get("q")
        if not isinstance(query, str) or not query.strip():
            return self._text(400, "Informe a consulta.")
        try:
            result = answer(self.app.root, query.strip(), embedder=self.app.embedder)
        except Exception:
            return self._text(500, "Não foi possível consultar.")
        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
        return self._respond(200, body, "application/json; charset=utf-8")

    def do_PUT(self):
        self._text(405, "Método não permitido.")

    def do_DELETE(self):
        self._text(405, "Método não permitido.")

    def _enter(self, parsed):
        values = parse_qs(parsed.query, keep_blank_values=False).get("t") or []
        token = values[0] if values else ""
        if not _same(token, self.app.token):
            return self._text(
                403,
                "Acesso negado. Abra o link impresso no terminal desta execução.",
            )
        body = _read_static("index.html")
        if body is None:
            return self._text(500, "Página indisponível.")
        return self._respond(
            200,
            body,
            "text/html; charset=utf-8",
            extra={"Set-Cookie": self.app.cookie()},
        )

    def _static(self, path):
        name = STATIC_FILES[path]
        body = _read_static(name)
        if body is None:
            return self._text(404, "Não encontrado.")
        return self._respond(200, body, _content_type(name))

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            self._text(400, "Pedido inválido.")
            return None
        if length <= 0:
            self._text(400, "Pedido inválido.")
            return None
        if length > MAX_BODY_BYTES:
            self._text(413, "Pedido grande demais.")
            return None
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            self._text(400, "Pedido inválido.")
            return None
        if not isinstance(data, dict):
            self._text(400, "Pedido inválido.")
            return None
        return data

    def _valid_host(self):
        host = (self.headers.get("Host") or "").strip().lower()
        return host in self.app.allowed_hosts()

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        hostname = (urlparse(origin).hostname or "").lower()
        return hostname in self.app.origin_hosts()

    def _cookie_token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name == "jarvis_consult":
                return value
        return ""

    def _text(self, status, message):
        self._respond(status, message.encode("utf-8"), "text/plain; charset=utf-8")

    def _respond(self, status, body, content_type, extra=None):
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "microphone=(), camera=(), geolocation=()")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Connection", "close")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)


class ConsultServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


def serve(root, token, host, port, embedder=None, limiter=None):
    checked = resolve_bind(host)
    if checked is None:
        raise OSError("endereço recusado")
    app = App(root, token, checked, port, embedder, limiter or Limiter())
    handler = type("BoundConsultHandler", (ConsultHandler,), {"app": app})
    server = ConsultServer((checked, port), handler)
    app.port = server.server_address[1]
    return server


def _read_static(name):
    root = STATIC_DIR.resolve()
    path = (STATIC_DIR / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _content_type(name):
    if name.endswith(".js"):
        return "text/javascript; charset=utf-8"
    if name.endswith(".css"):
        return "text/css; charset=utf-8"
    if name.endswith(".webmanifest"):
        return "application/manifest+json"
    if name.endswith(".png"):
        return "image/png"
    return "text/html; charset=utf-8"


def _same(left, right):
    left = "" if left is None else str(left)
    right = "" if right is None else str(right)
    if len(left) != len(right):
        return False
    return secrets.compare_digest(left, right)
