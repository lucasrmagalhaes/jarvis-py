"""Revisão espaçada a partir de cartões `pergunta ::: resposta` nas notas.

O vault é só leitura. O agendamento fica em ~/.jarvis/revisao.json.
Intervalos no estilo SM-2 simples: 1 dia, 6 dias e depois o intervalo vezes a facilidade.
"""

import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

from . import config

REVIEW_INTENTS = {
    "review",
    "review_book",
    "review_pause",
    "review_resume",
    "review_grade",
}
PATH_STOP = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "o",
    "a",
    "os",
    "as",
    "livro",
    "livros",
    "sobre",
}
CARD_ID = re.compile(r"^[0-9a-f]{16}$")
_RASCUNHO = re.compile(r"(?i)^\[rascunho\]\s+")


def review_path():
    return config.review_file()


def review_turn(root, intent, now, pending):
    kind = getattr(intent, "kind", "")
    active = isinstance(pending, dict) and pending.get("kind") == "review"
    if not active and kind == "review_pause":
        today = _today(root, now)
        reply, _novo = _handle(root, intent, today, None)
        return ("reply", reply, pending)
    if not active and kind not in REVIEW_INTENTS:
        return None
    if active and kind == "dismiss":
        _write_session(None)
        return ("drop",)
    if active and kind not in REVIEW_INTENTS and kind != "chat":
        _write_session(None)
        return ("drop",)
    if root is not None and not _outside_vault(root):
        return (
            "reply",
            "Não guardei a revisão dentro do vault, senhor.",
            None,
        )
    today = _today(root, now)
    reply, new_pending = _handle(root, intent, today, pending if active else None)
    _write_session(new_pending)
    return ("reply", reply, new_pending)


def load_pending():
    session = load_state().get("session")
    pending = _pending_from_session(session)
    return pending


def scan_cards(root):
    from .catalogo import obter
    from .routines import fold

    found = []
    try:
        catalogo = obter(root)
    except Exception:
        return []
    for nota in catalogo.notas.values():
        if not nota.util:
            continue
        relative = nota.relative
        if not relative or relative.startswith(".") or "/." in f"/{relative}":
            continue
        if not _visivel(root, relative, nota.texto or "", nota.sigilosa):
            continue
        for question, answer in nota.cartoes:
            card = _card(relative, question, answer)
            card["tags"] = list(nota.tags or [])
            found.append(card)
    found.sort(key=lambda card: (card["path"], fold(card["question"]), card["id"]))
    return found


def scan_drafts(root):
    from .routines import _read, _relative_note, fold, iter_notes

    found = []
    root = Path(root)
    for path in iter_notes(root):
        relative = _relative_note(root, path)
        if not relative or relative.startswith(".") or "/." in f"/{relative}":
            continue
        texto = _read(path)
        if not _visivel(root, relative, texto):
            continue
        for line in _visible_lines(texto):
            parsed = parse_draft_line(line)
            if parsed is None:
                continue
            question, answer = parsed
            found.append(_card(relative, question, answer))
    found.sort(key=lambda card: (card["path"], fold(card["question"]), card["id"]))
    return found


def _card(relative, question, answer):
    return {
        "id": card_id(relative, question),
        "path": relative,
        "question": question,
        "answer": answer,
    }


def _card_body(line):
    stripped = " ".join((line or "").split())
    if ":::" not in stripped:
        return ""
    stripped = re.sub(r"^(?:#{1,6}\s+|>\s+)", "", stripped)
    stripped = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", stripped)
    return stripped


def parse_card_line(line, origem=""):
    stripped = _card_body(line)
    if not stripped or _RASCUNHO.match(stripped):
        return None
    if stripped.count(":::") != 1:
        if stripped.count(":::") > 1:
            from .leitura import avisar

            avisar(origem, "cartao")
        return None
    question, answer = stripped.split(":::", 1)
    question = " ".join(question.split())
    answer = " ".join(answer.split())
    if not question or not answer:
        return None
    return question, answer


