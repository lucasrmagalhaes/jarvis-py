"""Conversa no terminal, com o mesmo cérebro e sem microfone."""

import sys
import threading

from .brain import Brain, BrainError
from .companion import Companion, _answer
from .log import setup as setup_log

from .comandos import texto_chat

HELP = texto_chat()


def loop(ask, read, write):
    write("Modo texto, sem microfone. /sair encerra.\n")
    while True:
        write("> ")
        try:
            line = read()
        except (EOFError, KeyboardInterrupt):
            write("\n")
            return
        if not line:
            write("\n")
            return
        typed = line.strip()
        if not typed:
            continue
        lowered = typed.lower()
        if lowered in {"/sair", "/exit", "/quit"}:
            write("JARVIS: Encerrando os sistemas. Até logo, senhor.\n")
            return
        if lowered in {"/ajuda", "/help"}:
            write(HELP + "\n")
            continue
        try:
            reply = ask(typed)
        except KeyboardInterrupt:
            write("Consulta cancelada.\n")
            continue
        if not reply:
            reply = "Concluí a tarefa, senhor, mas não há nada a reportar."
        write(f"\nJARVIS: {reply}\n")


def run():
    from .primeiro_uso import preparar_se_preciso

    if not preparar_se_preciso():
        return 1
    setup_log()
    try:
        brain = Brain()
    except BrainError as error:
        print(f"JARVIS: {error}")
        return 1
    print("JARVIS: Sistemas online. Às suas ordens, senhor.")
    companion = Companion(brain, speak=None, lock=threading.RLock())
    companion.start()
    companion.allow_checkins()

    def ask(text):
        with companion.lock:
            return _answer(brain, text)

    def read():
        return sys.stdin.readline()

    def write(text):
        sys.stdout.write(text)
        sys.stdout.flush()

    try:
        loop(ask, read, write)
    finally:
        companion.stop()
    return 0


if __name__ == "__main__":
    sys.exit(run() or 0)
