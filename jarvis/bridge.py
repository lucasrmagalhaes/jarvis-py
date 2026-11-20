"""Caixa dos assistentes e nota de perfil, dentro do vault.

O formato das notas trocadas é frontmatter com de, para, data e status.
Sem regra no AGENTS.md, a entrada é Jarvis/Inbox e a saída é Jarvis/Outbox.
"""

import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from .ajustes import nome_usuario
from .guardas import FALA_BLOQUEIO, tentar
from .log import LOG

SKIP = {".git", ".obsidian", "node_modules", ".trash"}
STATUS_NEW = "novo"
STATUS_TOLD = "avisado"
STATUS_READ = "lido"


class InboxNote:
    def __init__(self, path, meta, body):
        self.path = path
        self.meta = meta
        self.body = body


class InboxService:
    def __init__(self, vault, speak, bus, lock, interval=15, on_status=None, also=None):
        self.vault = vault
        self.speak = speak
        self.bus = bus
        self.lock = lock
        self.interval = interval
        self.on_status = on_status
        self.also = also
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="jarvis-inbox", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def tick(self):
        with self.lock:
            self._tick()

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as error:
                LOG.error("caixa de entrada: %s", error)

    def _tick(self):
        from .alerts import is_paused, recado_identity, remember_last

        if is_paused(datetime.now(timezone.utc)):
            return
        notes = inbox_notes(self.vault.path, {STATUS_NEW})
        if not notes:
            return
        self.vault.resync_snapshot()
        marked = []
        for note in notes:
            if set_status(note.path, STATUS_TOLD, self.vault.path):
                marked.append(note)
        if marked and self.vault.sync and not self.vault.blocked:
            self.vault.publish("aviso da caixa de entrada")
        if not marked:
            return
        try:
            remember_last(
                [
                    recado_identity(self.vault.path, note.path)
                    for note in marked
                ]
            )
        except Exception:
            LOG.error("caixa: não guardei o aviso")
        text = alert_text(marked)
        print(f"\nJARVIS: {text}")
        self.bus.transcript("reply", text)
        self.bus.state("speaking")
        try:
            if self.speak is not None:
                self.speak(text)
            self._also(text)
        finally:
            self.bus.state("standby")
        if self.on_status:
            self.on_status(self.vault.hud_payload())

    def _also(self, text):
        if self.also is None:
            return
        try:
            self.also(text)
        except Exception as error:
            LOG.error("aviso extra: %s", error)


def alert_text(notes):
    if len(notes) == 1:
        who = _who(notes[0])
        return f"Senhor, chegou recado de {who}."
    return f"Senhor, chegaram {len(notes)} recados dos assistentes."


def summarize_inbox(root):
    notes = inbox_notes(root, {STATUS_NEW, STATUS_TOLD})
    if not notes:
        return "Não há recado novo dos assistentes, senhor."
    shown = notes[:4]
    extra = len(notes) - len(shown)
    bits = []
    for note in shown:
        who = _who(note)
        body = " ".join(note.body.split())
        if len(body) > 140:
            body = body[:137].rstrip() + "..."
        bits.append(f"{who}: {body or 'sem texto'}")
    if len(notes) == 1:
        return f"Senhor, recado novo. {bits[0]}."
    speech = f"Senhor, há {len(notes)} recados novos. " + ". ".join(bits)
    if extra:
        speech += f". E mais {extra} sem o texto"
    return speech + "."


def read_inbox(root, read_only=False, before_write=None):
    notes = inbox_notes(root, {STATUS_NEW, STATUS_TOLD})
    if not notes:
        return "Não há recado novo dos assistentes, senhor."
    speech = _read_speech(notes)
    if read_only:
        return speech + " Não marquei como lido porque o vault está bloqueado para escrita."
    if before_write:
        before_write()
    for note in notes:
        set_status(note.path, STATUS_READ, root)
    return speech


def write_outbox(root, places, name, body, moment, read_only=False, before_write=None):
    safe = sanitize_name(name)
    text = " ".join((body or "").split())
    if not safe or not text:
        return "Não entendi para quem enviar o pedido, senhor."
    if read_only:
        return "Não gravei o pedido, senhor. O vault está bloqueado para escrita agora."
    if before_write:
        before_write()
    folder = _inside(root, outbox_dir(root, places) / safe)
    if folder is None:
        return "Não gravei o pedido, senhor. O destino ficou fora do vault."
    folder.mkdir(parents=True, exist_ok=True)
    stamp = moment.strftime("%Y-%m-%d")
    clock = moment.strftime("%H%M")
    path = folder / f"{stamp}-{clock}.md"
    suffix = 2
    while path.exists():
        path = folder / f"{stamp}-{clock}-{suffix}.md"
        suffix += 1
    note = render_message(
        {"de": nome_usuario(), "para": safe, "data": stamp, "status": STATUS_NEW},
        text + "\n",
    )
    if not tentar(path, note, checar=note):
        return FALA_BLOQUEIO
    return f"Pedi a {safe}, senhor. O pedido ficou na caixa de saída."


