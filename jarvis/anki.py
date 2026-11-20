"""Exporta cartões públicos para um texto que o Anki importa.

Sem --saida o comando só conta. O arquivo não entra no vault e não é enviado.
"""

import sys

from .andamento import SEM_VAULT, _n, _tema, exportar

USO = (
    "Uso:\n"
    "  python -m jarvis anki exportar\n"
    "  python -m jarvis anki exportar --tema TEXTO\n"
    "  python -m jarvis anki exportar --saida ARQUIVO\n"
    "Sem --saida, só conta os cartões públicos. Nada é gravado.\n"
    "Com --saida, grava frente, verso e etiquetas separados por tabulação.\n"
    "Nota com #sigiloso ou em pasta privada fica de fora.\n"
    "O arquivo não entra no vault e não é enviado."
)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "ajuda"}:
        print(USO)
        return 0
    if args[0] != "exportar":
        print("Não entendi. " + USO)
        return 2
    return _exportar(args[1:])


def _exportar(args):
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m jarvis anki exportar",
        add_help=True,
    )
    parser.add_argument("--tema", default="")
    parser.add_argument("--saida", default="")
    try:
        opcoes = parser.parse_args(args)
    except SystemExit as erro:
        codigo = erro.code
        return 0 if codigo in {0, None} else int(codigo or 2)
    from . import config

    root = config.vault_dir()
    if root is None:
        print(SEM_VAULT)
        return 1
    if _tema(opcoes.tema) is None:
        print("Não exportei. O tema não serve.")
        return 1
    gravar = bool(str(opcoes.saida or "").strip())
    try:
        resultado = exportar(
            root,
            tema=opcoes.tema,
            saida=opcoes.saida,
            gravar=gravar,
        )
    except Exception:
        print("Não consegui exportar os cartões.")
        return 1
    return _mostrar(resultado)


def _mostrar(resultado):
    erro = resultado.get("erro") or ""
    if erro == "vault":
        print(SEM_VAULT)
        return 1
    if erro == "tema":
        print("Não exportei. O tema não serve.")
        return 1
    if erro == "caminho":
        print("Não gravei. O caminho ficou dentro do vault ou não serve.")
        return 1
    if erro:
        print("Não consegui exportar os cartões.")
        return 1
    total = int(resultado.get("total") or 0)
    if resultado.get("gravou"):
        print(
            "Exportei "
            + _n(total, "cartão público", "cartões públicos")
            + " em "
            + str(resultado.get("caminho") or "")
            + ". Colunas: frente, verso, etiquetas."
        )
        return 0
    print(_n(total, "cartão público", "cartões públicos") + ". Nada foi gravado.")
    return 0
