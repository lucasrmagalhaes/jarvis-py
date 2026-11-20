"""Zip de diagnóstico na pasta do usuário. Sem nota e sem valor de segredo."""

import io
import os
import platform
import re
import zipfile
from datetime import datetime
from pathlib import Path

MEMBROS = (
    "versao.txt",
    "sistema.txt",
    "ajustes.txt",
    "doctor.txt",
    "log.txt",
    "benchmark.txt",
)
_LINHA = re.compile(
    r"^(?P<hora>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:,\d+)?)\s+"
    r"(?P<nivel>DEBUG|INFO|WARNING|ERROR|CRITICAL)\b"
)
_CHAVES_BENCH = (
    "notas",
    "indice_frio_s",
    "refeitas_frio",
    "indice_morno_s",
    "reindice_s",
    "refeitas_um",
    "busca_fria_s",
    "busca_s",
    "cartoes_s",
    "cartoes",
    "revisao_gravar_s",
    "revisao_ler_s",
    "revisao_cards",
    "memoria_mb",
)


def criar(
    pasta=None,
    doctor_fn=None,
    benchmark_fn=None,
    agora=None,
    ambiente=None,
    linhas=None,
):
    """Monta o zip. Devolve código, frase e caminho. Caminho vazio se recusou."""
    from .ajustes import relatorio_linhas, relatorio_pasta, vault_dir
    from .trava import TravaOcupada, fila_escrita, gravar_atomico, trava_arquivo

    ambiente = os.environ if ambiente is None else ambiente
    destino_dir = Path(pasta) if pasta is not None else relatorio_pasta()
    vault = vault_dir()
    if vault is not None and _dentro(destino_dir, vault):
        return 1, "A pasta do relatório está dentro do vault, senhor. Não gravei.", None
    momento = agora or datetime.now()
    nome = "jarvis-relatorio-" + momento.strftime("%Y%m%d-%H%M%S") + ".zip"
    try:
        destino_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 1, "Não consegui criar a pasta do relatório, senhor.", None
    destino = destino_dir / nome
    if destino.exists():
        destino = destino_dir / (
            "jarvis-relatorio-" + momento.strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid()) + ".zip"
        )
    if vault is not None and _dentro(destino, vault):
        return 1, "O relatório cairia dentro do vault, senhor. Não gravei.", None
    limite = relatorio_linhas() if linhas is None else _limite(linhas)
    segredos = _segredos(ambiente)
    pecas = {
        "versao.txt": _limpar(texto_versao(), segredos),
        "sistema.txt": _limpar(texto_sistema(), segredos),
        "ajustes.txt": _limpar(texto_ajustes(ambiente), segredos),
        "doctor.txt": _limpar(_doctor(doctor_fn), segredos),
        "log.txt": _limpar(linhas_sem_conteudo(_ler_log(vault), limite), segredos),
        "benchmark.txt": _limpar(_benchmark(benchmark_fn), segredos),
    }
    bruto = _zip(pecas)
    try:
        _gravar(destino, bruto, fila_escrita, trava_arquivo, gravar_atomico)
    except TravaOcupada:
        return 1, "O relatório está ocupado, senhor. Tente de novo.", None
    except OSError:
        return 1, "Não consegui gravar o relatório, senhor.", None
    return 0, "Gerei o relatório em " + str(destino) + ".", destino


def main(argv=None):
    args = list(argv or [])
    if any(item in {"-h", "--help"} for item in args):
        print(
            "Uso: python -m jarvis relatorio\n"
            "Grava um zip na pasta do usuário com diagnóstico, versão, "
            "nomes de configuração e linhas de log sem texto. "
            "Não inclui nota nem segredo."
        )
        return 0
    if args:
        print("Não entendi o argumento. Use: python -m jarvis relatorio")
        return 2
    codigo, mensagem, _caminho = criar()
    print(mensagem)
    return codigo


def texto_versao():
    from .__version__ import __version__

    return "versao=" + __version__ + "\n"


def texto_sistema():
    return (
        "sistema=" + platform.system() + "\n"
        "release=" + platform.release() + "\n"
        "maquina=" + platform.machine() + "\n"
        "python=" + platform.python_version() + "\n"
        "implementacao=" + platform.python_implementation() + "\n"
    )


def texto_ajustes(ambiente):
    from .ajustes import CATALOGO

    linhas = []
    for item in CATALOGO:
        bruto = ambiente.get(item.nome)
        presente = bruto is not None and str(bruto).strip() != ""
        linhas.append(item.nome + ": " + ("definido" if presente else "ausente"))
    return "\n".join(linhas) + "\n"


