"""Foto ou link do Telegram viram nota na inbox de notas do vault."""

import re
from pathlib import Path
from urllib.parse import urlparse

from .guardas import FALA_BLOQUEIO, GuardError, caminho_bloqueado, escrever
from .routines import _inside, fold, load_places

MAX_IMAGE = 8_000_000
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_TAG_RE = re.compile(r"#([\wÀ-ÿ-]{1,40})", re.UNICODE)
_LINK_RE = re.compile(r"(?i)^(https?://\S+)(?:\s+(.*))?$")
_REST_SKIP = re.compile(
    r"(?i)^(o que|me |anota|como |quais |bom dia|pede |liga |abre )"
)


def parse_link_capture(message):
    text = " ".join((message or "").split())
    match = _LINK_RE.match(text)
    if not match:
        return None
    url = match.group(1)
    rest = (match.group(2) or "").strip()
    if len(url) > 500:
        return None
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return {"blocked": True}
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if "?" in rest or len(rest) > 120 or _REST_SKIP.match(rest):
        return None
    title, tags = split_title_tags(rest)
    return {"blocked": False, "url": url, "title": title, "tags": tags}


def split_title_tags(text):
    raw = " ".join((text or "").split())
    tags = []

    def take(match):
        tag = _tag(match.group(1))
        if tag and tag not in tags:
            tags.append(tag)
        return " "

    title = _TAG_RE.sub(take, raw)
    return _clean_title(title), tags[:8]


def drop_pedido(spec):
    title = _clean_title((spec or {}).get("title") or "")
    if (spec or {}).get("kind") == "photo":
        return ("foto: " + title) if title else "foto"
    url = " ".join(str((spec or {}).get("url") or "").split())
    if title:
        return (url + " " + title)[:300]
    return url[:300]


def save_drop(root, spec, moment, read_only=False):
    spec = spec or {}
    if read_only:
        return "Não gravei a nota, senhor. O vault está bloqueado para escrita agora."
    root = Path(root)
    places = load_places(root)
    folder = _notes_dir(root, places)
    if folder is None:
        return "Não gravei a nota, senhor. O destino ficou fora do vault."
    kind = spec.get("kind")
    title = _clean_title(spec.get("title") or "")
    tags = _note_tags(spec.get("tags") or [])
    if kind == "link":
        url = " ".join(str(spec.get("url") or "").split())
        parsed = urlparse(url)
        if (
            not url
            or parsed.username
            or parsed.password
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
        ):
            return "Não gravei o link, senhor."
        if not title:
            title = _clean_title(_host_title(parsed))
        body = url
    elif kind == "photo":
        error, copied = _store_image(root, folder, spec, moment)
        if error:
            return error
        if not title:
            title = f"Foto {moment.strftime('%Y-%m-%d %H:%M')}"
        body = f"![[{copied}]]"
    else:
        return "Não gravei a nota, senhor."
    try:
        relative = _write_note(root, folder, title, tags, body, moment)
    except GuardError:
        return FALA_BLOQUEIO
    if relative is None:
        return "Não gravei a nota, senhor. O destino ficou fora do vault."
    from .journal import record

    record(drop_pedido({"kind": kind, "title": title, "url": spec.get("url") or ""}), moment)
    return f"Guardei na inbox de notas, senhor: {title}. O caminho é {relative}."


def _store_image(root, folder, spec, moment):
    source = spec.get("path")
    if not source:
        return "Não gravei a foto, senhor.", ""
    source = Path(source)
    try:
        data = source.read_bytes()
    except OSError:
        return "Não gravei a foto, senhor.", ""
    if not data:
        return "Não gravei a foto, senhor. A foto veio vazia.", ""
    if len(data) > MAX_IMAGE:
        return "Não gravei a foto, senhor. O arquivo é grande demais.", ""
    suffix = str(spec.get("suffix") or source.suffix or "").lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".jpg"
    name = moment.strftime("%Y-%m-%d-%H%M%S") + suffix
    dest_dir = folder / "anexos"
    dest = dest_dir / name
    if not _safe_note(root, dest) or caminho_bloqueado(dest):
        return "Não gravei a foto, senhor. O destino ficou fora do vault.", ""
    dest_dir.mkdir(parents=True, exist_ok=True)
    from .trava import fila_escrita, gravar_atomico

    with fila_escrita():
        gravar_atomico(dest, data)
    relative = _relative(root, dest)
    if not relative or "[" in relative or "]" in relative:
        try:
            dest.unlink()
        except OSError:
            pass
        return "Não gravei a foto, senhor. O destino ficou fora do vault.", ""
    return "", relative


def _write_note(root, folder, title, tags, body, moment):
    slug = _slug(title) or "nota"
    stamp = moment.strftime("%Y-%m-%d-%H%M%S")
    path = folder / f"{stamp}-{slug}.md"
    suffix = 2
    while path.exists():
        path = folder / f"{stamp}-{slug}-{suffix}.md"
        suffix += 1
    if not _safe_note(root, path) or caminho_bloqueado(path):
        return None
    rendered = _render(title, tags, body, moment)
    path.parent.mkdir(parents=True, exist_ok=True)
    escrever(path, rendered, checar=rendered, raiz=root)
    return _relative(root, path)


def _render(title, tags, body, moment):
    lines = ["---", "tags:"]
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append(f"titulo: {_yaml(title)}")
    lines.append("fonte: telegram")
    lines.append(f"data: {moment.strftime('%Y-%m-%d')}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    return "\n".join(lines)


def _notes_dir(root, places):
    root = Path(root)
    if places.notes:
        folder = root / places.notes
        if folder.suffix.lower() == ".md":
            folder = folder.parent
    else:
        folder = root / "Jarvis" / "Notas"
    if not _safe_note(root, folder):
        return None
    return folder


def _safe_note(root, path):
    if not _inside(path, root):
        return False
    try:
        relative = Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    parts = relative.parts
    if not parts:
        return False
    if any(part.startswith(".") or part == ".obsidian" for part in parts):
        return False
    return True


def _relative(root, path):
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return ""


def _note_tags(extra):
    found = ["inbox"]
    for tag in extra or []:
        cleaned = _tag(tag)
        if cleaned and cleaned not in found:
            found.append(cleaned)
    return found[:8]


def _tag(raw):
    cleaned = re.sub(r"[^a-z0-9_-]", "", fold(raw or ""))
    return cleaned[:24]


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", fold(text or "")).strip("-")
    return slug[:40]


def _clean_title(text):
    cleaned = " ".join(
        str(text or "").replace("\u2014", " ").replace("\u2013", " ").split()
    )
    return cleaned[:80]


def _host_title(parsed):
    host = (parsed.netloc or "").removeprefix("www.")
    return host or "Link"


def _yaml(value):
    text = _clean_title(value)
    if not text:
        return '""'
    special = set(':{}[]&*!|>%@`"\'#,')
    if (
        any(char in special for char in text)
        or text[:1] in "-? "
        or text.casefold() in {"yes", "no", "true", "false", "null"}
    ):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + escaped + '"'
    return text
