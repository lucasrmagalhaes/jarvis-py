"""Atualiza o clone do Jarvis. Nunca mexe no vault e nunca força o git."""

import os
import re
from pathlib import Path

from .__version__ import __version__

REQUISITOS = (
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-consult.txt",
    "requirements-bandeja.txt",
    "requirements-wake-deps.txt",
    "requirements-wake.txt",
)
_HEX = re.compile(r"^[0-9a-fA-F]{7,40}$")
_VERSAO = re.compile(r'__version__\s*=\s*"(\d+\.\d+\.\d+)"')
_SENSIVEL = ("token", "password", "senha", "authorization", "bearer", "secret")


class Resultado:
    def __init__(self, ok, fala, detalhe=""):
        self.ok = bool(ok)
        self.fala = fala
        self.detalhe = detalhe or ""


class SaidaGit:
    def __init__(self, code, out="", err=""):
        self.code = code
        self.out = out or ""
        self.err = err or ""


class AtualizarErro(Exception):
    def __init__(self, fala):
        super().__init__(fala)
        self.fala = fala


def preparar():
    """Pergunta antes de puxar. A confirmação fica no turno seguinte."""
    from .ajustes import atualizar_ligado

    if not atualizar_ligado():
        return "A atualização por voz está desligada, senhor.", None
    return (
        "Posso atualizar o código do Jarvis nesta máquina, senhor? "
        "Diga sim para continuar. O vault não entra.",
        {"kind": "atualizar"},
    )


def perguntar():
    fala, _pendente = preparar()
    return fala


def concluir(raiz=None, vault=None, runner=None, instalador=None, fumaca=None):
    """Puxa só o clone do Jarvis, em avanço rápido. Recusa sujeira e conflito."""
    from .ajustes import PROJECT_ROOT, atualizar_ligado, vault_dir

    if not atualizar_ligado():
        return Resultado(
            False,
            "A atualização está desligada, senhor. O vault não foi alterado.",
            "",
        )
    origem = Path(raiz) if raiz is not None else PROJECT_ROOT
    proibidos = [vault, vault_dir()]
    try:
        _recusar_vault(origem, proibidos)
        return _concluir(origem, proibidos, runner, instalador, fumaca)
    except AtualizarErro as erro:
        return Resultado(False, erro.fala, "")


def main(argv=None):
    args = list(argv or [])
    if any(item in {"-h", "--help"} for item in args):
        print(
            "Uso: python -m jarvis atualizar\n"
            "Puxa este repositório com git pull --ff-only. "
            "Não mexe no vault e não usa força."
        )
        return 0
    if args:
        print("Não entendi o argumento. Use: python -m jarvis atualizar")
        return 2
    resultado = concluir()
    print(resultado.fala)
    if resultado.detalhe:
        print(resultado.detalhe)
    return 0 if resultado.ok else 1


def validar(args):
    """Só status, rev-parse, pull --ff-only, diff de hashes e merge-base."""
    if not args:
        raise AtualizarErro("Comando git vazio, senhor. Não atualizei.")
    comando = args[0]
    if comando == "status" and list(args) == ["status", "--porcelain"]:
        return
    if comando == "rev-parse" and list(args) in (
        ["rev-parse", "--show-toplevel"],
        ["rev-parse", "HEAD"],
    ):
        return
    if comando == "pull" and list(args) == ["pull", "--ff-only"]:
        return
    if comando == "diff" and len(args) == 4 and args[1] == "--name-only":
        if _HEX.fullmatch(args[2]) and _HEX.fullmatch(args[3]):
            return
    if (
        comando == "merge-base"
        and len(args) == 4
        and args[1] == "--is-ancestor"
        and _HEX.fullmatch(args[2])
        and _HEX.fullmatch(args[3])
    ):
        return
    for arg in args:
        texto = str(arg)
        if texto in {"-f", "--force", "--force-with-lease", "--force-if-includes"}:
            raise AtualizarErro("Atualização forçada bloqueada, senhor. Não atualizei.")
        if texto.startswith("--force") or texto.startswith("+"):
            raise AtualizarErro("Atualização forçada bloqueada, senhor. Não atualizei.")
    raise AtualizarErro("Comando git bloqueado, senhor. Não atualizei.")


