"""Log local rotativo. Não vai para o vault."""

import logging
from logging.handlers import RotatingFileHandler

LOG = logging.getLogger("jarvis")


class FiltroSigilo(logging.Filter):
    """Tira nota sigilosa do log. No modo privado, não grava nada."""

    def filter(self, record):
        try:
            from .privacidade import modo_privado_ativo, redigir_log
        except Exception:
            return True
        if modo_privado_ativo():
            return False
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redigir_log(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def _garantir_filtro():
    if not any(isinstance(item, FiltroSigilo) for item in LOG.filters):
        LOG.addFilter(FiltroSigilo())


_garantir_filtro()


def setup():
    if LOG.handlers:
        return
    from . import config

    path = config.log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=512_000, backupCount=3, encoding="utf-8"
        )
    except OSError as error:
        print(f"Log local indisponível: {error}")
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.setLevel(logging.INFO)
    LOG.addHandler(handler)
    LOG.propagate = False
    LOG.info("log em %s", path)


def gap_speech(error):
    """Frase curta quando falta vault, chave ou dependência. Vazio se não for esse caso."""
    text = str(error or "").casefold()
    if (
        "vault" in text
        or "jarvis_vault" in text
        or "repositório git" in text
        or "repositorio git" in text
    ):
        return (
            "O vault não está pronto, senhor. "
            "Confira a pasta e rode python -m jarvis.setup."
        )
    if (
        "depend" in text
        or "no module named" in text
        or "modulenotfound" in text
        or "não há áudio" in text
        or "nao ha audio" in text
    ):
        return (
            "Falta uma dependência, senhor. "
            "Rode python -m jarvis.doctor --corrigir, ou use python -m jarvis.chat."
        )
    if any(
        token in text
        for token in (
            "senha de app",
            "jira_token",
            "gmail_app_password",
            "falta a chave",
            "chave de api",
        )
    ):
        return (
            "Falta uma chave, senhor. "
            "Rode python -m jarvis.setup. Eu não leio o valor em voz alta."
        )
    return ""


def failure_speech(error):
    text = str(error or "").casefold()
    if "demorou" in text or "cancelada" in text or "timeout" in text or "tempo esgotado" in text:
        return "A consulta passou do tempo, senhor. Pode tentar de novo."
    if "microfone" in text or "permiss" in text:
        return "Não consegui usar o microfone, senhor. Verifique a permissão e tente de novo."
    gap = gap_speech(error)
    if gap:
        return gap
    if "claude" in text or "execut" in text:
        return "Não consegui falar com o Claude Code, senhor. Confira se ele está instalado e logado."
    if "github" in text or "rede" in text or "conex" in text or "offline" in text or "inacess" in text:
        return "Sem rede no momento, senhor. O que já está neste computador continua aqui."
    return "Encontrei um problema, senhor. Pode tentar de novo."
