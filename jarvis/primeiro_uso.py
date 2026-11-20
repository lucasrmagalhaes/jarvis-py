"""Primeiro uso: aponta o vault, confere o git e monta o índice.

python -m jarvis primeiro-uso
"""

import os
import subprocess
import sys
from pathlib import Path

from .envfile import env_path, merge_env, read_env, write_env
from .progresso import barra

TOUR = (
    "bom dia",
    "o que tenho hoje",
    "revisão do dia",
    "o que aprendi esta semana",
    "me testa sobre um tema",
)

_NOMES = {
    "livros": ("livro", "livros", "book", "books"),
    "videos": ("video", "videos", "vídeo", "vídeos"),
    "cursos": ("curso", "cursos", "course", "courses"),
}


def _saida(text=""):
    bruto = "" if text is None else str(text)
    if bruto.startswith("\r"):
        sys.stdout.write(bruto)
        sys.stdout.flush()
        return
    print(bruto)


class Console:
    def __init__(self, input_fn=None, output_fn=None):
        self._input = input_fn or input
        self._output = output_fn or _saida

    def say(self, text=""):
        self._output(text)

    def progress(self, text):
        self._output(text)

    def ask(self, prompt):
        try:
            return self._input(prompt + ": ").strip()
        except EOFError:
            return ""

    def confirm(self, prompt, default=True):
        hint = "S/n" if default else "s/N"
        entered = self.ask(prompt + " (" + hint + ")")
        if entered == "":
            return default
        return entered.casefold() in {"s", "sim", "y", "yes"}


def configuracao_ausente():
    if (os.environ.get("JARVIS_VAULT") or "").strip():
        return False
    return not env_path().is_file()


def preparar_se_preciso():
    """True se o processo deve continuar. False se ainda falta configuração."""

    if not configuracao_ausente():
        return True
    if not _terminal():
        print("Sem configuração ainda. Rode python -m jarvis primeiro-uso.")
        return False
    return main([]) == 0


def fala_atalho():
    return (
        "Para apontar o vault, rode python -m jarvis primeiro-uso. "
        + texto_tour()
    )


def texto_tour():
    linhas = ["Cinco pedidos para experimentar:"]
    for indice, frase in enumerate(TOUR, 1):
        linhas.append(str(indice) + ". " + frase)
    return " ".join(linhas)


def main(argv=None, console=None):
    del argv
    output = console or Console()
    try:
        return _rodar(output)
    except KeyboardInterrupt:
        output.say("")
        output.say("Primeiro uso cancelado.")
        return 130


def _rodar(console):
    console.say("Primeiro uso do JARVIS")
    console.say("")
    console.say("Vou pedir a pasta do vault, conferir se ela é um repositório git")
    console.say("e montar o índice local. Nada disso sai da máquina.")
    console.say("Gmail, Jira e GitHub continuam só leitura. Eu não envio e-mail.")
    pasta = _pedir_pasta(console)
    if pasta is None:
        return 1
    achados = detectar_pastas(pasta)
    _mostrar_pastas(console, achados)
    if not console.confirm("Gravo essa pasta na configuração local?", default=True):
        console.say("Não gravei nada.")
        return 1
    valores = _valores(pasta, achados)
    _gravar(valores)
    for chave, valor in valores.items():
        os.environ[chave] = valor
    console.say("Configuração salva em " + str(env_path()))
    console.say("")
    resumo = construir_indice(pasta, console.progress)
    console.say(
        "Índice pronto: "
        + str(resumo["notas"])
        + " notas em "
        + f"{resumo['segundos']:.1f}s."
    )
    console.say("")
    console.say(texto_tour())
    console.say("Para medir um vault sintético: python -m jarvis.benchmark")
    return 0


def _pedir_pasta(console):
    sugestao = (os.environ.get("JARVIS_VAULT") or "").strip()
    for _ in range(3):
        prompt = "Pasta do vault"
        if sugestao:
            prompt += " [" + sugestao + "]"
        entered = console.ask(prompt)
        bruto = entered or sugestao
        if not bruto:
            console.say("Preciso do caminho da pasta.")
            continue
        pasta = Path(bruto).expanduser()
        if not pasta.is_dir():
            console.say("Essa pasta não existe.")
            continue
        if not eh_repositorio(pasta):
            console.say("Essa pasta não é um repositório git. O vault precisa ser um clone.")
            continue
        return pasta
    console.say("Não consegui validar a pasta. Rode de novo quando o clone estiver pronto.")
    return None