def _concluir(origem, proibidos, runner, instalador, fumaca):
    from .ajustes import atualizar_timeout
    from .trava import TravaOcupada, fila_escrita, gravar_atomico

    tempo = atualizar_timeout()
    topo = _git(origem, ["rev-parse", "--show-toplevel"], tempo, runner, proibidos)
    if topo.code != 0:
        return Resultado(
            False,
            "Este Jarvis não está num clone git, senhor. Não atualizei.",
            _detalhe_git(topo),
        )
    try:
        if Path(_limpar_caminho(topo.out)).resolve() != Path(origem).resolve():
            return Resultado(
                False,
                "O git não aponta para o código do Jarvis, senhor. Não atualizei.",
                "",
            )
    except OSError:
        return Resultado(False, "Não consegui ler o clone do Jarvis, senhor. Não atualizei.", "")
    antiga = _head(origem, tempo, runner, proibidos)
    if not _HEX.fullmatch(antiga):
        return Resultado(False, "Não li a revisão do clone, senhor. Não atualizei.", "")
    sujo = _git(origem, ["status", "--porcelain"], tempo, runner, proibidos)
    if sujo.code != 0:
        return Resultado(False, "Não consegui ler o estado do git, senhor. Não atualizei.", "")
    if sujo.out.strip():
        return Resultado(False, _fala_sujo(sujo.out), "")
    antes = _ler_texto(origem, "CHANGELOG.md")
    try:
        with fila_escrita():
            de_novo = _git(origem, ["status", "--porcelain"], tempo, runner, proibidos)
            if de_novo.code != 0:
                return Resultado(
                    False,
                    "Não consegui ler o estado do git, senhor. Não atualizei.",
                    "",
                )
            if de_novo.out.strip():
                return Resultado(False, _fala_sujo(de_novo.out), "")
            pull = _git(origem, ["pull", "--ff-only"], tempo, runner, proibidos)
            if pull.code != 0:
                return Resultado(False, _fala_pull(pull), _detalhe_git(pull))
            nova = _head(origem, tempo, runner, proibidos)
            if not _HEX.fullmatch(nova):
                return Resultado(
                    False,
                    "Não confirmei a revisão depois do pull, senhor. Não forcei nada.",
                    "",
                )
            if antiga != nova:
                base = _git(
                    origem,
                    ["merge-base", "--is-ancestor", antiga, nova],
                    tempo,
                    runner,
                    proibidos,
                )
                if base.code != 0:
                    return Resultado(
                        False,
                        "O histórico não avançou em linha reta, senhor. "
                        "Não forcei e não mesclei.",
                        "",
                    )
    except TravaOcupada:
        return Resultado(False, "O vault está em uso, senhor. Não atualizei o código.", "")
    mudou = antiga != nova
    pip_ok = True
    nomes = []
    if mudou:
        diff = _git(
            origem,
            ["diff", "--name-only", antiga, nova],
            tempo,
            runner,
            proibidos,
        )
        nomes = _requisitos(origem, diff)
        if nomes:
            pip_ok = _reinstalar(origem, nomes, instalador)
    fumaca_ok, fumaca_texto = (True, "")
    if mudou:
        fumaca_ok, fumaca_texto = _fumaca(origem, fumaca)
    depois = _ler_texto(origem, "CHANGELOG.md") if mudou else antes
    versao = _versao_no_disco(origem) or __version__
    ok = pip_ok and fumaca_ok
    _recibo(proibidos, antiga, nova, versao, ok, gravar_atomico)
    fala = _fala_final(mudou, versao, antes, depois, pip_ok, fumaca_ok, nomes)
    detalhe = _detalhe_final(antes, depois, fumaca_texto, pip_ok, nomes)
    return Resultado(ok, fala, detalhe)


def _head(origem, tempo, runner, proibidos):
    saida = _git(origem, ["rev-parse", "HEAD"], tempo, runner, proibidos)
    if saida.code != 0:
        return ""
    return saida.out.strip()


def _git(cwd, args, timeout, runner, proibidos):
    validar(args)
    _recusar_vault(cwd, proibidos)
    if runner is not None:
        saida = runner(list(args), cwd)
        return SaidaGit(getattr(saida, "code", 1), getattr(saida, "out", ""), getattr(saida, "err", ""))
    from .ajustes import atualizar_timeout, git_bin
    from .procutil import command_argv, run_text

    comando = command_argv(git_bin(), "-C", str(cwd), *args)
    if comando is None:
        raise AtualizarErro("Não encontrei o git, senhor. Não atualizei.")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["GIT_EDITOR"] = "true"
    env["GIT_MERGE_AUTOEDIT"] = "no"
    limite = timeout if timeout is not None else atualizar_timeout()
    resultado = run_text(comando, limite, env=env)
    if resultado.timed_out:
        raise AtualizarErro("O git passou do tempo, senhor. Não forcei nada.")
    if resultado.os_error:
        raise AtualizarErro("Não consegui chamar o git, senhor. Não atualizei.")
    return SaidaGit(resultado.code, resultado.out, resultado.err)


