"""Fatos locais sobre o usuário.

O arquivo é ~/.jarvis/memoria.json. Não entra no vault e não guarda segredo.
"""

import hashlib
import json
import re
import threading
from pathlib import Path

from . import config
from .guardas import texto_secreto
from .routines import fold

_BULLET = re.compile(r"^\s*-\s+(?P<stamp>\d{4}-\d{2}-\d{2}):\s+(?P<body>.+?)\s*$")
_LOCK = threading.RLock()


def memory_path():
    return config.jarvis_home() / "memoria.json"


def add_fact(text, day):
    cleaned = " ".join((text or "").split())
    if not cleaned or texto_secreto(cleaned):
        return False
    cleaned = cleaned[:400].rstrip()
    stamp = str(day or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
        stamp = ""
    with _LOCK:
        with _trava():
            data = _load()
            folded = fold(cleaned)
            for item in data["fatos"]:
                if fold(item.get("texto") or "") == folded:
                    return True
            data["fatos"].append({"id": _fact_id(cleaned), "texto": cleaned, "em": stamp})
            _save(data)
            return True


def list_facts():
    return list(_load()["fatos"])


def remove_fact(fact_id):
    with _LOCK:
        with _trava():
            data = _load()
            kept = [item for item in data["fatos"] if item.get("id") != fact_id]
            if len(kept) == len(data["fatos"]):
                return False
            data["fatos"] = kept
            _save(data)
            return True


def match_facts(query):
    folded = fold(query)
    if len(folded) < 2:
        return []
    found = []
    for item in list_facts():
        if folded in fold(item.get("texto") or ""):
            found.append(item)
    return found


def about_speech(root=None):
    if root is not None:
        _import_profile(root)
    facts = list_facts()
    extras = _state_lines()
    if not facts and not extras:
        return "Ainda não guardei nada sobre o senhor."
    parts = ["Isto é o que tenho guardado sobre o senhor."]
    shown = facts[:8]
    for item in shown:
        parts.append(str(item.get("texto") or "").strip() + ".")
    extra = len(facts) - len(shown)
    if extra:
        parts.append(f"E mais {extra} fatos.")
    parts.extend(extras)
    return " ".join(part for part in parts if part)


def prepare_forget(query):
    text = " ".join((query or "").split()).strip(" \t.?!")
    if not text:
        return "O que devo esquecer, senhor?", None
    hits = match_facts(text)
    if not hits:
        return "Não encontrei isso no que guardei sobre o senhor.", None
    shown = hits[:4]
    pending = {"kind": "forget", "options": shown}
    if len(shown) == 1:
        return f"Esqueço este item, senhor: {shown[0]['texto']}?", pending
    parts = [f"{index + 1}, {item['texto']}" for index, item in enumerate(shown)]
    return (
        "Encontrei mais de um item, senhor. Diga o número. " + ". ".join(parts) + ".",
        pending,
    )


def apply_forget(root, pending, choice, profile=True):
    options = (pending or {}).get("options") or []
    if choice == "yes":
        if len(options) != 1:
            return "Diga o número, senhor."
        choice = 0
    if not isinstance(choice, int) or choice < 0 or choice >= len(options):
        return "Não encontrei essa opção, senhor."
    option = options[choice]
    text = option.get("texto") or ""
    if profile and root is not None:
        removed = _remove_profile_line(root, text)
        if removed is False:
            return "Não apaguei, senhor. A escrita foi bloqueada."
    if not remove_fact(option.get("id")):
        return "Não encontrei mais esse item, senhor."
    return "Esqueci, senhor."


def _import_profile(root):
    try:
        from .bridge import profile_file
        from .routines import load_places
    except Exception:
        return
    root = Path(root)
    try:
        places = load_places(root)
        path = profile_file(root, places, _today(places))
    except Exception:
        return
    if not path.is_file():
        return
    try:
        current = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in current.splitlines():
        match = _BULLET.match(line)
        if not match:
            continue
        body = match.group("body").strip()
        if not body or texto_secreto(body):
            continue
        add_fact(body, match.group("stamp"))


def _remove_profile_line(root, text):
    try:
        from .bridge import profile_file
        from .guardas import tentar
        from .routines import load_places
    except Exception:
        return None
    folded = fold(text)
    if len(folded) < 2:
        return None
    root = Path(root)
    try:
        places = load_places(root)
        path = profile_file(root, places, _today(places))
    except Exception:
        return None
    if not path.is_file():
        return None
    try:
        current = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    kept = []
    changed = False
    for line in current.splitlines():
        if line.lstrip().startswith("- ") and folded in fold(line):
            changed = True
            continue
        kept.append(line)
    if not changed:
        return None
    updated = "\n".join(kept).strip()
    if not updated:
        updated = "# Perfil"
    updated += "\n"
    if not tentar(path, updated, checar="", raiz=root):
        return False
    return True


def _today(places):
    from datetime import datetime

    return datetime.now(places.tz).date()


def _state_lines():
    lines = []
    try:
        from .review import load_state

        cards = load_state().get("cards")
        if isinstance(cards, dict) and cards:
            count = len(cards)
            noun = "cartão" if count == 1 else "cartões"
            lines.append(f"Há {count} {noun} na revisão.")
    except Exception:
        pass
    try:
        from .alerts import load_alerts

        paused = load_alerts().get("paused_until") or ""
        if paused:
            lines.append(f"Os alertas estão pausados até {paused}.")
    except Exception:
        pass
    return lines


def _fact_id(text):
    return hashlib.sha256(fold(text).encode("utf-8")).hexdigest()[:12]


def _load():
    path = memory_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {"fatos": []}
    if not isinstance(data, dict):
        return {"fatos": []}
    raw = data.get("fatos")
    facts = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get("texto") or "").split())
            fact_id = str(item.get("id") or "")
            stamp = str(item.get("em") or "")
            if not text or not re.fullmatch(r"[0-9a-f]{12}", fact_id):
                continue
            if texto_secreto(text):
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
                stamp = ""
            facts.append({"id": fact_id, "texto": text[:400], "em": stamp})
    return {"fatos": facts}


def _trava():
    from .trava import trava_arquivo

    path = memory_path()
    return trava_arquivo(path.with_name(path.name + ".lock"))


def _save(data):
    from .trava import gravar_atomico

    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"fatos": data.get("fatos") or []}, ensure_ascii=False, indent=2) + "\n"
    gravar_atomico(path, payload, mode=0o600)