def parse_draft_line(line, origem=""):
    stripped = _card_body(line)
    if not stripped or not _RASCUNHO.match(stripped):
        return None
    rest = _RASCUNHO.sub("", stripped, count=1)
    if rest.count(":::") != 1:
        if rest.count(":::") > 1:
            from .leitura import avisar

            avisar(origem, "cartao")
        return None
    question, answer = rest.split(":::", 1)
    question = " ".join(question.split())
    answer = " ".join(answer.split())
    if not question or not answer:
        return None
    return question, answer


def card_id(relative, question):
    from .routines import fold

    raw = fold(relative) + "\n" + fold(question)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def path_matches(relative, query):
    from .routines import fold

    tokens = [
        token
        for token in fold(query).split()
        if token not in PATH_STOP and len(token) >= 2
    ]
    if not tokens:
        return False
    hay = fold(relative.replace("\\", "/"))
    return all(token in hay for token in tokens)


def apply_sm2(record, grade, today):
    ease = _ease(record)
    try:
        reps = int(record.get("reps") or 0)
    except (TypeError, ValueError):
        reps = 0
    try:
        interval = int(record.get("interval") or 0)
    except (TypeError, ValueError):
        interval = 0
    try:
        lapses = int(record.get("lapses") or 0)
    except (TypeError, ValueError):
        lapses = 0
    if grade == "acertei":
        quality = 5
        if reps <= 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = max(1, int(round(interval * ease)))
        reps += 1
    elif grade in {"bom", "facil", "dificil"}:
        quality = {"dificil": 3, "bom": 4, "facil": 5}[grade]
        if grade == "dificil":
            if reps <= 0:
                interval = 1
            elif reps == 1:
                interval = 2
            else:
                interval = max(1, int(round(max(interval, 1) * 1.2)))
        elif grade == "facil":
            if reps <= 0:
                interval = 4
            elif reps == 1:
                interval = 10
            else:
                interval = max(1, int(round(interval * ease * 1.3)))
        else:
            if reps <= 0:
                interval = 1
            elif reps == 1:
                interval = 6
            else:
                interval = max(1, int(round(interval * ease)))
        reps += 1
    else:
        quality = 2
        reps = 0
        interval = 1
        lapses += 1
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    ease = round(ease + delta, 2)
    if ease < 1.3:
        ease = 1.3
    due = today + timedelta(days=interval)
    path = _safe_path(record.get("path") or "")
    stored = {
        "interval": interval,
        "ease": ease,
        "reps": reps,
        "lapses": lapses,
        "due": due.isoformat(),
    }
    if path:
        stored["path"] = path
    return stored


def load_state():
    path = review_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        data = {}
    return _normalize(data)


def select_due(cards, state, today, limit, novos=None, prioridade=None, novos_feitos=0):
    if limit <= 0:
        return []
    records = state.get("cards") if isinstance(state.get("cards"), dict) else {}
    regras = tuple(prioridade or ())
    usar_cota = novos is not None or bool(regras)
    ranked = []
    for card in cards:
        record = records.get(card["id"]) if isinstance(records.get(card["id"]), dict) else {}
        due = _due_date(record, today)
        if due > today:
            continue
        fresh = _cartao_novo(record)
        if usar_cota:
            ranked.append(
                (
                    _rank_prioridade(card, regras),
                    1 if fresh else 0,
                    due.isoformat(),
                    card["path"],
                    card["question"],
                    card["id"],
                    fresh,
                    card,
                )
            )
        else:
            ranked.append((due.isoformat(), card["path"], card["question"], card["id"], False, card))
    ranked.sort()
    cota = None
    if novos is not None:
        try:
            cota = max(0, int(novos) - max(0, int(novos_feitos or 0)))
        except (TypeError, ValueError):
            cota = 0
    chosen = []
    novos_usados = 0
    for item in ranked:
        fresh = item[-2]
        card = item[-1]
        if fresh and cota is not None:
            if novos_usados >= cota:
                continue
            novos_usados += 1
        chosen.append(card)
        if len(chosen) >= limit:
            break
    return chosen


