"""Controle remoto pelo Telegram: pausa do dia, limite e botões.

O texto da nota não entra aqui. O botão só devolve uma frase curta,
e essa frase passa pelo mesmo registro dos comandos de voz.
"""

import secrets
import time
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

FALA_SAIR = "Remoto desligado até amanhã, senhor."
LIMITE_TEXTO = "Devagar, senhor. Muitas mensagens neste minuto."
_ZONA = ZoneInfo("America/Sao_Paulo")
_FIXOS = {
    "rev:show": "revela",
    "rev:errei": "errei",
    "rev:dificil": "dificil",
    "rev:bom": "bom",
    "rev:facil": "facil",
    "drf:aceita": "aceita o rascunho",
    "drf:descarta": "descarta o rascunho",
    "prv:on": "modo privado",
    "prv:off": "sai do modo privado",
    "atu:sim": "sim",
    "atu:nao": "nao",
    "anki:sim": "sim",
    "anki:nao": "nao",
    "cx:mapa": "grava o mapa",
    "cx:liga": "liga as notas",
    "cx:nao": "nao",
}
_PODCAST_HOSTS = {
    "podcasts.apple.com",
    "anchor.fm",
    "pca.st",
    "overcast.fm",
    "pocketcasts.com",
    "transistor.fm",
    "buzzsprout.com",
    "podbean.com",
}
_AUDIO = {".mp3", ".m4a", ".ogg", ".wav", ".opus"}


def agora_local():
    return datetime.now(_ZONA)


def desligar_hoje(momento=None):
    dia = _dia(momento)

    def mutate(data):
        data["telegram_off"] = dia

    from .state import update

    update(mutate)
    return FALA_SAIR


def remoto_ligado(momento=None):
    from .state import load

    dia = _dia(momento)
    try:
        marcado = load().get("telegram_off")
    except Exception:
        return False
    return marcado != dia


class Limitador:
    def __init__(self, relogio=None):
        self.relogio = relogio or time.monotonic
        self.selos = []

    def permite(self, limite):
        try:
            teto = int(limite)
        except (TypeError, ValueError):
            teto = 20
        if teto < 1:
            teto = 1
        agora = float(self.relogio())
        self.selos = [item for item in self.selos if agora - item < 60.0]
        if len(self.selos) >= teto:
            return False
        self.selos.append(agora)
        return True


def comando_do_link(url):
    from .midia import id_do_video

    endereco = " ".join(str(url or "").split())
    if not endereco:
        return "", ""
    if id_do_video(endereco):
        return "video", "salva esse vídeo " + endereco
    if _e_podcast(endereco):
        return "podcast", "salva esse podcast " + endereco
    return "artigo", "salva esse artigo " + endereco


def preparar_captura(url):
    tipo, frase = comando_do_link(url)
    nomes = {"video": "vídeo", "artigo": "artigo", "podcast": "podcast"}
    nome = nomes.get(tipo) or "link"
    texto = "Quer que eu salve este " + nome + ", senhor? " + " ".join(str(url or "").split())
    token = secrets.token_hex(4)
    linhas = [[("Salvar", "cap:s:" + token), ("Agora não", "cap:n:" + token)]]
    return texto, linhas, token, frase


def frase_do_botao(dado, capturas):
    texto = str(dado or "")[:64]
    if texto in _FIXOS:
        return _FIXOS[texto]
    if texto.startswith("cap:s:") or texto.startswith("cap:n:"):
        token = texto[6:]
        frase = (capturas or {}).pop(token, None)
        if not frase:
            return ""
        if texto.startswith("cap:n:"):
            return "cancelar-captura"
        return frase
    return ""


def teclado_da_resposta(entrada):
    from .comandos import classificar
    from .privacidade import modo_privado_ativo
    from .review import load_pending

    try:
        kind = classificar(entrada or "").kind
    except Exception:
        kind = ""
    if kind in {"private_on", "private_off"}:
        if modo_privado_ativo():
            return [[("Sair do modo privado", "prv:off")]]
        return [[("Ativar modo privado", "prv:on")]]
    if kind == "atualizar":
        return [[("Sim", "atu:sim"), ("Agora não", "atu:nao")]]
    if kind == "anki":
        return [[("Sim", "anki:sim"), ("Agora não", "anki:nao")]]
    if kind == "connect":
        return [
            [("Grava o mapa", "cx:mapa"), ("Liga as notas", "cx:liga")],
            [("Agora não", "cx:nao")],
        ]
    try:
        pending = load_pending()
    except Exception:
        pending = None
    if not isinstance(pending, dict):
        return []
    if pending.get("kind") == "review":
        if pending.get("phase") == "question":
            return [[("Revelar", "rev:show")]]
        if pending.get("phase") == "answer":
            return [[
                ("Errei", "rev:errei"),
                ("Difícil", "rev:dificil"),
                ("Bom", "rev:bom"),
                ("Fácil", "rev:facil"),
            ]]
    if pending.get("kind") == "draft":
        return [[("Aceitar", "drf:aceita"), ("Descartar", "drf:descarta")]]
    return []


def _dia(momento):
    atual = momento or agora_local()
    if getattr(atual, "tzinfo", None) is None:
        atual = atual.replace(tzinfo=_ZONA)
    return atual.date().isoformat()


def _e_podcast(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in _PODCAST_HOSTS or "podcast" in host:
        return True
    if host == "open.spotify.com" and "/episode" in (parsed.path or ""):
        return True
    suffix = PurePosixPath(parsed.path or "").suffix.lower()
    return suffix in _AUDIO