def eh_repositorio(pasta):
    from . import config

    git = config.git_bin() or "git"
    try:
        result = subprocess.run(
            [git, "-C", str(pasta), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and (result.stdout or "").strip() == "true"


def detectar_pastas(root):
    from .routines import SKIP_DIRS, fold

    raiz = Path(root)
    try:
        base = raiz.resolve()
    except OSError:
        return {}
    contagem = _contar_md(base, SKIP_DIRS)
    nomes = {tipo: {fold(nome) for nome in lista} for tipo, lista in _NOMES.items()}
    melhor = {tipo: ("", -1) for tipo in _NOMES}
    for relativa, quantidade in contagem.items():
        if not relativa:
            continue
        nome = fold(Path(relativa).name)
        for tipo, aceitos in nomes.items():
            if nome in aceitos and quantidade > melhor[tipo][1]:
                melhor[tipo] = (relativa, quantidade)
    return {tipo: caminho for tipo, (caminho, qtd) in melhor.items() if qtd >= 0 and caminho}


def _contar_md(base, skip):
    totais = {}

    def visitar(atual):
        try:
            entradas = list(os.scandir(atual))
        except OSError:
            return 0
        arquivos = 0
        for entrada in entradas:
            nome = entrada.name
            if not nome or nome.startswith(".") or nome in skip:
                continue
            try:
                if entrada.is_symlink():
                    continue
                if entrada.is_dir(follow_symlinks=False):
                    arquivos += visitar(Path(entrada.path))
                elif nome.lower().endswith(".md") and entrada.is_file(follow_symlinks=False):
                    arquivos += 1
            except OSError:
                continue
        try:
            relativa = Path(atual).resolve().relative_to(base).as_posix()
        except (OSError, ValueError):
            relativa = ""
        if relativa:
            totais[relativa] = arquivos
        return arquivos

    visitar(base)
    return totais


def _mostrar_pastas(console, achados):
    rotulos = (("livros", "Livros"), ("videos", "Vídeos"), ("cursos", "Cursos"))
    if not achados:
        console.say("Não achei pasta de livros, vídeos ou cursos. Sigo com o padrão.")
        return
    console.say("Pastas encontradas:")
    for chave, rotulo in rotulos:
        if achados.get(chave):
            console.say("  " + rotulo + ": " + achados[chave])


def _valores(pasta, achados):
    valores = {"JARVIS_VAULT": str(pasta)}
    mapa = {
        "livros": "JARVIS_LIVROS_PASTA",
        "videos": "JARVIS_VIDEOS_PASTA",
        "cursos": "JARVIS_CURSOS_PASTA",
    }
    ordem = []
    for chave, nome in mapa.items():
        if achados.get(chave):
            valores[nome] = achados[chave]
            ordem.append(achados[chave])
    if ordem:
        valores["JARVIS_REVISAO_PRIORIDADE"] = ", ".join(ordem)
    return valores


def _gravar(valores):
    destino = env_path()
    merged = merge_env(read_env(destino), valores)
    write_env(destino, merged)


def construir_indice(root, escrever=None):
    import time

    from .catalogo import obter
    from .indice_vetor import NoteIndex, cache_file

    inicio = time.perf_counter()

    def tick(feito, total, segundos):
        if escrever is None:
            return
        escrever("\r" + barra(feito, total, segundos))

    catalogo = obter(root, progresso=tick)
    if escrever is not None:
        escrever("")
    modelo = _modelo()
    refeitas = []
    try:
        refeitas = NoteIndex(root, modelo, cache_file(root, modelo)).sync()
    except Exception:
        refeitas = []
    return {
        "notas": sum(1 for nota in catalogo.notas.values() if nota.util),
        "refeitas": len(refeitas),
        "segundos": time.perf_counter() - inicio,
    }


class HashEmbedder:
    """Vetor local barato, só para o índice existir sem baixar modelo."""

    def embed(self, texts):
        import hashlib

        rows = []
        for text in texts:
            digest = hashlib.sha256((text or "").encode("utf-8", errors="replace")).digest()
            rows.append([byte / 255.0 for byte in digest[:8]])
        return rows


def _modelo():
    try:
        from .consult import default_embedder

        modelo = default_embedder()
    except Exception:
        modelo = None
    if modelo is not None:
        return modelo
    return HashEmbedder()


def _terminal():
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
