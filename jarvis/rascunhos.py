"""Revisão dos cartões em rascunho antes de entrarem na revisão espaçada.

O cartão fica na nota com a marca [rascunho]. Aceitar tira a marca.
Editar troca a pergunta e a resposta e mantém o rascunho. Descartar apaga a linha.
"""

import re
from pathlib import Path

from .guardas import FALA_BLOQUEIO, GuardError, escrever
from .review import (
    _clip,
    _outside_vault,
    _write_session,
    card_id,
    parse_draft_line,
    scan_drafts,
)

DRAFT_INTENTS = {"draft_list", "draft_accept", "draft_discard", "draft_edit"}
_PROIBIDO = re.compile(
    r"(?i)(git\s+push|enviar\s+e-?mail|envie\s+um\s+e-?mail|sendmessage|"
    r"ignore\s+as\s+instru|dado-nao-confiavel)"
)
_SEM_VAULT = (
    "O vault não está configurado, senhor. Sem ele eu não leio as notas. "
    "Rode python -m jarvis.setup."
)
_LEMBRETE = "Diga aceita, edita ou descarta, senhor."


def eh_turno_rascunho(intent, pending):
    kind = getattr(intent, "kind", "")
    active = isinstance(pending, dict) and pending.get("kind") == "draft"
    if kind in DRAFT_INTENTS:
        return True
    return active and kind == "chat"


def rascunho_altera(intent, pending):
    kind = getattr(intent, "kind", "")
    if kind in {"draft_accept", "draft_discard", "draft_edit"}:
        return True
    if kind != "chat" or not isinstance(pending, dict) or pending.get("kind") != "draft":
        return False
    return atalho_de(getattr(intent, "text", "")) is not None


def atalho_de(text):
    raw = " ".join((text or "").split())
    aceita = re.match(r"(?i)^(?:aceita|aceitar|aceite)(?:\s+(?P<num>\d{1,3}))?\s*$", raw)
    if aceita:
        return ("draft_accept", aceita.group("num") or "", "")
    descarta = re.match(
        r"(?i)^(?:descarta|descartar|descarte)(?:\s+(?P<num>\d{1,3}))?\s*$",
        raw,
    )
    if descarta:
        return ("draft_discard", descarta.group("num") or "", "")
    edita = re.match(r"(?i)^(?:edita|editar|edite)\s+(?P<body>.+)$", raw)
    if edita:
        return ("draft_edit", "", edita.group("body").strip())
    return None


def draft_turn(root, intent, now, pending):
    del now
    kind = getattr(intent, "kind", "")
    active = isinstance(pending, dict) and pending.get("kind") == "draft"
    if not active and kind not in DRAFT_INTENTS:
        return None
    if root is not None and not _outside_vault(root):
        return ("reply", "Não guardei a revisão dentro do vault, senhor.", None)
    if root is None:
        _write_session(None)
        return ("reply", _SEM_VAULT, None)
    numero = getattr(intent, "query", "") or ""
    corpo = getattr(intent, "text", "") or ""
    if active and kind == "chat":
        atalho = atalho_de(corpo)
        if atalho is None:
            return ("reply", _LEMBRETE, pending)
        kind, numero, corpo = atalho
    cards = scan_drafts(root)
    if kind == "draft_list":
        return _listar(cards)
    if not cards:
        _write_session(None)
        return ("reply", "Não há rascunho para revisar, senhor.", None)
    alvo = _escolher(cards, pending if active else None, numero)
    if alvo is False:
        return ("reply", "Não há rascunho com esse número, senhor.", _guardar(cards))
    if alvo is None:
        return ("reply", "Esse rascunho saiu da nota, senhor.", _guardar(cards))
    if kind == "draft_edit":
        return _editar(root, cards, alvo, corpo)
    if kind == "draft_discard":
        return _mudar(root, alvo, "discard", "Descartei o rascunho, senhor.")
    return _mudar(root, alvo, "accept", "Aceitei o rascunho, senhor. Ele entra na revisão.")


def _listar(cards):
    if not cards:
        _write_session(None)
        return ("reply", "Não há rascunho para revisar, senhor.", None)
    pending = _guardar(cards)
    return ("reply", _anunciar(cards), pending)


def _editar(root, cards, alvo, corpo):
    par = _partir(corpo)
    if par is None:
        return (
            "reply",
            "Diga a pergunta, três sinais de dois-pontos e a resposta, senhor.",
            _guardar(cards, alvo["id"]),
        )
    if par == "proibido":
        return (
            "reply",
            "Não guardei esse texto no cartão, senhor.",
            _guardar(cards, alvo["id"]),
        )
    try:
        ok = _alterar(root, alvo["id"], "edit", par)
    except GuardError:
        return ("reply", FALA_BLOQUEIO, _guardar(cards, alvo["id"]))
    if not ok:
        _lista = _listar(scan_drafts(root))
        return ("reply", "Esse rascunho saiu da nota, senhor.", _lista[2])
    novos = scan_drafts(root)
    novo = None
    for card in novos:
        if card["question"] == par[0] and card["answer"] == par[1]:
            novo = card
            break
    pending = _guardar(novos, novo["id"] if novo else None)
    fala = "Atualizei o rascunho, senhor. Ele continua fora da revisão."
    if novo:
        fala += " " + _detalhe(novo)
    return ("reply", fala, pending)


