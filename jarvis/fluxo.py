"""Lê o fluxo do Claude e do Ollama e entrega cada frase fechada."""

import json

from .frases import split_ready


class StreamError(Exception):
    pass


def stream_command(command):
    """Troca a saída json pela saída em fluxo, sem mexer no resto do comando."""
    updated = []
    skip = False
    for part in command:
        if skip:
            skip = False
            continue
        if part == "--output-format":
            updated.extend(["--output-format", "stream-json"])
            skip = True
            continue
        updated.append(part)
    if "--include-partial-messages" not in updated:
        updated.append("--include-partial-messages")
    if "--verbose" not in updated:
        updated.append("--verbose")
    return updated


def consume_events(events, on_sentence):
    """Consome eventos do Claude. Devolve texto, sessão e se a fala pediu para parar."""
    full = ""
    emitted = []
    session = None
    saw_delta = False
    error = ""
    stopped = False
    try:
        for item in events:
            event = _as_event(item)
            if event is None:
                continue
            if event.get("type") == "result":
                session = event.get("session_id") or session
                if event.get("is_error"):
                    error = str(event.get("result") or "erro")[:400]
                result = event.get("result")
                if isinstance(result, str) and len(result) >= len(full):
                    full = result
                continue
            piece, is_delta = event_text(event)
            if is_delta and piece:
                saw_delta = True
                full += piece
            elif piece and not saw_delta and len(piece) >= len(full):
                full = piece
            else:
                continue
            if not _emit_ready(full, emitted, on_sentence):
                stopped = True
                break
        if error and not emitted:
            raise StreamError(error)
        if not stopped and _emit_ready(full, emitted, on_sentence):
            _ready, rest = split_ready(full)
            tail = " ".join(rest.split())
            if tail:
                emitted.append(tail)
                if on_sentence(tail) is False:
                    stopped = True
        elif not stopped:
            stopped = True
    finally:
        _close(events)
    return _finish(emitted, full, session, stopped)


def consume_ollama(lines, on_sentence):
    full = ""
    emitted = []
    for item in lines:
        event = _as_event(item)
        if event is None:
            continue
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        piece = message.get("content") or ""
        if piece:
            full += str(piece)
            if not _emit_ready(full, emitted, on_sentence):
                return " ".join(emitted)
        if event.get("done"):
            break
    _ready, rest = split_ready(full)
    tail = " ".join(rest.split())
    if tail:
        emitted.append(tail)
        if on_sentence(tail) is False:
            return " ".join(emitted)
    return " ".join(emitted) or " ".join(full.split())


def event_text(event):
    if event.get("type") == "stream_event":
        inner = event.get("event") if isinstance(event.get("event"), dict) else {}
        delta = inner.get("delta") if isinstance(inner.get("delta"), dict) else {}
        if delta.get("type") == "text_delta":
            return str(delta.get("text") or ""), True
        return "", False
    if event.get("type") != "assistant":
        return "", False
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    content = message.get("content")
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    elif isinstance(content, str):
        parts.append(content)
    return "".join(parts), False


def _as_event(item):
    if isinstance(item, dict):
        return item
    if not isinstance(item, str):
        return None
    line = item.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _emit_ready(full, emitted, on_sentence):
    ready, _rest = split_ready(full)
    while len(emitted) < len(ready):
        sentence = ready[len(emitted)]
        emitted.append(sentence)
        if on_sentence(sentence) is False:
            return False
    return True


def _finish(emitted, full, session, stopped):
    text = " ".join(emitted).strip() or " ".join((full or "").split())
    return text, session, stopped


def _close(events):
    closer = getattr(events, "close", None)
    if closer is None:
        return
    try:
        closer()
    except Exception:
        return
