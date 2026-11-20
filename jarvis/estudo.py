"""Teste falado sobre um tema, a partir dos cartões já existentes.

A comparação padrão é local. O cérebro só entra se estiver ligado e a
semelhança ficar no meio do caminho. A nota não é alterada.
"""

import re
from difflib import SequenceMatcher

from . import config
from .review import (
    _clip,
    _find,
    _outside_vault,
    _today,
    _write_session,
    record_grade,
    scan_cards,
)

_WORD = re.compile(r"[a-z0-9]+")


def study_turn(root, intent, now, pending, judge=None):
    kind = getattr(intent, "kind", "")
    active = isinstance(pending, dict) and pending.get("kind") == "study"
    if not active and kind != "study":
        return None
    if root is not None and not _outside_vault(root):
        return (
            "reply",
            "Não guardei a revisão dentro do vault, senhor.",
            None,
        )
    if root is None:
        _write_session(None)
        return (
            "reply",
            "O vault não está configurado, senhor. Sem ele eu não leio as notas. "
            "Rode python -m jarvis.setup.",
            None,
        )
    today = _today(root, now)
    if active and kind == "dismiss":
        _write_session(None)
        return ("reply", "Encerrei o teste, senhor.", None)
    if active and kind == "review_pause":
        return None
    if active and kind == "review_grade":
        falado = (getattr(intent, "text", "") or "").strip()
        if not falado:
            falado = getattr(intent, "query", "") or ""
        reply, new_pending = _hear(root, pending, falado, today, judge)
        _write_session(new_pending)
        return ("reply", reply, new_pending)
    if active and kind not in {"chat", "study"}:
        _write_session(None)
        return ("drop",)
    if kind == "study":
        reply, new_pending = _begin(root, intent.query or "", today)
    else:
        reply, new_pending = _hear(root, pending, getattr(intent, "text", "") or "", today, judge)
    _write_session(new_pending)
    return ("reply", reply, new_pending)


def select_cards(root, query, limit, today=None, embedder=None):
    from .busca import in_scope, parse_scope
    from .review import load_state, select_due
    from .routines import fold, hybrid_notes

    cleaned, folder = parse_scope(query or "")
    cards = [card for card in scan_cards(root) if in_scope(card["path"], folder)]
    if not cards:
        return []
    tokens = [token for token in fold(cleaned).split() if len(token) >= 3]
    scores = {}
    if tokens:
        try:
            hits = hybrid_notes(root, cleaned, embedder=embedder, limit=20)
        except Exception:
            hits = []
        order = {}
        for index, hit in enumerate(hits):
            order.setdefault(hit.relative, index)
        tags = _tags_for(root, {card["path"] for card in cards})
        ranked = []
        for card in cards:
            score = 0
            if card["path"] in order:
                score += 10 - min(order[card["path"]], 9)
            hay_tags = tags.get(card["path"], "")
            if any(token in hay_tags for token in tokens):
                score += 6
            hay = fold(card["question"] + " " + card["path"])
            score += sum(1 for token in tokens if token in hay)
            if score:
                scores[card["id"]] = score
                ranked.append(card)
        chosen = ranked
    else:
        chosen = list(cards)
        for card in chosen:
            scores[card["id"]] = 0
    due_ids = set()
    if today is not None and chosen:
        due_ids = {card["id"] for card in select_due(chosen, load_state(), today, 100000)}
    from .routines import fold as fold_text

    chosen.sort(
        key=lambda card: (
            0 if card["id"] in due_ids else 1,
            -scores.get(card["id"], 0),
            card["path"],
            fold_text(card["question"]),
        )
    )
    if limit <= 0:
        return []
    return chosen[:limit]


def compare_answers(expected, spoken, judge=None):
    signals = _signals(expected, spoken)
    local = _is_match(signals)
    if judge is not None and _is_borderline(signals):
        try:
            verdict = judge(expected, spoken)
        except Exception:
            verdict = None
        if verdict is True or verdict is False:
            return verdict
    return local


def _begin(root, query, today):
    theme = " ".join((query or "").split())
    if not theme:
        return "Sobre o que devo testar, senhor?", None
    chosen = select_cards(root, theme, config.study_limit(), today=today, embedder=_embedder())
    if not chosen:
        return f"Não encontrei cartão sobre {theme}, senhor.", None
    first = chosen[0]
    pending = _pending(first["id"], [card["id"] for card in chosen[1:]], theme)
    total = len(chosen)
    if total == 1:
        head = f"Teste sobre {theme}, senhor. Um cartão."
    else:
        head = f"Teste sobre {theme}, senhor. São {total} cartões."
    return f"{head} Pergunta: {_clip(first['question'], 240)}", pending


