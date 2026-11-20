"""Prazo e cancelamento dos modos de vários turnos.

cancela e para encerram o modo. nova conversa também. O prazo evita que
uma frase nova vire resposta de um teste ou de uma confirmação antiga.
O carimbo é só horário. Não guarda texto de nota.
"""

import re
from datetime import datetime, timezone

from .routines import fold, normalize_phrase

_DESDE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$"
)
_PARADA = {
    "cancela",
    "cancelar",
    "cancele",
    "cancela isso",
    "cancelar isso",
    "para",
    "parar",
    "pare",
    "chega",
    "encerra",
    "encerrar",
    "pode parar",
    "para por favor",
}
_CONTINUA = {"chat", "review_grade"}
_INICIA = {
    "feynman": "feynman",
    "socratic": "socratic",
    "weekly": "weekly",
    "study": "study",
    "sessao_iniciar": "sessao",
    "connect": "conexao",
    "anki": "anki",
    "destaques": "destaques",
    "atualizar": "atualizar",
    "review": "review",
    "review_book": "review",
    "draft_list": "draft",
    "draft_accept": "draft",
    "draft_discard": "draft",
    "draft_edit": "draft",
    "review_resume": "review",
}
_FALA_CANCELA = {
    "feynman": "Encerrei a explicação, senhor.",
    "socratic": "Encerrei as perguntas, senhor.",
    "weekly": "Encerrei a revisão semanal, senhor.",
    "study": "Encerrei o teste, senhor.",
    "sessao": "Encerrei a sessão de estudo, senhor.",
    "review": "Encerrei a revisão, senhor.",
    "anki": "Tudo bem, senhor. Não exportei os cartões.",
    "destaques": "Tudo bem, senhor. Não importei os destaques.",
    "destaques_cartoes": "Tudo bem, senhor. Não gravei os cartões.",
    "estudo_midia": "Tudo bem, senhor. Não processei a fila de mídia.",
    "estudo_cartoes": "Tudo bem, senhor. Não gravei os cartões.",
    "estudo_ligacoes": "Tudo bem, senhor. Não anotei as ligações.",
    "atualizar": "Tudo bem, senhor. Não atualizei o código.",
    "conexao": "Deixei as ligações como estão, senhor.",
    "fontes_notas": "Tudo bem, senhor. Não enviei as fontes.",
    "draft": "Encerrei a revisão dos rascunhos, senhor.",
    "day": "Tudo bem, senhor. Não gravei.",
    "week": "Tudo bem, senhor. Não gravei.",
    "forget": "Tudo bem, senhor. Continua guardado.",
    "capture": "Tudo bem, senhor. Não gravei.",
    "done": "Tudo bem, senhor. Não marquei nada.",
    "snooze": "Tudo bem, senhor. Deixei o lembrete como está.",
    "cancel": "Tudo bem, senhor. Deixei o lembrete como está.",
}
FALA_PRAZO = (
    "O tempo desse modo acabou, senhor. "
    "Encerrei para não misturar com o próximo pedido."
)


def frase_de_parada(message):
    texto = fold(normalize_phrase(message or ""))
    return texto in _PARADA


def desde_valido(valor):
    texto = str(valor or "").strip()
    if not _DESDE.fullmatch(texto):
        return ""
    return texto


def modo_de(kind):
    return _INICIA.get(kind or "")


def continua_modo(kind):
    return kind in _CONTINUA


def ignora_prazo(pending):
    """A sessão conta o próprio relógio. O recap segue JARVIS_MODO_PRAZO."""
    if not isinstance(pending, dict) or pending.get("kind") != "sessao":
        return False
    return pending.get("phase") in {"estudo", "pausa", "intervalo"}


def fala_cancelar(kind):
    return _FALA_CANCELA.get(kind or "", "Encerrei, senhor.")


def expirado(desde, agora, prazo):
    texto = desde_valido(desde)
    if not texto or agora is None:
        return False
    try:
        inicio = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return False
    momento = agora
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    try:
        segundos = (momento - inicio).total_seconds()
    except (TypeError, ValueError):
        return False
    return segundos >= float(prazo)
