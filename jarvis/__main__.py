"""Atalho de linha de comando: python -m jarvis doctor."""

import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"--versao", "versao"}:
        from .__version__ import __version__

        print(__version__)
        return 0
    if not args:
        from .primeiro_uso import configuracao_ausente, preparar_se_preciso

        if configuracao_ausente():
            if not preparar_se_preciso():
                return 1
            return 0
    if not args or args[0] in {"-h", "--help", "ajuda"}:
        print(
            "Uso:\n"
            "  python -m jarvis --versao\n"
            "  python -m jarvis doctor\n"
            "  python -m jarvis doctor --corrigir\n"
            "  python -m jarvis primeiro-uso\n"
            "  python -m jarvis atualizar\n"
            "  python -m jarvis relatorio\n"
            "  python -m jarvis anki exportar [--tema TEXTO] [--saida ARQUIVO]\n"
            "  python -m jarvis destaques kindle ARQUIVO [--cartoes]\n"
            "  python -m jarvis destaques pdf ARQUIVO [--cartoes]\n"
            "  python -m jarvis destaques koreader ARQUIVO [--cartoes]\n"
            "  python -m jarvis video URL [--cartoes] [--ligacoes]\n"
            "  python -m jarvis audio ARQUIVO [--cartoes] [--ligacoes]\n"
            "  python -m jarvis midia [--confirmar] [--cartoes] [--ligacoes]\n"
            "  python -m jarvis.benchmark\n"
            "  python -m jarvis instalar-inicio\n"
            "  python -m jarvis remover-inicio\n"
        )
        return 0
    if args[0] in {"primeiro-uso", "primeiro_uso"}:
        from .primeiro_uso import main as primeiro_main

        return primeiro_main(args[1:])
    if args[0] == "doctor":
        from .doctor import main as doctor_main

        return doctor_main(args[1:])
    if args[0] == "atualizar":
        from .atualizar import main as atualizar_main

        return atualizar_main(args[1:])
    if args[0] == "relatorio":
        from .relatorio import main as relatorio_main

        return relatorio_main(args[1:])
    if args[0] == "anki":
        from .anki import main as anki_main

        return anki_main(args[1:])
    if args[0] == "destaques":
        from .destaques import main as destaques_main

        return destaques_main(args[1:])
    if args[0] == "video":
        from .estudo_midia import main_video

        return main_video(args[1:])
    if args[0] == "audio":
        from .estudo_midia import main_audio

        return main_audio(args[1:])
    if args[0] == "midia":
        from .estudo_midia import main_fila

        return main_fila(args[1:])
    if args[0] in {"instalar-inicio", "remover-inicio"}:
        from .inicio import executar

        return executar(args)
    print(
        "Não entendi o comando. Use: python -m jarvis --versao, doctor, "
        "atualizar, relatorio, anki exportar, destaques, video, audio, midia, primeiro-uso, "
        "instalar-inicio ou remover-inicio."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
