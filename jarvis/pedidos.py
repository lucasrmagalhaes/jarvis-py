"""Log local de cada pedido, sem a pergunta e sem o conteúdo da nota.

O arquivo é ~/.jarvis/log.jsonl. Gira ao passar do limite de tamanho.
"""

import json
import os
from pathlib import Path

from . import config

LIMITE_BYTES = 200_000
_CHAVES = ("em", "intencao", "duracao", "sucesso")


def log_path():
    return config.jarvis_home() / "log.jsonl"


def record_turn(intent, duration, success, moment):
    try:
        from .privacidade import modo_privado_ativo

        if modo_privado_ativo():
            return
    except Exception:
        return
    payload = {
        "em": getattr(moment, "isoformat", lambda: "")(),
        "intencao": _intent(intent),
        "duracao": _duration(duration),
        "sucesso": bool(success),
    }
    line = json.dumps({key: payload[key] for key in _CHAVES}, ensure_ascii=False, separators=(",", ":"))
    try:
        _append(log_path(), line)
    except (OSError, TimeoutError):
        return


def summary():
    """Contagem por intenção e duração média. Não devolve texto de pedido."""

    counts = {}
    totals = {}
    for line in _read_lines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        intent = _intent(payload.get("intencao"))
        duration = _duration(payload.get("duracao"))
        counts[intent] = counts.get(intent, 0) + 1
        totals[intent] = totals.get(intent, 0.0) + duration
    rows = []
    for intent in sorted(counts):
        count = counts[intent]
        average = totals[intent] / count if count else 0.0
        rows.append(
            {
                "intencao": intent,
                "vezes": count,
                "media": round(average, 3),
            }
        )
    total = sum(counts.values())
    spent = sum(totals.values())
    return {
        "total": total,
        "media": round(spent / total, 3) if total else 0.0,
        "por_intencao": rows,
    }


def _read_lines():
    found = []
    path = log_path()
    for candidate in (path, Path(str(path) + ".1")):
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip():
                found.append(line)
    return found


def _intent(value):
    text = "".join(char for char in str(value or "chat") if char.isalnum() or char == "_")
    return (text or "chat")[:40]


def _duration(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    if number > 86400:
        return 86400.0
    return round(number, 3)


def _append(path, line):
    from .trava import trava_arquivo

    path.parent.mkdir(parents=True, exist_ok=True)
    with trava_arquivo(path.with_name(path.name + ".lock"), espera=2):
        _rotate(path)
        fd = os.open(str(path), os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)


def _rotate(path):
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < LIMITE_BYTES:
        return
    backup = Path(str(path) + ".1")
    try:
        os.replace(path, backup)
    except OSError:
        return
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
