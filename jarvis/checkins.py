"""Briefing no primeiro arranque do dia e resumo ao fim da tarde."""

from datetime import datetime
from zoneinfo import ZoneInfo

from . import config
from .routines import autosave_week, briefing_speech, classify, load_places, run_routine
from .state import update

DEFAULT_ZONE = "America/Sao_Paulo"


def due_kind(now, state, morning_on, evening_on, evening_at):
    today = now.date().isoformat()
    state = state or {}
    threshold = now.replace(
        hour=evening_at[0],
        minute=evening_at[1],
        second=0,
        microsecond=0,
    )
    if now.weekday() == 6 and now >= threshold and state.get("week") != today:
        return "week"
    if evening_on and now >= threshold and state.get("evening") != today:
        return "evening"
    if morning_on and state.get("morning") != today:
        if evening_on and now >= threshold:
            return None
        return "morning"
    return None


def digest_due(now, state, at):
    if now.weekday() != 6:
        return False
    threshold = now.replace(
        hour=at[0],
        minute=at[1],
        second=0,
        microsecond=0,
    )
    if now < threshold:
        return False
    today = now.date().isoformat()
    return (state or {}).get("digest") != today


def briefing_due(now, state, at):
    threshold = now.replace(
        hour=at[0],
        minute=at[1],
        second=0,
        microsecond=0,
    )
    if now < threshold:
        return False
    today = now.date().isoformat()
    return (state or {}).get("briefing_telegram") != today


def mark_briefing(day):
    stamp = day.isoformat()

    def mutate(data):
        data["briefing_telegram"] = stamp

    update(mutate)


def mark_digest(day):
    stamp = day.isoformat()

    def mutate(data):
        data["digest"] = stamp

    update(mutate)


def lembrete_nota_due(now, state, at):
    threshold = now.replace(
        hour=at[0],
        minute=at[1],
        second=0,
        microsecond=0,
    )
    if now < threshold:
        return False
    today = now.date().isoformat()
    return (state or {}).get("lembrete_nota") != today


def mark_lembrete_nota(day):
    stamp = day.isoformat()

    def mutate(data):
        data["lembrete_nota"] = stamp

    update(mutate)


def revisao_semanal_due(now, state, at):
    if now.weekday() != 6:
        return False
    threshold = now.replace(
        hour=at[0],
        minute=at[1],
        second=0,
        microsecond=0,
    )
    if now < threshold:
        return False
    today = now.date().isoformat()
    return (state or {}).get("revisao_semanal") != today


def mark_revisao_semanal(day):
    stamp = day.isoformat()

    def mutate(data):
        data["revisao_semanal"] = stamp

    update(mutate)


def toque_sequencia_due(now, state, at):
    threshold = now.replace(
        hour=at[0],
        minute=at[1],
        second=0,
        microsecond=0,
    )
    if now < threshold:
        return False
    today = now.date().isoformat()
    return (state or {}).get("toque_sequencia") != today


def mark_toque_sequencia(day):
    stamp = day.isoformat()

    def mutate(data):
        data["toque_sequencia"] = stamp

    update(mutate)


def digest_text(root, now):
    from .aprendizado import learned_speech

    if root is None:
        return ""
    return learned_speech(root, now)


def mark_sent(kind, day):
    stamp = day.isoformat()

    def mutate(data):
        data[kind] = stamp
        if kind == "evening":
            data["morning"] = stamp

    update(mutate)


def local_now(root, clock=None):
    if clock is not None:
        return clock()
    zone = ZoneInfo(DEFAULT_ZONE)
    if root is not None:
        try:
            zone = load_places(root).tz
        except Exception:
            zone = ZoneInfo(DEFAULT_ZONE)
    return datetime.now(zone)


def render(root, kind, now, read_only=False):
    if root is None:
        return "O vault não está configurado, senhor.", None
    if kind == "week":
        return autosave_week(root, now, read_only=read_only), None
    if kind == "morning":
        places = load_places(root)
        return briefing_speech(root, places, now), None
    session = {}
    reply = run_routine(
        root,
        classify("resumo do fim do dia"),
        now,
        read_only=read_only,
        session=session,
    )
    return reply, session.get("pending")


def settings_from_env():
    return {
        "morning_on": config.checkin_morning(),
        "evening_on": config.checkin_evening(),
        "evening_at": config.checkin_evening_at(),
        "enabled": config.checkin_enabled(),
    }