def remember_fact(root, places, fact, moment, read_only=False, before_write=None):
    text = " ".join((fact or "").split())
    if not text:
        return "O que devo lembrar, senhor?"
    text = text[:400].rstrip()
    if read_only:
        return "Não gravei o fato, senhor. O vault está bloqueado para escrita agora."
    if before_write:
        before_write()
    path = profile_file(root, places, moment.date())
    if _inside(root, path) is None:
        return "Não gravei o fato, senhor. A nota de perfil ficou fora do vault."
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = moment.strftime("%Y-%m-%d")
    line = f"- {stamp}: {text}\n"
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if text.casefold() in current.casefold():
        _remember_local(text, stamp)
        return "Esse fato já está na nota de perfil, senhor."
    meta, body = split_frontmatter(current)
    if current.startswith("---") and meta is not None:
        if body and not body.endswith("\n"):
            body += "\n"
        if not tentar(path, render_message(meta, body + line), checar=line):
            return FALA_BLOQUEIO
    elif current:
        if not current.endswith("\n"):
            current += "\n"
        if not tentar(path, current + line, checar=line):
            return FALA_BLOQUEIO
    else:
        if not tentar(path, f"# Perfil\n\n{line}", checar=line):
            return FALA_BLOQUEIO
    _remember_local(text, stamp)
    return "Guardei na nota de perfil, senhor."


def _remember_local(text, stamp):
    try:
        from .memoria import add_fact

        add_fact(text, stamp)
    except Exception:
        LOG.error("nao guardei o fato na memoria local")


def profile_text(root, limit=2500):
    from .routines import load_places

    root = Path(root)
    places = load_places(root)
    day = datetime.now(places.tz).date()
    path = profile_file(root, places, day)
    if not path.is_file():
        return ""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    _meta, body = split_frontmatter(current)
    body = body.strip()
    if len(body) <= limit:
        return body
    return body[-limit:]


def inbox_notes(root, statuses):
    folder = inbox_dir(root)
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.rglob("*.md")):
        relative = path.relative_to(folder)
        if any(part in SKIP or part.startswith(".") for part in relative.parts):
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = split_frontmatter(current)
        status = (meta.get("status") or STATUS_NEW).casefold()
        if status not in statuses:
            continue
        found.append(InboxNote(path, meta, body))
    return found


def inbox_dir(root, places=None):
    root = Path(root)
    if places is None:
        from .routines import load_places

        places = load_places(root)
    if places.inbox:
        path = root / places.inbox
        if path.suffix == ".md":
            return path.parent
        return path
    return root / "Jarvis" / "Inbox"


def outbox_dir(root, places=None):
    root = Path(root)
    if places is None:
        from .routines import load_places

        places = load_places(root)
    if places.outbox:
        path = root / places.outbox
        if path.suffix == ".md":
            return path.parent
        return path
    return root / "Jarvis" / "Outbox"


def profile_file(root, places, day):
    from .routines import _apply_date

    root = Path(root)
    if places.profile:
        return root / _apply_date(places.profile, day, root)
    return root / "Jarvis" / "Perfil.md"


def sanitize_name(name):
    raw = (name or "").strip()
    if not raw or any(char in raw for char in "/\\") or ".." in raw:
        return ""
    if not re.fullmatch(r"[^\W\d_][^\W]{0,40}", raw, flags=re.UNICODE):
        return ""
    return raw


def set_status(path, status, raiz=None):
    path = Path(path)
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return False
    meta, body = split_frontmatter(current)
    if not current.startswith("---"):
        meta = {"status": status}
        body = current
    else:
        meta["status"] = status
    return tentar(path, render_message(meta, body), checar="", raiz=raiz)


def split_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    meta = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            meta[key] = value.strip()
    return meta, body


def render_message(meta, body):
    order = ["de", "para", "data", "status"]
    keys = [key for key in order if key in meta]
    keys.extend(key for key in meta if key not in order)
    lines = ["---"]
    for key in keys:
        value = " ".join(str(meta[key]).split())
        lines.append(f"{key}: {value}")
    lines.append("---")
    body = body if body.startswith("\n") or body == "" else "\n" + body
    if body and not body.endswith("\n"):
        body += "\n"
    return "\n".join(lines) + body


def _read_speech(notes):
    shown = notes[:4]
    extra = len(notes) - len(shown)
    bits = []
    for note in shown:
        who = _who(note)
        body = " ".join(note.body.split())
        if len(body) > 180:
            body = body[:177].rstrip() + "..."
        bits.append(f"De {who}: {body or 'sem texto'}")
    sentence = "Recados dos assistentes. " + ". ".join(bits)
    if extra:
        sentence += f". E mais {extra}"
    return sentence + "."


def _who(note):
    who = " ".join(str(note.meta.get("de") or "um assistente").split())
    return who[:40] or "um assistente"


def _inside(root, path):
    from .paths import esta_dentro

    if not esta_dentro(path, root):
        return None
    return Path(path)
