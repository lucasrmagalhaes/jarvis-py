"""Notas criadas ou alteradas nos últimos sete dias, só com título e subtítulo."""

import re
from datetime import timedelta
from pathlib import Path

from .routines import (
    ROOT_NAMES,
    SKIP_DIRS,
    _inside,
    _join_pt,
    _plain,
    _read,
    _title,
    _without_frontmatter,
    fold,
    iter_notes,
)

_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$")


def learned_speech(root, moment):
    items = notes_since(root, moment - timedelta(days=7))
    if not items:
        return "Não há nota criada ou alterada nos últimos sete dias, senhor."
    shown = items[:5]
    bits = []
    for title, headings in shown:
        if headings:
            bits.append(title + ", " + _join_pt(headings))
        else:
            bits.append(title)
    speech = "Nos últimos sete dias, senhor, " + _join_pt(bits) + "."
    extra = len(items) - len(shown)
    if extra:
        speech += f" E mais {extra}."
    return speech


def notes_since(root, cutoff):
    root = Path(root)
    found = {}
    for path in _git_notes(root, cutoff):
        found[path.resolve()] = path
    for path in _mtime_notes(root, cutoff):
        found.setdefault(path.resolve(), path)
    items = []
    for path in found.values():
        text = _read(path)
        title = _title(path, text)
        items.append((title, _headings(text, title)))
    items.sort(key=lambda item: fold(item[0]))
    return items


def _headings(text, title):
    found = []
    folded_title = fold(title)
    for line in _without_frontmatter(text).splitlines():
        match = _HEADING.match(line.strip())
        if not match:
            continue
        heading = _plain(match.group(1))
        if not heading or fold(heading) == folded_title:
            continue
        if heading not in found:
            found.append(heading)
        if len(found) == 3:
            break
    return found


def _mtime_notes(root, cutoff):
    try:
        limit = cutoff.timestamp()
    except (OSError, OverflowError, ValueError):
        return []
    found = []
    for path in iter_notes(root):
        if path.name.casefold() in ROOT_NAMES:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if modified >= limit:
            found.append(path)
    return found


def _git_notes(root, cutoff):
    from . import config
    from .procutil import command_argv, run_text

    git = (config.git_bin() or "").strip() or "git"
    since = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    command = command_argv(
        git,
        "-C",
        str(root),
        "log",
        f"--since={since}",
        "--name-only",
        "--pretty=format:",
        "--",
        "*.md",
    )
    if command is None:
        return []
    result = run_text(command, 20)
    if result.code != 0:
        return []
    found = []
    root = Path(root)
    for line in (result.out or "").splitlines():
        relative = line.strip().replace("\\", "/")
        if not relative.endswith(".md"):
            continue
        parts = [part for part in relative.split("/") if part]
        if not parts or any(part in SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        if parts[-1].casefold() in ROOT_NAMES:
            continue
        path = (root / relative).resolve()
        if _inside(path, root) and path.is_file():
            found.append(path)
    return found
