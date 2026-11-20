"""Nota de índice já existente no vault, usada só como sinal extra da busca.

Se o arquivo não estiver lá, a busca segue igual. A pasta .obsidian não entra.
"""

import re
from pathlib import Path

from .routines import _read, fold

_WIKI = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]+)?(?:\|([^\[\]]+))?\]\]")
_MD = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_TICK = re.compile(r"`([^`]+)`")


def boosted_docs(root, docs, query):
    path = index_file(root)
    if path is None or not path.is_file():
        return []
    tokens = _tokens(query)
    if not tokens:
        return []
    entries = parse_index(_read(path))
    if not entries:
        return []
    by_key = {}
    for doc in docs:
        for key in _keys(doc):
            by_key.setdefault(key, doc)
    ordered = []
    seen = set()
    for entry in entries:
        if not any(token in entry["blob"] for token in tokens):
            continue
        doc = by_key.get(fold(entry["target"]))
        if doc is None:
            doc = by_key.get(fold(Path(entry["target"]).name))
        if doc is None or doc[2] in seen:
            continue
        seen.add(doc[2])
        ordered.append(doc)
    return ordered


def index_file(root):
    from . import config

    raw = config.index_relative()
    if not raw:
        return None
    root = Path(root).resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
        relative = resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    parts = relative.parts
    if not parts or any(part.startswith(".") or part in {".obsidian", ".."} for part in parts):
        return None
    if resolved.suffix.lower() != ".md":
        return None
    return resolved


def parse_index(text):
    entries = []
    topic = ""
    for line in (text or "").splitlines():
        heading = re.match(r"^#{1,6}\s+(.+)$", line.strip())
        if heading:
            topic = heading.group(1).strip()
            continue
        found = []
        for match in _WIKI.finditer(line):
            target = match.group(1).strip()
            label = (match.group(2) or target).strip()
            found.append((target, label))
        for match in _MD.finditer(line):
            target = match.group(2).strip()
            if target.lower().endswith(".md"):
                found.append((target, match.group(1).strip()))
        for match in _TICK.finditer(line):
            target = match.group(1).strip()
            if target.lower().endswith(".md"):
                found.append((target, Path(target).stem))
        blob = fold(topic + " " + line)
        for target, label in found:
            cleaned = target.replace("\\", "/").strip().lstrip("/")
            if cleaned.lower().endswith(".md"):
                cleaned = cleaned[:-3]
            if not cleaned or cleaned.startswith(".") or ".obsidian" in cleaned.split("/"):
                continue
            if ".." in cleaned.split("/"):
                continue
            entries.append(
                {
                    "target": cleaned,
                    "label": label,
                    "blob": fold(blob + " " + label + " " + cleaned),
                }
            )
    return entries


def _tokens(query):
    raw = [token for token in fold(query or "").split() if len(token) >= 2]
    useful = [token for token in raw if len(token) >= 3]
    return useful or raw


def _keys(doc):
    relative = doc[2]
    stem = relative[:-3] if relative.lower().endswith(".md") else relative
    keys = {
        fold(stem),
        fold(Path(stem).name),
        fold(relative),
        fold(doc[3]),
    }
    return {key for key in keys if key}