def _recusar_vault(caminho, proibidos):
    for item in proibidos:
        if item is not None and _cruza(caminho, item):
            raise AtualizarErro(
                "O código e o vault estão no mesmo caminho, senhor. Não atualizei."
            )


def _cruza(esquerda, direita):
    return _dentro(esquerda, direita) or _dentro(direita, esquerda)


def _dentro(path, root):
    try:
        alvo = Path(path).resolve()
        base = Path(root).resolve()
    except OSError:
        return False
    if alvo == base:
        return True
    try:
        alvo.relative_to(base)
    except ValueError:
        return False
    return True


def _limpar_caminho(texto):
    return (texto or "").strip().strip('"')


def _fala_sujo(porcelain):
    nomes = []
    for linha in porcelain.splitlines():
        texto = linha[3:].strip() if len(linha) > 3 else linha.strip()
        if " -> " in texto:
            texto = texto.split(" -> ", 1)[1].strip()
        texto = texto.replace("\\", "/").strip().strip('"')
        if not texto or ".." in texto.split("/"):
            continue
        nomes.append(texto)
    if not nomes:
        return "Há alterações locais no código do Jarvis, senhor. Não puxei nada."
    amostra = ", ".join(nomes[:5])
    return (
        "Há alterações locais no código do Jarvis, senhor. Não puxei nada. "
        "Arquivos: " + amostra + "."
    )


def _fala_pull(saida):
    texto = ((saida.err or "") + "\n" + (saida.out or "")).casefold()
    if "fast-forward" in texto or "not possible" in texto or "diverg" in texto:
        return "O remoto não entra em avanço rápido, senhor. Não forcei e não mesclei."
    if "conflict" in texto or "conflit" in texto:
        return "Há conflito no código do Jarvis, senhor. Não mesclei e não forcei."
    if "local changes" in texto or "would be overwritten" in texto:
        return "Há alterações locais no código do Jarvis, senhor. Não puxei nada."
    return "Não consegui atualizar o código, senhor. Não forcei nada."


def _detalhe_git(saida):
    texto = " ".join(((saida.err or "") or (saida.out or "")).split())
    return _sanear(texto)


def _sanear(texto):
    limpo = " ".join((texto or "").split())
    baixo = limpo.casefold()
    if any(marca in baixo for marca in _SENSIVEL):
        return ""
    if "@" in limpo and "://" in limpo:
        return ""
    if len(limpo) > 180:
        return limpo[:180]
    return limpo


def _ler_texto(raiz, nome):
    if nome not in {"CHANGELOG.md"}:
        return ""
    path = (Path(raiz) / nome)
    try:
        alvo = path.resolve()
        if not _dentro(alvo, raiz) or not alvo.is_file():
            return ""
        return alvo.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _versao_no_disco(raiz):
    path = Path(raiz) / "jarvis" / "__version__.py"
    try:
        alvo = path.resolve()
        if not _dentro(alvo, raiz) or not alvo.is_file():
            return ""
        texto = alvo.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    achou = _VERSAO.search(texto)
    if not achou:
        return ""
    return achou.group(1)


def _requisitos(origem, diff):
    if diff.code != 0:
        path = _caminho_requisito(origem, "requirements.txt")
        return ["requirements.txt"] if path is not None else []
    vistos = set()
    for linha in diff.out.splitlines():
        nome = linha.strip().replace("\\", "/")
        if nome in REQUISITOS:
            vistos.add(nome)
    return [nome for nome in REQUISITOS if nome in vistos and _caminho_requisito(origem, nome)]


def _caminho_requisito(origem, nome):
    if nome not in REQUISITOS or "/" in nome or "\\" in nome:
        return None
    path = Path(origem) / nome
    try:
        alvo = path.resolve()
    except OSError:
        return None
    if not _dentro(alvo, origem) or not alvo.is_file():
        return None
    return alvo


def _reinstalar(origem, nomes, instalador):
    from .ajustes import atualizar_timeout

    limite = min(600, max(180, atualizar_timeout()))
    for nome in nomes:
        path = _caminho_requisito(origem, nome)
        if path is None:
            return False
        if instalador is not None:
            codigo = instalador(path)
        else:
            codigo = _pip(path, limite)
        if codigo != 0:
            return False
    return True


