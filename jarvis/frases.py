"""Corta a fala em frases completas, para começar a falar antes do fim."""

import re

_SENTENCE = re.compile(r"^(.{3,}?[.!?])(?:\s+|\Z)", re.S)


def split_ready(buffer):
    """Devolve as frases já fechadas e o resto que ainda pode crescer."""
    ready = []
    rest = buffer or ""
    while True:
        match = _SENTENCE.match(rest)
        if not match:
            break
        sentence = " ".join(match.group(1).split())
        if len(sentence) < 3:
            break
        ready.append(sentence)
        rest = rest[match.end() :]
    return ready, rest


def split_all(text):
    ready, rest = split_ready(text or "")
    tail = " ".join(rest.split())
    if tail:
        ready.append(tail)
    return ready