def _cartao_novo(record):
    if not isinstance(record, dict) or not record:
        return True
    try:
        reps = int(record.get("reps") or 0)
        lapses = int(record.get("lapses") or 0)
    except (TypeError, ValueError):
        return True
    if reps > 0 or lapses > 0:
        return False
    if str(record.get("due") or "").strip():
        return False
    return True


def _rank_prioridade(card, regras):
    if not regras:
        return 0
    from .routines import fold

    caminho = fold(str(card.get("path") or "").replace("\\", "/")).strip("/")
    tags = {fold(str(tag or "")).lstrip("#") for tag in card.get("tags") or []}
    for index, regra in enumerate(regras):
        token = fold(str(regra or "")).strip().strip("/")
        if not token:
            continue
        if token.startswith("#"):
            if token[1:] in tags:
                return index
            continue
        if caminho == token or caminho.startswith(token + "/"):
            return index
        if ("/" + token + "/") in ("/" + caminho + "/"):
            return index
    return len(regras)


def _handle(root, intent, today, pending):
    kind = intent.kind
    if kind == "review_pause":
        _set_paused(today)
        return (
            "Pausa na revisão, senhor. Diga retoma a revisão para continuar.",
            None,
        )
    if kind == "review_grade" and (pending is None or pending.get("phase") != "answer"):
        if pending is not None and pending.get("phase") == "question":
            return _reveal(root, pending)
        return "Não há revisão em andamento, senhor.", None
    if kind == "review_grade" and pending is not None:
        return _grade(root, pending, intent.query or "", today)
    if kind in {"review", "review_book", "review_resume"}:
        query = ""
        if kind == "review_book":
            query = intent.query or ""
            if not _query_tokens(query):
                return "Sobre qual livro, senhor?", None
        if kind == "review_resume":
            _clear_pause()
        elif _is_paused(today):
            return (
                "A revisão está pausada hoje, senhor. Diga retoma a revisão para continuar.",
                None,
            )
        return _begin(root, today, query)
    if pending is not None and pending.get("phase") == "question":
        return _reveal(root, pending)
    if pending is not None and pending.get("phase") == "answer":
        return (
            "Diga acertei ou errei, senhor. Difícil, bom e fácil também servem.",
            pending,
        )
    return "Não há revisão em andamento, senhor.", None


def _query_tokens(query):
    from .routines import fold

    return [
        token
        for token in fold(query).split()
        if token not in PATH_STOP and len(token) >= 2
    ]


def _begin(root, today, query):
    if root is None:
        return (
            "O vault não está configurado, senhor. Sem ele eu não leio as notas. "
            "Rode python -m jarvis.setup.",
            None,
        )
    cards = scan_cards(root)
    if query:
        matched = [card for card in cards if path_matches(card["path"], query)]
        if not matched:
            return "Não encontrei cartão no caminho desse livro, senhor.", None
    else:
        matched = cards
        if not matched:
            return "Não encontrei cartão no formato pergunta e resposta, senhor.", None
    state = load_state()
    left = _remaining(state, today)
    limit = config.review_limit()
    if left <= 0:
        return f"O limite de hoje é {limit} cartões, senhor.", None
    novos_limite = config.review_new_limit()
    prioridade = config.review_priority()
    feitos_novos = _novos_feitos(state, today)
    due = select_due(
        matched,
        state,
        today,
        left,
        novos=novos_limite,
        prioridade=prioridade,
        novos_feitos=feitos_novos,
    )
    if not due:
        if query:
            return "Não há cartão vencido sobre esse livro, senhor.", None
        if _so_novos_bloqueados(matched, state, today, feitos_novos, novos_limite):
            return "O limite de cartões novos de hoje já foi atingido, senhor.", None
        return "Não há cartão para revisar hoje, senhor.", None
    first = due[0]
    pending = {
        "kind": "review",
        "phase": "question",
        "card_id": first["id"],
        "queue": [card["id"] for card in due[1:]],
        "filter": query[:120],
    }
    total = len(due)
    if total == 1:
        head = "Um cartão nesta revisão, senhor."
    else:
        head = f"São {total} cartões nesta revisão, senhor."
    return f"{head} Pergunta: {_clip(first['question'], 240)}", pending


