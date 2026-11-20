"""Controle dos avisos em ~/.jarvis/state.json.

"Silencia esse aviso hoje" dura só o dia. "Silencia sempre" segue nas próximas.
"Pausa os alertas até amanhã" segura a fala sem apagar o que ainda vai ser avisado.
"""

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .state import load, update

DEFAULT_ZONE = "America/Sao_Paulo"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDENTITY = re.compile(r"^(?:jira|github|mail|lembrete|recado):[^\s]{1,180}$")


def event_identity(event):
    if not isinstance(event, dict):
        return ""
    kind = str(event.get("kind") or "")
    if kind == "jira":
        key = str(event.get("key") or "").strip()
        return f"jira:{key}" if key else ""
    if kind in {"github", "mail"}:
        ident = str(event.get("id") or "").strip()
        return f"{kind}:{ident}" if ident else ""
    return ""


def reminder_identity(text):
    from .routines import fold

    folded = "-".join(fold(text).split())[:120]
    if not folded:
        return ""
    return "lembrete:" + folded


def recado_identity(vault, path):
    from pathlib import Path

    try:
        relative = Path(path).resolve().relative_to(Path(vault).resolve()).as_posix()
    except (OSError, ValueError):
        relative = Path(path).name
    relative = "-".join(relative.split())
    if not relative or relative.startswith(".") or ".." in relative.split("/"):
        return ""
    return "recado:" + relative[:160]


def silence(mode, moment):
    data = load_alerts()
    last = data["last"]
    if not last:
        return "Não há aviso recente para silenciar, senhor."
    day = local_date(moment, data["zone"]).isoformat()

    def mutate(state):
        alerts = _read(state)
        if mode == "always":
            for ident in last:
                if ident not in alerts["always"]:
                    alerts["always"].append(ident)
            alerts["always"] = alerts["always"][-200:]
        else:
            bucket = list(alerts["today"].get(day) or [])
            for ident in last:
                if ident not in bucket:
                    bucket.append(ident)
            alerts["today"][day] = bucket[-200:]
        state["alerts"] = alerts

    update(mutate)
    plural = len(last) > 1
    if mode == "always":
        if plural:
            return "Silenciei esses avisos de vez, senhor."
        return "Silenciei esse aviso de vez, senhor."
    if plural:
        return "Silenciei esses avisos até o fim do dia, senhor."
    return "Silenciei esse aviso até o fim do dia, senhor."


def pause_alerts(moment, zone=DEFAULT_ZONE):
    day = local_date(moment, zone) + timedelta(days=1)

    def mutate(state):
        alerts = _read(state)
        alerts["paused_until"] = day.isoformat()
        alerts["zone"] = _zone_name(zone)
        state["alerts"] = alerts

    update(mutate)
    return "Pausa nos alertas até amanhã, senhor."


def remember_last(idents):
    cleaned = []
    for ident in idents or []:
        text = str(ident or "").strip()
        if IDENTITY.match(text) and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return

    def mutate(state):
        alerts = _read(state)
        alerts["last"] = cleaned[:20]
        state["alerts"] = alerts

    update(mutate)


def is_paused(moment):
    data = load_alerts()
    paused = data["paused_until"]
    if not paused:
        return False
    return local_date(moment, data["zone"]).isoformat() < paused


def control_for(moment):
    data = load_alerts()
    day = local_date(moment, data["zone"]).isoformat()
    today = data["today"].get(day) or []
    return {
        "paused": is_paused(moment),
        "always": list(data["always"]),
        "today": list(today),
    }


def muted_ids(moment):
    data = control_for(moment)
    return set(data["always"]) | set(data["today"])


def load_alerts():
    return _read(load())


def local_date(moment, zone):
    if moment is None:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(_zone_name(zone))
    except Exception:
        tz = ZoneInfo(DEFAULT_ZONE)
    return moment.astimezone(tz).date()


def _read(state):
    raw = state.get("alerts") if isinstance(state, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    paused = str(raw.get("paused_until") or "")
    if not DATE.match(paused):
        paused = ""
    zone = _zone_name(raw.get("zone") or DEFAULT_ZONE)
    today = {}
    incoming = raw.get("today") if isinstance(raw.get("today"), dict) else {}
    for key, value in incoming.items():
        stamp = str(key or "")
        if not DATE.match(stamp):
            continue
        today[stamp] = _idents(value)
    return {
        "paused_until": paused,
        "zone": zone,
        "always": _idents(raw.get("always")),
        "today": today,
        "last": _idents(raw.get("last")),
    }


def _idents(value):
    found = []
    if not isinstance(value, list):
        return found
    for item in value:
        text = str(item or "").strip()
        if IDENTITY.match(text) and text not in found:
            found.append(text)
    return found[-200:]


def _zone_name(zone):
    text = str(zone or "").strip() or DEFAULT_ZONE
    if not re.fullmatch(r"[A-Za-z0-9_+/-]{1,64}", text):
        return DEFAULT_ZONE
    try:
        ZoneInfo(text)
    except Exception:
        return DEFAULT_ZONE
    return text
