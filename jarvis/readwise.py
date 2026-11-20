"""Importa destaques do Readwise para o clone local do vault.

O token fica em READWISE_TOKEN. Ele não entra no log, no cursor nem na nota.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .log import LOG

EXPORT_URL = "https://readwise.io/api/v2/export/"
DEFAULT_FOLDER = "Leituras/Readwise"
STATE_NAME = "readwise.json"
MAX_PAGES = 20

FALTA_TOKEN = (
    "Falta o token do Readwise, senhor. "
    "Defina READWISE_TOKEN no arquivo de ambiente. "
    "Eu não leio o valor em voz alta."
)
TOKEN_RECUSADO = (
    "O token do Readwise foi recusado, senhor. "
    "Confira READWISE_TOKEN. Eu não leio o valor em voz alta."
)
FALHA = "Não consegui buscar os destaques, senhor. Confira a rede e tente de novo."
FALTA_VAULT = (
    "O vault não está configurado, senhor. "
    "Sem ele eu não gravo os destaques. "
    "Rode python -m jarvis.setup."
)
BLOQUEADO_VAULT = "Não importei, senhor. O vault está bloqueado para escrita agora."
PASTA_FORA = "Não importei, senhor. A pasta dos destaques ficou fora do vault."
PASTA_OBSIDIAN = "Não importei, senhor. A pasta .obsidian está bloqueada."
NADA_NOVO = "Não há destaque novo, senhor."
ESCRITA_BLOQUEADA = "Não importei, senhor. A escrita foi bloqueada."

_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CURSOR_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_BLOCK_RE = re.compile(r"(?s)<!-- rw:(\d+) -->\n(.*?)<!-- /rw -->")


class ReadwiseError(Exception):
    def __init__(self, speech):
        self.speech = speech
        super().__init__(speech)


class ImportResult:
    def __init__(self, speech, ok=True):
        self.speech = speech
        self.ok = ok


def urlopen(request, timeout=30):
    return urllib.request.urlopen(request, timeout=timeout)


def token_from_env():
    return config.readwise_token()


def folder_from_env():
    return config.readwise_pasta()


def state_path():
    return config.jarvis_home() / STATE_NAME


def load_state():
    empty = {"updated_after": "", "page_cursor": ""}
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        "updated_after": _safe_stamp(data.get("updated_after")),
        "page_cursor": _safe_cursor(data.get("page_cursor")),
    }


def save_state(state):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "page_cursor": _safe_cursor(state.get("page_cursor")),
        "updated_after": _safe_stamp(state.get("updated_after")),
    }
    blob = json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n"
    from .trava import gravar_atomico, trava_arquivo

    with trava_arquivo(path.with_name(path.name + ".lock")):
        gravar_atomico(path, blob, mode=0o600)


def import_speech(root, now, read_only=False, before_write=None, opener=None):
    if read_only:
        return BLOQUEADO_VAULT
    if not token_from_env():
        return FALTA_TOKEN
    if before_write:
        before_write()
    try:
        return import_highlights(root, now=now, opener=opener).speech
    except ReadwiseError as error:
        return error.speech
    except Exception:
        LOG.error("readwise: consulta falhou")
        return FALHA


def import_highlights(root, token=None, now=None, opener=None, folder=None):
    secret = token if token is not None else token_from_env()
    if not secret:
        return ImportResult(FALTA_TOKEN, ok=False)
    root = Path(root)
    relative, problem = resolve_folder(root, folder if folder is not None else folder_from_env())
    if problem:
        return ImportResult(problem, ok=False)
    moment = now or datetime.now(timezone.utc)
    started = _stamp(moment)
    state = load_state()
    created = 0
    updated = 0
    notes = 0
    skipped = 0
    seen = set()
    try:
        for _page in range(MAX_PAGES):
            current = state.get("page_cursor") or ""
            payload = fetch_page(
                secret,
                state.get("updated_after") or "",
                current,
                opener,
            )
            stats = apply_books(root, relative, payload.get("results") or [])
            created += stats["created"]
            updated += stats["updated"]
            notes += stats["notes"]
            skipped += stats["skipped"]
            nxt = _safe_cursor(payload.get("nextPageCursor"))
            if not nxt or nxt == current or nxt in seen:
                state["page_cursor"] = ""
                state["updated_after"] = started
                save_state(state)
                break
            seen.add(nxt)
            state["page_cursor"] = nxt
            save_state(state)
        else:
            save_state(state)
    except ReadwiseError as error:
        return ImportResult(error.speech, ok=False)
    return ImportResult(_speech(created, updated, notes, skipped), ok=True)


def resolve_folder(root, raw):
    text = (raw or "").strip().replace("\\", "/")
    if not text:
        text = DEFAULT_FOLDER
    if text.startswith("/") or text.startswith("~"):
        return None, PASTA_FORA
    parts = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None, PASTA_FORA
        parts.append(part)
    if not parts:
        return None, PASTA_FORA
    if any(part == ".obsidian" for part in parts):
        return None, PASTA_OBSIDIAN
    relative = "/".join(parts)
    from .guardas import caminho_bloqueado

    if caminho_bloqueado(relative):
        if any(part == ".obsidian" for part in parts):
            return None, PASTA_OBSIDIAN
        return None, PASTA_FORA
    base = Path(root).resolve()
    try:
        (base / relative).resolve().relative_to(base)
    except (OSError, ValueError):
        return None, PASTA_FORA
    return relative, None


def montar_pedido(token, updated_after, page_cursor):
    """Só GET. O corpo não leva nota do vault."""
    params = {}
    if updated_after:
        params["updatedAfter"] = updated_after
    if page_cursor:
        params["pageCursor"] = page_cursor
    url = EXPORT_URL
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=None, method="GET")
    request.add_header("Authorization", "Token " + token)
    request.add_header("Accept", "application/json")
    return request


def fetch_page(token, updated_after, page_cursor, opener=None):
    request = montar_pedido(token, updated_after, page_cursor)
    open_url = opener or urlopen
    try:
        with open_url(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        LOG.error("readwise: consulta falhou")
        if getattr(error, "code", 0) in (401, 403):
            raise ReadwiseError(TOKEN_RECUSADO)
        raise ReadwiseError(FALHA)
    except ReadwiseError:
        raise
    except Exception:
        LOG.error("readwise: consulta falhou")
        raise ReadwiseError(FALHA)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        LOG.error("readwise: consulta falhou")
        raise ReadwiseError(FALHA)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        LOG.error("readwise: consulta falhou")
        raise ReadwiseError(FALHA)
    return payload


def apply_books(root, relative, results):
    from .guardas import caminho_bloqueado, escrever, texto_secreto

    stats = {"created": 0, "updated": 0, "notes": 0, "skipped": 0}
    folder = Path(root) / relative
    grouped = _group_books(results)
    for book_id, fragments in grouped:
        meta, highlights = _merge_fragments(fragments)
        if texto_secreto(_plain(meta.get("title"))) or texto_secreto(_plain(meta.get("author"))):
            _recusa("segredo")
            stats["skipped"] += 1
            continue
        path = _find_note(folder, book_id)
        existing = {}
        if path is not None:
            try:
                existing = parse_blocks(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                existing = {}
        created = 0
        updated = 0
        skipped = 0
        for item in highlights:
            hid = _int_id(item.get("id"))
            text = _plain(item.get("text"))
            note = _plain(item.get("note"))
            if not text:
                continue
            if texto_secreto(text) or texto_secreto(note):
                _recusa("segredo")
                skipped += 1
                continue
            rendered = render_highlight(text, note)
            previous = existing.get(hid)
            if previous == rendered:
                continue
            if previous is None:
                created += 1
            else:
                updated += 1
            existing[hid] = rendered
        stats["skipped"] += skipped
        if not existing or (created == 0 and updated == 0):
            continue
        meta = dict(meta)
        meta["highlights"] = highlights
        body = render_note(meta, book_id, existing)
        destination = path or (folder / _filename(meta.get("title"), book_id))
        if destination.is_symlink() or not _dentro(root, destination):
            _recusa("fora")
            stats["skipped"] += 1
            continue
        blocked = caminho_bloqueado(destination)
        if blocked:
            _recusa("obsidian" if "obsidian" in blocked else "credencial")
            stats["skipped"] += 1
            continue
        if not body.strip():
            _recusa("vazio")
            stats["skipped"] += 1
            continue
        if texto_secreto(body):
            _recusa("segredo")
            stats["skipped"] += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            escrever(destination, body, raiz=Path(root))
        except Exception:
            _recusa("bloqueada")
            raise ReadwiseError(ESCRITA_BLOQUEADA)
        stats["created"] += created
        stats["updated"] += updated
        stats["notes"] += 1
    return stats


def parse_blocks(text):
    found = {}
    for match in _BLOCK_RE.finditer(text or ""):
        found[int(match.group(1))] = match.group(2).strip("\n")
    return found


def render_highlight(text, note):
    lines = []
    for line in text.split("\n"):
        lines.append("> " + line if line else ">")
    if note:
        lines.append("")
        lines.append(note)
        if ":::" not in note:
            lines.append("")
            lines.append(_pergunta(text) + " ::: " + _resposta(note))
    return "\n".join(lines).strip("\n")


def render_note(book, book_id, blocks):
    title = _plain(book.get("title")) or "Sem título"
    author = _plain(book.get("author"))
    source = _plain(book.get("source"))
    url = _source_url(book)
    tags = _tags(book, blocks)
    lines = [
        "---",
        "title: " + _yaml_quote(title),
        "author: " + _yaml_quote(author),
        "source: " + _yaml_quote(source),
        "url: " + _yaml_quote(url),
    ]
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append("  - " + _yaml_quote(tag))
    else:
        lines.append("tags: []")
    lines.append("readwise_id: " + str(int(book_id)))
    lines.append("---")
    lines.append("")
    lines.append("# " + title.replace("\n", " "))
    lines.append("")
    for hid in sorted(blocks):
        lines.append("<!-- rw:%d -->" % hid)
        lines.append(blocks[hid].strip("\n"))
        lines.append("<!-- /rw -->")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None, opener=None, now=None):
    del argv
    from .vault import Vault

    if not token_from_env():
        print(FALTA_TOKEN)
        return 1
    vault = Vault.from_env()
    if vault is None:
        print(FALTA_VAULT)
        return 1
    _relative, problem = resolve_folder(vault.path, folder_from_env())
    if problem:
        print(problem)
        return 1
    prep = vault.prepare()
    print(prep.detail)
    if prep.fatal or not prep.ok or prep.read_only:
        if prep.read_only:
            print(BLOQUEADO_VAULT)
        return 1
    result = import_highlights(
        vault.path,
        now=now or datetime.now(timezone.utc),
        opener=opener,
    )
    published = vault.publish("importa meus destaques")
    print(result.speech)
    print(published.detail)
    if not result.ok or not published.ok or published.fatal:
        return 1
    return 0


def _recusa(code):
    allowed = {"obsidian", "credencial", "fora", "vazio", "segredo", "bloqueada"}
    LOG.info("escrita recusada: %s", code if code in allowed else "bloqueada")


def _dentro(root, path):
    base = Path(root).resolve()
    try:
        Path(path).resolve().relative_to(base)
    except (OSError, ValueError):
        return False
    return True


def _speech(created, updated, notes, skipped):
    if created == 0 and updated == 0:
        speech = NADA_NOVO
    else:
        parts = []
        if created:
            word = "destaque" if created == 1 else "destaques"
            parts.append("importei %d %s" % (created, word))
        if updated:
            parts.append("atualizei %d" % updated)
        note_word = "nota" if notes == 1 else "notas"
        body = " e ".join(parts)
        speech = body[:1].upper() + body[1:] + " em %d %s, senhor." % (notes, note_word)
    if skipped:
        extra = " Um trecho foi recusado." if skipped == 1 else " Trechos foram recusados."
        speech += extra
    return speech


def _group_books(results):
    order = []
    grouped = {}
    for book in results:
        if not isinstance(book, dict):
            continue
        book_id = _int_id(book.get("user_book_id"))
        if book_id is None:
            continue
        if book_id not in grouped:
            grouped[book_id] = []
            order.append(book_id)
        grouped[book_id].append(book)
    return [(book_id, grouped[book_id]) for book_id in order]


def _merge_fragments(fragments):
    meta = fragments[-1]
    highlights = {}
    order = []
    for fragment in fragments:
        items = fragment.get("highlights") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            hid = _int_id(item.get("id"))
            if hid is None:
                continue
            if hid not in highlights:
                order.append(hid)
            highlights[hid] = item
    return meta, [highlights[hid] for hid in order]


def _find_note(folder, book_id):
    if not folder.is_dir():
        return None
    marker = "readwise_id: %d" % int(book_id)
    for path in sorted(folder.glob("*.md")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            head = path.read_text(encoding="utf-8")[:4000]
        except (OSError, UnicodeError):
            continue
        front = _frontmatter(head)
        if any(line.strip() == marker for line in front.splitlines()):
            return path
    return None


def _frontmatter(text):
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    if end == -1:
        return ""
    return text[4:end]


def _filename(title, book_id):
    from .routines import fold

    folded = fold(_plain(title))
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:48].strip("-")
    if not slug:
        slug = "leitura"
    return "%s-%d.md" % (slug, int(book_id))


def _source_url(book):
    from .guardas import texto_secreto

    for key in ("source_url", "unique_url"):
        value = _plain(book.get(key))
        if value and not texto_secreto(value):
            return value
    return ""


def _tags(book, blocks):
    del blocks
    from .guardas import texto_secreto

    found = []
    seen = set()
    pools = list(book.get("book_tags") or [])
    for item in book.get("highlights") or []:
        if isinstance(item, dict):
            pools.extend(item.get("tags") or [])
    for item in pools:
        name = item.get("name") if isinstance(item, dict) else item
        text = _plain(name)[:40]
        if not text or texto_secreto(text):
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(text)
    found.sort(key=lambda item: item.casefold())
    return found


def _pergunta(text):
    snippet = " ".join(text.split()).replace(":::", " ")
    snippet = " ".join(snippet.split())
    if len(snippet) > 160:
        snippet = snippet[:157].rstrip() + "..."
    if not snippet:
        snippet = "este trecho"
    return "O que este destaque registra: " + snippet


def _resposta(note):
    text = " ".join(note.split()).replace(":::", " ")
    text = " ".join(text.split())
    return text or "nota do senhor"


def _yaml_quote(value):
    text = _plain(value).replace("\\", "\\\\").replace('"', '\\"')
    return '"' + text + '"'


def _plain(value):
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _int_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _stamp(moment):
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_stamp(value):
    text = str(value or "").strip()
    if _STAMP_RE.match(text):
        return text
    return ""


def _safe_cursor(value):
    if value is None:
        return ""
    text = str(value).strip()
    if _CURSOR_RE.match(text):
        return text
    return ""


if __name__ == "__main__":
    import sys

    sys.exit(main())