def _reveal(root, pending):
    card = _find(root, pending.get("card_id"))
    if card is None:
        return _skip_missing(root, pending)
    nxt = dict(pending)
    nxt["phase"] = "answer"
    return (
        f"A resposta é {_clip(card['answer'], 300)}, senhor. Diga acertei ou errei. "
        "Difícil, bom e fácil também servem.",
        nxt,
    )


_ACERTO = {"acertei", "bom", "facil", "dificil"}


def cards_until(cards, state, today, ate):
    """Cartões com vencimento até a data, sem o limite diário."""
    records = state.get("cards") if isinstance(state.get("cards"), dict) else {}
    chosen = []
    for card in cards:
        record = records.get(card["id"]) if isinstance(records.get(card["id"]), dict) else {}
        if _due_date(record, today) <= ate:
            chosen.append(card)
    return chosen


def record_grade(card, outcome, today, novo=False):
    def mutate(data):
        cards = data.setdefault("cards", {})
        current = cards.get(card["id"]) if isinstance(cards.get(card["id"]), dict) else {}
        current = dict(current)
        current["path"] = card["path"]
        cards[card["id"]] = apply_sm2(current, outcome, today)
        _bump_daily(data, today, novo=bool(novo))
        _bump_diario(data, today, outcome)

    update_state(mutate)


def cards_due_line(root, now):
    today = _today(root, now)
    if root is None:
        return "Não há cartão para revisar hoje."
    try:
        count = len(select_due(scan_cards(root), load_state(), today, 100000))
    except Exception:
        return "Não consegui contar os cartões de hoje."
    if count <= 0:
        return "Não há cartão para revisar hoje."
    if count == 1:
        return "Há 1 cartão para revisar hoje."
    limite = config.review_limit()
    if count <= limite:
        return f"Há {count} cartões para revisar hoje."
    novos = config.review_new_limit()
    return (
        f"Há {count} cartões na fila. "
        f"Hoje eu trago até {limite}, com no máximo {novos} novos."
    )


def review_stats(root, today):
    state = load_state()
    due = 0
    if root is not None:
        try:
            due = len(select_due(scan_cards(root), state, today, 100000))
        except Exception:
            due = 0
    daily = state.get("daily") if isinstance(state.get("daily"), dict) else {}
    done = 0
    if daily.get("date") == today.isoformat():
        try:
            done = int(daily.get("count") or 0)
        except (TypeError, ValueError):
            done = 0
    if done < 0:
        done = 0
    return {
        "vencidos": due,
        "feitos_hoje": done,
        "sequencia": streak_length(state.get("days") or [], today),
    }


def streak_length(days, today):
    found = {str(item) for item in days or []}
    if today.isoformat() in found:
        cursor = today
    else:
        cursor = today - timedelta(days=1)
        if cursor.isoformat() not in found:
            return 0
    count = 0
    while cursor.isoformat() in found and count < 400:
        count += 1
        cursor = cursor - timedelta(days=1)
    return count


def _visivel(root, relative, text="", sigilosa=None):
    try:
        from .routines import _expor_nota
    except Exception:
        return True
    try:
        return _expor_nota(root, relative, text, sigilosa=sigilosa)
    except Exception:
        return True


def _grade(root, pending, grade, today):
    notas = {"acertei", "errei", "dificil", "bom", "facil"}
    outcome = grade if grade in notas else "errei"
    card = _find(root, pending.get("card_id"))
    if card is None:
        return _skip_missing(root, pending)
    state = load_state()
    records = state.get("cards") if isinstance(state.get("cards"), dict) else {}
    record = records.get(card["id"]) if isinstance(records.get(card["id"]), dict) else {}
    record_grade(card, outcome, today, novo=_cartao_novo(record))
    if outcome == "acertei":
        lead = "Certo, senhor."
    elif outcome == "facil":
        lead = "Registrei como fácil, senhor."
    elif outcome == "bom":
        lead = "Registrei como bom, senhor."
    elif outcome == "dificil":
        lead = "Registrei como difícil, senhor."
    else:
        lead = "Registrei o erro, senhor. Esse cartão volta amanhã."
    nxt = _next_pending(root, pending)
    if nxt is None:
        return f"{lead} Revisão encerrada, senhor.", None
    question = _find(root, nxt.get("card_id"))
    if question is None:
        return _skip_missing(root, nxt, lead)
    return f"{lead} Pergunta: {_clip(question['question'], 240)}", nxt