def _mudar(root, alvo, acao, lead):
    try:
        ok = _alterar(root, alvo["id"], acao)
    except GuardError:
        cards = scan_drafts(root)
        return ("reply", FALA_BLOQUEIO, _guardar(cards, alvo["id"]))
    if not ok:
        _lista = _listar(scan_drafts(root))
        return ("reply", "Esse rascunho saiu da nota, senhor.", _lista[2])
    restantes = scan_drafts(root)
    pending = _guardar(restantes)
    if pending is None:
        return ("reply", lead + " Não há mais rascunho.", None)
    return ("reply", lead + " " + _anunciar(restantes), pending)


def _escolher(cards, pending, numero):
    if str(numero or "").isdigit():
        index = int(numero) - 1
        if index < 0 or index >= len(cards):
            return False
        return cards[index]
    if isinstance(pending, dict) and pending.get("card_id"):
        for card in cards:
            if card["id"] == pending.get("card_id"):
                return card
    return cards[0] if cards else None


def _guardar(cards, atual=None):
    if not cards:
        _write_session(None)
        return None
    ids = [card["id"] for card in cards]
    if atual and atual in ids:
        ids.remove(atual)
        ids.insert(0, atual)
    pending = {
        "kind": "draft",
        "mode": "draft",
        "phase": "choose",
        "card_id": ids[0],
        "queue": ids[1:],
        "filter": "",
    }
    _write_session(pending)
    return pending


def _anunciar(cards):
    total = len(cards)
    if total == 1:
        partes = ["Há 1 rascunho, senhor."]
    else:
        partes = ["Há " + str(total) + " rascunhos, senhor."]
    for index, card in enumerate(cards[:5], start=1):
        partes.append(str(index) + ". " + _clip(card["question"], 80))
    if total > 5:
        partes.append("E mais " + str(total - 5) + ".")
    partes.append("Resposta do primeiro: " + _clip(cards[0]["answer"], 160) + ".")
    partes.append("Diga aceita, edita ou descarta.")
    return " ".join(partes)


def _detalhe(card):
    return (
        "Pergunta: "
        + _clip(card["question"], 120)
        + ". Resposta: "
        + _clip(card["answer"], 160)
        + "."
    )


def _partir(corpo):
    from .guardas import texto_secreto

    text = " ".join((corpo or "").split())
    if ":::" not in text:
        return None
    pergunta, resposta = text.split(":::", 1)
    pergunta = " ".join(pergunta.split())[:180]
    resposta = " ".join(resposta.split())[:180]
    if not pergunta or not resposta:
        return None
    if _PROIBIDO.search(pergunta) or _PROIBIDO.search(resposta):
        return "proibido"
    if texto_secreto(pergunta + " " + resposta):
        return "proibido"
    return pergunta, resposta


def _alterar(root, alvo, acao, novo=None):
    found = _localizar(root, alvo)
    if found is None:
        return False
    path, index, lines = found
    if acao == "accept":
        lines[index] = re.sub(r"(?i)\[rascunho\]\s*", "", lines[index], count=1)
    elif acao == "discard":
        del lines[index]
    else:
        lines[index] = _trocar(lines[index], novo[0], novo[1])
    texto = "\n".join(lines).rstrip() + "\n"
    escrever(path, texto, raiz=Path(root))
    return True


def _localizar(root, alvo):
    from .routines import _relative_note, iter_notes

    root = Path(root)
    for path in iter_notes(root):
        relative = _relative_note(root, path)
        if not relative or relative.startswith(".") or "/." in f"/{relative}":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for index, line in _visiveis(lines):
            parsed = parse_draft_line(line)
            if parsed is None:
                continue
            if card_id(relative, parsed[0]) == alvo:
                return path, index, lines
    return None


def _visiveis(lines):
    corpo = list(lines)
    inicio = 0
    if corpo and corpo[0].strip() == "---":
        for index in range(1, len(corpo)):
            if corpo[index].strip() == "---":
                inicio = index + 1
                break
    fenced = False
    for index in range(inicio, len(corpo)):
        if corpo[index].strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield index, corpo[index]


def _trocar(line, pergunta, resposta):
    match = re.search(r"(?i)\[rascunho\]", line)
    if not match:
        return "- [rascunho] " + pergunta + " ::: " + resposta
    return line[: match.end()] + " " + pergunta + " ::: " + resposta