def _pip(path, timeout):
    import sys

    from .procutil import command_argv, run_text

    argv = command_argv(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-r",
        str(path),
    )
    if argv is None:
        return 1
    resultado = run_text(argv, timeout)
    if resultado.timed_out or resultado.os_error:
        return 1
    return resultado.code


def _fumaca(origem, fumaca):
    if fumaca is not None:
        codigo, texto = fumaca()
        return codigo == 0, _sanear(texto)
    import sys

    from .ajustes import atualizar_timeout
    from .procutil import command_argv, run_text

    codigo_fonte = (
        "import jarvis\n"
        "from jarvis.comandos import COMANDOS\n"
        "assert jarvis.__version__\n"
        "assert COMANDOS\n"
    )
    argv = command_argv(sys.executable, "-c", codigo_fonte)
    if argv is None:
        return False, ""
    env = os.environ.copy()
    env.pop("JARVIS_VAULT", None)
    env["JARVIS_SKIP_HARDWARE"] = "1"
    env["PYTHONPATH"] = str(origem) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    limite = min(60, max(15, atualizar_timeout()))
    resultado = run_text(argv, limite, env=env, cwd=origem)
    if resultado.timed_out or resultado.os_error or resultado.code != 0:
        return False, _sanear(resultado.err or resultado.out)
    return True, ""


def _recibo(proibidos, antiga, nova, versao, ok, gravar):
    from .ajustes import jarvis_home

    if not _HEX.fullmatch(antiga) or not _HEX.fullmatch(nova):
        return
    if not re.fullmatch(r"\d+\.\d+\.\d+", versao or ""):
        return
    pasta = jarvis_home()
    destino = pasta / "atualizacao.txt"
    for item in proibidos:
        if item is not None and (_cruza(pasta, item) or _dentro(destino, item)):
            return
    texto = (
        "ok=" + ("1" if ok else "0") + "\n"
        "versao=" + versao + "\n"
        "antes=" + antiga + "\n"
        "depois=" + nova + "\n"
    )
    try:
        gravar(destino, texto, mode=0o600)
    except OSError:
        return


def _fala_final(mudou, versao, antes, depois, pip_ok, fumaca_ok, nomes):
    if not mudou:
        return "O Jarvis já está atualizado, senhor. Versão " + __version__ + "."
    extra = _resumo_changelog(antes, depois)
    if not pip_ok:
        return _com_extra(
            "Puxei o código, senhor, mas não reinstalei as dependências.",
            extra,
        )
    if not fumaca_ok:
        return _com_extra(
            "Puxei o código, senhor, mas a checagem rápida falhou.",
            extra,
        )
    if versao == __version__:
        fala = "Atualizei o código do Jarvis, senhor. A versão continua " + versao + "."
    else:
        fala = (
            "Atualizei o código do Jarvis para a versão "
            + versao
            + ", senhor. Abra o Jarvis de novo para usá-la."
        )
    if extra:
        fala += " " + extra
    if nomes:
        fala += " Reinstalei " + ", ".join(nomes) + "."
    return fala + " O vault não foi alterado."


def _com_extra(fala, extra):
    if extra:
        fala += " " + extra
    return fala + " O vault não foi alterado."


def _resumo_changelog(antes, depois):
    if antes == depois:
        return "O changelog não mudou."
    antigas = set(antes.splitlines())
    titulos = []
    for linha in depois.splitlines():
        if linha.startswith("## ") and linha not in antigas:
            titulo = linha[3:].strip()
            if titulo:
                titulos.append(titulo)
    if not titulos:
        novas = [linha for linha in depois.splitlines() if linha not in antigas and linha.strip()]
        if not novas:
            return "O changelog não mudou."
        return "O changelog tem " + str(len(novas)) + " linhas novas."
    if len(titulos) == 1:
        return "O changelog abre em " + titulos[0] + "."
    return "O changelog abre em " + ", ".join(titulos[:4]) + "."


def _detalhe_final(antes, depois, fumaca_texto, pip_ok, nomes):
    linhas = []
    if not pip_ok and nomes:
        linhas.append("Dependências não reinstaladas: " + ", ".join(nomes) + ".")
    if fumaca_texto:
        linhas.append(fumaca_texto)
    antigas = set((antes or "").splitlines())
    novas = []
    for linha in (depois or "").splitlines():
        if linha in antigas:
            continue
        limpa = _sanear(linha)
        if limpa:
            novas.append(limpa)
        if len(novas) >= 30:
            break
    if novas:
        linhas.append("Changelog:")
        linhas.extend(novas)
    return "\n".join(linhas)
