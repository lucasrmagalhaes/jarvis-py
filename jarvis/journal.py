"""Log local dos pedidos. Não entra no vault e não guarda a resposta."""

import json
import os
import threading
from datetime import date, timedelta

from . import config

_LOCK = threading.Lock()
_KEEP_DAYS = 21
_LABELS = {
    "hoje": "Hoje",
    "ontem": "Ontem",
    "anteontem": "Anteontem",
}
_OFFSETS = {"hoje": 0, "ontem": 1, "anteontem": 2}


def record(message, moment):
    text = " ".join((message or "").split())
    if not text:
        return
    try:
        from .privacidade import modo_privado_ativo

        if modo_privado_ativo():
            return
    except Exception:
        return
    text = text[:300]
    try:
        path = _path(moment.date())
        line = json.dumps({"em": moment.isoformat(), "pedido": text}, ensure_ascii=False)
        with _LOCK:
            from .trava import trava_arquivo

            with trava_arquivo(path.with_name(path.name + ".lock"), espera=2):
                _append(path, line)
                _prune(path.parent, moment.date())
    except (OSError, TimeoutError):
        return


def history_speech(moment, day_key):
    key = (day_key or "ontem").casefold()
    offset = _OFFSETS.get(key, 1)
    day = moment.date() - timedelta(days=offset)
    found = read_day(day)
    label = _LABELS.get(key, "Ontem")
    when = label.casefold()
    if not found:
        return f"Não há pedido registrado {when}, senhor."
    shown = found[:5]
    bits = [f"{label} o senhor pediu: {shown[0]}."]
    for text in shown[1:]:
        bits.append(f"E também: {text}.")
    sentence = " ".join(bits)
    extra = len(found) - len(shown)
    if extra:
        sentence += f" E mais {extra}."
    return sentence


def read_day(day):
    path = _path(day)
    if not path.is_file():
        return []
    found = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        text = " ".join(str(payload.get("pedido") or "").split())
        if text:
            found.append(text[:300])
    return found


def _path(day):
    return config.jarvis_home() / "logs" / "interacoes" / f"{day.isoformat()}.log"


def _append(path, line):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _prune(directory, today):
    limit = today - timedelta(days=_KEEP_DAYS)
    try:
        names = list(directory.iterdir())
    except OSError:
        return
    for path in names:
        if path.suffix != ".log":
            continue
        try:
            year, month, day = (int(part) for part in path.stem.split("-"))
            found = date(year, month, day)
        except (TypeError, ValueError):
            continue
        if found < limit:
            try:
                path.unlink()
            except OSError:
                pass