def linhas_sem_conteudo(texto, limite):
    """Fica só o horário e o nível. O resto da linha pode ser nota ou segredo."""
    saida = []
    for bruta in (texto or "").splitlines():
        achou = _LINHA.match(bruta.strip())
        if not achou:
            continue
        saida.append(achou.group("hora") + " " + achou.group("nivel"))
    if limite <= 0 or not saida:
        return ""
    final = saida[-limite:]
    return "\n".join(final) + "\n"


def texto_benchmark():
    """Mede um vault sintético minúsculo. O resultado é só número."""
    import shutil
    import tempfile

    from .benchmark import medir
    from .sintetico import gerar_vault

    anterior = os.environ.get("JARVIS_REVISAO")
    base = Path(tempfile.mkdtemp(prefix="jarvis-relatorio-"))
    try:
        raiz = base / "vault"
        gerar_vault(raiz, notas=8, livros=1, videos=1, cursos=1, cartoes=4, longas=0)
        dados = medir(raiz, repeticoes=1)
    except Exception as error:
        return "Benchmark: não concluído (" + type(error).__name__ + ").\n"
    finally:
        if anterior is None:
            os.environ.pop("JARVIS_REVISAO", None)
        else:
            os.environ["JARVIS_REVISAO"] = anterior
        shutil.rmtree(base, ignore_errors=True)
    return formatar_benchmark(dados)


def formatar_benchmark(dados):
    if not isinstance(dados, dict):
        return "Benchmark: não concluído.\n"
    linhas = []
    for chave in _CHAVES_BENCH:
        linhas.append(chave + "=" + _numero(dados.get(chave)))
    return "\n".join(linhas) + "\n"


def _numero(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return "0"
    if isinstance(valor, float):
        return f"{valor:.3f}"
    return str(valor)


def _doctor(doctor_fn):
    if doctor_fn is not None:
        try:
            return str(doctor_fn() or "")
        except Exception as error:
            return "Diagnóstico: não concluído (" + type(error).__name__ + ").\n"
    from contextlib import redirect_stdout

    from . import doctor

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        try:
            doctor.run()
        except Exception as error:
            print("Diagnóstico: não concluído (" + type(error).__name__ + ").")
    texto = buffer.getvalue()
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return texto


def _benchmark(benchmark_fn):
    if benchmark_fn is None:
        return texto_benchmark()
    try:
        return str(benchmark_fn() or "")
    except Exception as error:
        return "Benchmark: não concluído (" + type(error).__name__ + ").\n"


def _ler_log(vault):
    from .ajustes import log_path

    path = log_path()
    if vault is not None and _dentro(path, vault):
        return ""
    try:
        tamanho = path.stat().st_size
    except OSError:
        return ""
    try:
        with path.open("rb") as arquivo:
            if tamanho > 65536:
                arquivo.seek(tamanho - 65536)
            bruto = arquivo.read()
    except OSError:
        return ""
    return bruto.decode("utf-8", errors="replace")


def _segredos(ambiente):
    from .ajustes import CATALOGO

    achados = []
    for item in CATALOGO:
        if not item.segredo:
            continue
        valor = str(ambiente.get(item.nome) or "").strip()
        if len(valor) >= 8:
            achados.append(valor)
    achados.sort(key=len, reverse=True)
    return achados


def _limpar(texto, segredos):
    limpo = texto or ""
    for segredo in segredos:
        limpo = limpo.replace(segredo, "[definido]")
    saida = []
    for linha in limpo.splitlines():
        baixo = linha.casefold()
        if "#sigiloso" in baixo or "<dado-nao-confiavel" in baixo:
            saida.append("[linha sem conteudo]")
        else:
            saida.append(linha)
    if not saida:
        return ""
    return "\n".join(saida) + "\n"


def _limite(valor):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return 40
    if numero < 0:
        return 0
    if numero > 200:
        return 200
    return numero


def _zip(pecas):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as arquivo:
        for nome in MEMBROS:
            arquivo.writestr(nome, pecas.get(nome) or "")
    return buffer.getvalue()


def _gravar(destino, dados, fila, trava, gravar):
    from .trava import TravaOcupada

    try:
        with fila():
            _gravar_com_trava(destino, dados, trava, gravar)
    except TravaOcupada:
        _gravar_com_trava(destino, dados, trava, gravar)


def _gravar_com_trava(destino, dados, trava, gravar):
    destino.parent.mkdir(parents=True, exist_ok=True)
    with trava(destino.with_name(destino.name + ".lock"), mensagem="relatório ocupado"):
        gravar(destino, dados, mode=0o600)


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