def _skip_missing(root, pending, lead=""):
    nxt = _next_pending(root, pending)
    prefix = (lead + " ") if lead else ""
    if nxt is None:
        return f"{prefix}O cartão saiu da nota, senhor. Revisão encerrada.".strip(), None
    question = _find(root, nxt.get("card_id"))
    if question is None:
        return _skip_missing(root, nxt, lead)
    return (
        f"{prefix}O cartão saiu da nota, senhor. Pergunta: {_clip(question['question'], 240)}".strip(),
        nxt,
    )


def _next_pending(root, pending):
    queue = [item for item in (pending.get("queue") or []) if CARD_ID.match(str(item or ""))]
    while queue:
        card_id = queue.pop(0)
        if _find(root, card_id) is not None:
            return {
                "kind": "review",
                "phase": "question",
                "card_id": card_id,
                "queue": queue,
                "filter": str(pending.get("filter") or "")[:120],
            }
    return None


def _find(root, card_id):
    if root is None or not CARD_ID.match(str(card_id or "")):
        return None
    for card in scan_cards(root):
        if card["id"] == card_id:
            return card
    return None


def _remaining(state, today):
    daily = state.get("daily") if isinstance(state.get("daily"), dict) else {}
    count = 0
    if daily.get("date") == today.isoformat():
        try:
            count = int(daily.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
    if count < 0:
        count = 0
    return max(0, config.review_limit() - count)


def _novos_feitos(state, today):
    daily = state.get("daily") if isinstance(state.get("daily"), dict) else {}
    if daily.get("date") != today.isoformat():
        return 0
    try:
        value = int(daily.get("novos") or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _so_novos_bloqueados(cards, state, today, feitos, limite):
    if feitos < limite:
        return False
    records = state.get("cards") if isinstance(state.get("cards"), dict) else {}
    algum = False
    for card in cards:
        record = records.get(card["id"]) if isinstance(records.get(card["id"]), dict) else {}
        due = _due_date(record, today)
        if due > today:
            continue
        algum = True
        if not _cartao_novo(record):
            return False
    return algum


def _bump_daily(state, today, novo=False):
    stamp = today.isoformat()
    daily = state.get("daily") if isinstance(state.get("daily"), dict) else {}
    count = 0
    novos = 0
    if daily.get("date") == stamp:
        try:
            count = int(daily.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        try:
            novos = int(daily.get("novos") or 0)
        except (TypeError, ValueError):
            novos = 0
    if count < 0:
        count = 0
    if novos < 0:
        novos = 0
    if novo:
        novos += 1
    state["daily"] = {"date": stamp, "count": count + 1, "novos": novos}
    days = state.get("days") if isinstance(state.get("days"), list) else []
    if stamp not in days:
        days.append(stamp)
    state["days"] = days[-400:]


def _bump_diario(state, today, outcome):
    """Conta acerto e erro do dia. Não guarda pergunta, resposta nem caminho."""
    stamp = today.isoformat()
    historico = state.get("diario") if isinstance(state.get("diario"), list) else []
    atual = None
    for item in historico:
        if isinstance(item, dict) and str(item.get("data") or "") == stamp:
            atual = item
            break
    if atual is None:
        atual = {"data": stamp, "certos": 0, "erros": 0}
        historico.append(atual)
    if outcome in _ACERTO:
        atual["certos"] = _teto(atual.get("certos")) + 1
    else:
        atual["erros"] = _teto(atual.get("erros")) + 1
    state["diario"] = historico


def _teto(valor):
    try:
        numero = int(valor or 0)
    except (TypeError, ValueError):
        return 0
    if numero < 0:
        return 0
    if numero > 500:
        return 500
    return numero


def _is_paused(today):
    return load_state().get("paused_on") == today.isoformat()


def _set_paused(today):
    def mutate(data):
        data["paused_on"] = today.isoformat()
        session = data.get("session")
        mode = session.get("mode") if isinstance(session, dict) else ""
        if mode not in {"study", "draft"}:
            data["session"] = None

    update_state(mutate)


def _clear_pause():
    def mutate(data):
        data["paused_on"] = ""

    update_state(mutate)


def _write_session(pending):
    session = _session_from_pending(pending)

    def mutate(data):
        data["session"] = session

    update_state(mutate)


def _session_from_pending(pending):
    if not isinstance(pending, dict):
        return None
    kind = pending.get("kind")
    mode = pending.get("mode")
    if mode not in {"review", "study", "draft"}:
        if kind == "study":
            mode = "study"
        elif kind == "draft":
            mode = "draft"
        elif kind in {None, "review"}:
            mode = "review"
        else:
            return None
    if mode == "draft":
        if kind not in {None, "draft"}:
            return None
    elif kind not in {None, "review", "study"}:
        return None
    card_id = str(pending.get("card_id") or "")
    if not CARD_ID.match(card_id):
        return None
    phase = pending.get("phase")
    if mode == "study":
        allowed = {"listen"}
    elif mode == "draft":
        allowed = {"choose"}
    else:
        allowed = {"question", "answer"}
    if phase not in allowed:
        return None
    queue = []
    for item in pending.get("queue") or []:
        text = str(item or "")
        if CARD_ID.match(text) and text not in queue:
            queue.append(text)
    saida = {
        "mode": mode,
        "phase": phase,
        "card_id": card_id,
        "queue": queue[:200],
        "filter": " ".join(str(pending.get("filter") or "").split())[:120],
    }
    from .modos import desde_valido

    desde = desde_valido(pending.get("desde"))
    if desde:
        saida["desde"] = desde
    return saida


def _pending_from_session(session):
    if not isinstance(session, dict):
        return None
    raw_mode = session.get("mode")
    if raw_mode == "draft":
        mode = "draft"
    elif raw_mode == "study":
        mode = "study"
    else:
        mode = "review"
    if mode == "draft":
        kind = "draft"
    elif mode == "study":
        kind = "study"
    else:
        kind = "review"
    pending = {
        "kind": kind,
        "mode": mode,
        "phase": session.get("phase"),
        "card_id": session.get("card_id"),
        "queue": session.get("queue") if isinstance(session.get("queue"), list) else [],
        "filter": session.get("filter") or "",
    }
    from .modos import desde_valido

    desde = desde_valido(session.get("desde"))
    if desde:
        pending["desde"] = desde
    stored = _session_from_pending(pending)
    if stored is None:
        return None
    stored["kind"] = pending["kind"]
    return stored


def _visible_lines(text):
    lines = (text or "").splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                lines = lines[index + 1 :]
                break
    visible = []
    fenced = False
    for line in lines:
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            visible.append(line)
    return visible


def _today(root, now):
    from zoneinfo import ZoneInfo

    from .routines import _aware, load_places

    if root:
        places = load_places(root)
        moment = _aware(now, places)
        return moment.date()
    try:
        zone = ZoneInfo("America/Sao_Paulo")
    except Exception:
        zone = ZoneInfo("UTC")
    if now.tzinfo is None:
        moment = now.replace(tzinfo=zone)
    else:
        moment = now.astimezone(zone)
    return moment.date()


def _due_date(record, today):
    from datetime import date

    raw = str((record or {}).get("due") or "")
    try:
        found = date.fromisoformat(raw)
    except ValueError:
        return today
    return found


def _ease(record):
    try:
        ease = float((record or {}).get("ease") or 2.5)
    except (TypeError, ValueError):
        ease = 2.5
    if ease < 1.3:
        return 1.3
    if ease > 5:
        return 5
    return ease


def _safe_path(value):
    from .paths import caminho_relativo

    text = str(value or "").replace("\\", "/").strip()
    if text.startswith("."):
        return ""
    return caminho_relativo(text, limite=240)


def _clip(text, limit):
    cleaned = " ".join(str(text or "").replace("\u2014", " ").replace("\u2013", " ").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _outside_vault(root):
    path = review_path()
    try:
        resolved = path.resolve()
        root_resolved = Path(root).resolve()
    except OSError:
        return True
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return True
    return False


def _normalize(data):
    raw = data if isinstance(data, dict) else {}
    cards = {}
    incoming = raw.get("cards") if isinstance(raw.get("cards"), dict) else {}
    for key, value in incoming.items():
        if not CARD_ID.match(str(key)) or not isinstance(value, dict):
            continue
        cards[str(key)] = _clean_card(value)
    daily = raw.get("daily") if isinstance(raw.get("daily"), dict) else {}
    try:
        count = int(daily.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count < 0:
        count = 0
    try:
        novos = int(daily.get("novos") or 0)
    except (TypeError, ValueError):
        novos = 0
    if novos < 0:
        novos = 0
    date = str(daily.get("date") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = ""
        count = 0
        novos = 0
    paused = str(raw.get("paused_on") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", paused):
        paused = ""
    days = []
    seen_days = set()
    incoming_days = raw.get("days") if isinstance(raw.get("days"), list) else []
    for item in incoming_days:
        text = str(item or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) and text not in seen_days:
            seen_days.add(text)
            days.append(text)
    return {
        "cards": cards,
        "daily": {"date": date, "count": count, "novos": novos},
        "paused_on": paused,
        "days": days[-400:],
        "diario": _limpar_diario(raw),
        "session": _session_from_pending(_pending_from_session(raw.get("session"))),
    }


def _limpar_diario(raw):
    incoming = raw.get("diario") if isinstance(raw.get("diario"), list) else []
    por_data = {}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        data = str(item.get("data") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
            continue
        certos = _teto(item.get("certos"))
        erros = _teto(item.get("erros"))
        if data in por_data:
            certos = _teto(por_data[data]["certos"] + certos)
            erros = _teto(por_data[data]["erros"] + erros)
        if certos or erros:
            por_data[data] = {"data": data, "certos": certos, "erros": erros}
    ordenado = [por_data[chave] for chave in sorted(por_data)]
    return ordenado[-120:]


def _clean_card(value):
    from datetime import date

    due = _due_date(value, date(2000, 1, 1))
    try:
        interval = int(value.get("interval") or 0)
    except (TypeError, ValueError):
        interval = 0
    if interval < 0:
        interval = 0
    if interval > 36500:
        interval = 36500
    try:
        reps = int(value.get("reps") or 0)
    except (TypeError, ValueError):
        reps = 0
    if reps < 0:
        reps = 0
    try:
        lapses = int(value.get("lapses") or 0)
    except (TypeError, ValueError):
        lapses = 0
    if lapses < 0:
        lapses = 0
    stored = {
        "interval": interval,
        "ease": round(_ease(value), 2),
        "reps": reps,
        "lapses": lapses,
        "due": due.isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value.get("due") or "")) else "",
    }
    if not stored["due"]:
        stored.pop("due")
    path = _safe_path(value.get("path") or "")
    if path:
        stored["path"] = path
    return stored


def update_state(mutator):
    path = review_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    from .trava import TravaOcupada, trava_arquivo

    try:
        with trava_arquivo(
            path.with_suffix(".lock"),
            espera=2,
            mensagem="revisão do Jarvis ocupada",
        ):
            data = load_state()
            mutator(data)
            _save(path, _normalize(data))
    except TravaOcupada as error:
        raise TimeoutError("revisão do Jarvis ocupada") from error


def _save(path, data):
    from .trava import gravar_atomico

    cards = data.get("cards") if isinstance(data, dict) else None
    many = isinstance(cards, dict) and len(cards) > 200
    if many:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    gravar_atomico(path, payload, mode=0o600)