def _hear(root, pending, spoken, today, judge):
    card = _find(root, (pending or {}).get("card_id"))
    if card is None:
        return _skip(root, pending)
    correct = compare_answers(card["answer"], spoken, judge)
    record_grade(card, "acertei" if correct else "errei", today)
    if correct:
        lead = f"Certo, senhor. A resposta é {_clip(card['answer'], 300)}."
    else:
        lead = f"Não foi dessa vez, senhor. A resposta é {_clip(card['answer'], 300)}."
    nxt = _next(root, pending)
    if nxt is None:
        return f"{lead} Teste encerrado, senhor.", None
    question = _find(root, nxt.get("card_id"))
    if question is None:
        return _skip(root, nxt, lead)
    return f"{lead} Pergunta: {_clip(question['question'], 240)}", nxt


def _skip(root, pending, lead=""):
    nxt = _next(root, pending)
    prefix = (lead + " ") if lead else ""
    if nxt is None:
        return f"{prefix}O cartão saiu da nota, senhor. Teste encerrado.".strip(), None
    question = _find(root, nxt.get("card_id"))
    if question is None:
        return _skip(root, nxt, lead)
    return (
        f"{prefix}O cartão saiu da nota, senhor. Pergunta: {_clip(question['question'], 240)}".strip(),
        nxt,
    )


def _next(root, pending):
    from .review import CARD_ID

    queue = [item for item in ((pending or {}).get("queue") or []) if CARD_ID.match(str(item or ""))]
    while queue:
        card_id = queue.pop(0)
        if _find(root, card_id) is not None:
            return _pending(card_id, queue, (pending or {}).get("filter") or "")
    return None


def _pending(card_id, queue, theme):
    return {
        "kind": "study",
        "mode": "study",
        "phase": "listen",
        "card_id": card_id,
        "queue": list(queue),
        "filter": " ".join(str(theme or "").split())[:120],
    }


def _embedder():
    try:
        from .routines import _search_embedder

        return _search_embedder()
    except Exception:
        return None


def _tags_for(root, relatives):
    from pathlib import Path

    from .routines import _read, fold

    found = {}
    root = Path(root)
    for relative in relatives:
        path = root / relative
        try:
            if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                continue
        except (OSError, ValueError, AttributeError):
            try:
                path.resolve().relative_to(root.resolve())
            except (OSError, ValueError):
                continue
        found[relative] = " ".join(sorted(_front_tags(_read(path), fold)))
    return found


def _front_tags(text, fold):
    if not (text or "").startswith("---"):
        return set()
    end = text.find("\n---", 3)
    if end == -1:
        return set()
    block = text[3:end]
    tags = []
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        inline = re.match(r"(?i)^tags?:\s*(.*)$", line)
        if not inline:
            index += 1
            continue
        value = inline.group(1).strip()
        if value:
            tags.extend(_split_tags(value))
            index += 1
            continue
        index += 1
        while index < len(lines):
            item = re.match(r"^\s*-\s+(.+)$", lines[index])
            if not item:
                break
            tags.append(item.group(1).strip().strip("'\""))
            index += 1
    return {fold(tag.lstrip("#")) for tag in tags if fold(tag.lstrip("#"))}


def _split_tags(value):
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    parts = re.split(r"[,]", text)
    found = []
    for part in parts:
        token = part.strip().strip("'\"")
        if token:
            found.append(token)
    return found


def _words(text):
    from .routines import fold

    return _WORD.findall(fold(text or ""))


def _signals(expected, spoken):
    left = _words(expected)
    right = _words(spoken)
    left_set = set(left)
    right_set = set(right)
    overlap = (len(left_set & right_set) / len(left_set)) if left_set else 0.0
    phrase_l = " ".join(left)
    phrase_r = " ".join(right)
    ratio = SequenceMatcher(None, phrase_l, phrase_r).ratio() if phrase_l and phrase_r else 0.0
    contains = bool(left_set) and left_set <= right_set
    return {
        "left": left,
        "right": right,
        "exact": bool(left) and left == right,
        "contains": contains,
        "overlap": overlap,
        "ratio": ratio,
    }


def _is_match(signals):
    if not signals["left"] or not signals["right"]:
        return False
    if signals["exact"] or signals["contains"]:
        return True
    return signals["overlap"] >= 0.6 or signals["ratio"] >= 0.72


def _is_borderline(signals):
    if not signals["left"] or not signals["right"]:
        return False
    if signals["exact"] or signals["contains"]:
        return False
    if signals["overlap"] >= 0.6 or signals["ratio"] >= 0.72:
        return False
    return signals["overlap"] >= 0.34 or signals["ratio"] >= 0.45
