"""Início no login, pelo terminal.

python -m jarvis instalar-inicio
python -m jarvis remover-inicio

No Windows, instalar-inicio cria a tarefa agendada Jarvis. Se o agendador
recusar, grava um atalho .cmd na pasta Inicializar. remover-inicio desliga os dois.
"""

import sys

from .autostart import for_current_process

USO = (
    "Comandos: instalar-inicio, remover-inicio.\n"
    "instalar-inicio cria a tarefa agendada ou o atalho da pasta Inicializar.\n"
    "remover-inicio desliga os dois.\n"
    "Para conversar: python -m jarvis.main"
)


def executar(argv=None, service=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"-h", "--help", "ajuda"}:
        print(USO)
        return 0
    if not args:
        print(USO)
        return 2
    alvo = service if service is not None else for_current_process()
    comando = args[0]
    if comando == "instalar-inicio":
        result = alvo.enable()
        print(result.message)
        return 0 if result.ok else 1
    if comando == "remover-inicio":
        result = alvo.disable()
        print(result.message)
        return 0 if result.ok else 1
    print(USO)
    return 2
