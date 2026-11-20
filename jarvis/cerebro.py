"""Cérebros plugáveis. Ollama responde pergunta simples. O Claude continua o padrão."""

import json
import re
import time
import urllib.error
import urllib.request

from . import config

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2"
_COMPLEX = re.compile(
    r"\b("
    r"grav[ae]|edita(?:r)?|altera(?:r)?|cria(?:r)?|apaga(?:r)?|"
    r"escreve(?:r)?|pesquisa(?:r)?|busca na (?:web|internet)|"
    r"na internet|no google|commit(?:ar)?|pull request|codigo|c[oó]digo"
    r")\b",
    re.IGNORECASE,
)


class CerebroError(Exception):
    pass


class Backend:
    name = ""

    def answer(self, system, user, transport=None):
        raise CerebroError("backend sem resposta")


class ClaudeBackend(Backend):
    name = "claude"


class OllamaBackend(Backend):
    name = "ollama"

    def answer(self, system, user, transport=None):
        return complete(system, user, transport=transport)


_REGISTRY = {"ollama": OllamaBackend}


def register_backend(name, factory):
    if name != "ollama":
        raise CerebroError("backend desconhecido")
    if not callable(factory):
        raise CerebroError("backend desconhecido")
    _REGISTRY[name] = factory


def reset_backends():
    _REGISTRY["ollama"] = OllamaBackend


def cerebro_name():
    raw = config.cerebro_raw()
    if raw in {"", "claude", "claude-code"}:
        return "claude"
    if raw == "ollama":
        return "ollama"
    return "claude"


def pergunta_simples(message):
    text = " ".join((message or "").split())
    if not text or len(text) > 240:
        return False
    if "```" in text or "http://" in text or "https://" in text:
        return False
    if _COMPLEX.search(text):
        return False
    return True


def choose_backend(message):
    if cerebro_name() == "ollama" and pergunta_simples(message):
        factory = _REGISTRY.get("ollama") or OllamaBackend
        return factory()
    return ClaudeBackend()


def ollama_base():
    return _valid_base(config.ollama_url())


def ollama_model():
    return config.ollama_model()


def report_status(transport=None):
    raw = config.cerebro_raw()
    if cerebro_name() != "ollama":
        if raw and raw not in {"claude", "claude-code"}:
            return "warn", "JARVIS_CEREBRO não reconhecido, uso o Claude Code", ""
        return "ok", "Claude Code", ""
    base = ollama_base()
    model = ollama_model()
    if not base:
        return (
            "warn",
            "URL do Ollama inválida. Perguntas simples caem no Claude ou na busca do vault.",
            "defina JARVIS_OLLAMA_URL com http://127.0.0.1:11434",
        )
    try:
        present = model_ready(base, model, config.ollama_timeout(), transport)
    except CerebroError:
        return (
            "warn",
            "Ollama inacessível. Perguntas simples caem no Claude ou na busca do vault.",
            "confira se o Ollama está no ar e o JARVIS_OLLAMA_URL",
        )
    if present:
        return "ok", f"Ollama, modelo {model}", ""
    return (
        "warn",
        f"Ollama no ar, sem o modelo {model}.",
        "baixe esse modelo no Ollama ou troque JARVIS_OLLAMA_MODEL",
    )


def model_ready(base, model, timeout, transport=None):
    call = transport or default_transport
    body = call("GET", base + "/api/tags", None, timeout)
    if not isinstance(body, dict):
        raise CerebroError("ollama invalido")
    names = []
    for item in body.get("models") or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    wanted = model.split(":", 1)[0]
    return any(name == model or name.split(":", 1)[0] == wanted for name in names)


def stream_lines(system, user, transport=None):
    """Linhas NDJSON do Ollama com stream ligado. O teste injeta transport."""
    if transport is not None:
        return transport(system, user)
    base = ollama_base()
    if not base:
        raise CerebroError("ollama indisponivel")
    payload = {
        "model": ollama_model(),
        "stream": True,
        "messages": [
            {"role": "system", "content": system or ""},
            {"role": "user", "content": user or ""},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/chat",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/x-ndjson"},
        method="POST",
    )
    prazo = config.ollama_timeout()
    try:
        response = urllib.request.urlopen(request, timeout=prazo)
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise CerebroError("ollama indisponivel") from error
    return _com_prazo(response, prazo)


def complete(system, user, transport=None):
    base = ollama_base()
    if not base:
        raise CerebroError("ollama indisponivel")
    call = transport or default_transport
    payload = {
        "model": ollama_model(),
        "stream": False,
        "messages": [
            {"role": "system", "content": system or ""},
            {"role": "user", "content": user or ""},
        ],
    }
    body = call("POST", base + "/api/chat", payload, config.ollama_timeout())
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        raise CerebroError("ollama vazio")
    cleaned = text.replace("\u2014", ", ").replace("\u2013", ", ")
    return " ".join(cleaned.split())


def default_transport(method, url, payload, timeout):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _ler_corpo(response, timeout, 1_000_000)
    except CerebroError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        raise CerebroError("ollama indisponivel") from error
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CerebroError("ollama invalido") from error
    if not isinstance(body, dict):
        raise CerebroError("ollama invalido")
    return body


def _ler_corpo(response, timeout, teto):
    """Lê no máximo `teto` bytes e não passa do prazo total.

    Um soquete que recebe um byte de vez em quando não reinicia o prazo.
    """
    limite = time.monotonic() + max(0.1, float(timeout or 0.1))
    pedacos = []
    lido = 0
    while lido < teto:
        if time.monotonic() >= limite:
            raise CerebroError("ollama demorou demais")
        falta = limite - time.monotonic()
        _ajustar_socket(response, min(falta, 0.25))
        try:
            # Um byte por vez. read(n) grande espera encher o bloco e a goteira
            # renovaria o prazo do soquete até o fim do corpo.
            bloco = response.read(1)
        except TimeoutError:
            continue
        if not bloco:
            break
        pedacos.append(bloco)
        lido += len(bloco)
    if time.monotonic() >= limite and not pedacos:
        raise CerebroError("ollama demorou demais")
    return b"".join(pedacos)


def _ajustar_socket(response, segundos):
    sock = None
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None) if fp is not None else None
    if raw is not None:
        sock = getattr(raw, "_sock", None)
    if sock is None:
        return
    try:
        sock.settimeout(max(0.05, float(segundos)))
    except OSError:
        pass


def _com_prazo(response, timeout):
    limite = time.monotonic() + max(0.1, float(timeout))
    try:
        for raw in response:
            if time.monotonic() > limite:
                raise CerebroError("ollama demorou demais")
            yield raw.decode("utf-8", errors="replace")
    finally:
        try:
            response.close()
        except Exception:
            pass


def _valid_base(raw):
    text = (raw or "").strip().rstrip("/")
    if not text.lower().startswith(("http://", "https://")):
        return ""
    if " " in text or "\n" in text or "@" in text:
        return ""
    rest = text.split("://", 1)[1]
    host = rest.split("/", 1)[0]
    if not host or host.startswith("."):
        return ""
    return text
