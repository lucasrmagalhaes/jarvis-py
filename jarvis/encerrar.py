"""Encerra painel, descarrega o estado e mata processos externos.

Ctrl+C e a saída da bandeja passam por aqui. O Claude e o ffmpeg
não ficam órfãos.
"""

import atexit

from .procutil import encerrar_filhos
from .trava import sincronizar

_INSTALADO = False
_ARQUIVOS = (
    "state.json",
    "contexto.json",
    "memoria.json",
    "revisao.json",
    "log.jsonl",
    "readwise.json",
)


def instalar():
    global _INSTALADO
    if _INSTALADO:
        return
    _INSTALADO = True
    atexit.register(encerrar_filhos)


def encerrar(brain=None):
    instalar()
    try:
        from .panel import parar

        parar()
    except Exception:
        pass
    if brain is not None:
        memoria = getattr(brain, "memory", None)
        if memoria is not None:
            try:
                memoria._save()
            except Exception:
                pass
    _sincronizar_estado()
    encerrar_filhos()


def _sincronizar_estado():
    try:
        from . import config

        home = config.jarvis_home()
    except Exception:
        return
    for nome in _ARQUIVOS:
        sincronizar(home / nome)
