"""Leitura tolerante do vault.

Arquivo binário, enorme ou com codificação estranha é pulado.
O log leva o caminho e o motivo, nunca o texto da nota.
"""

import hashlib
import os
import re
from pathlib import Path

MAX_BYTES = 1_000_000
MAX_LINHA = 8000

_AVISOS = set()


def limpar_avisos():
    _AVISOS.clear()


def avisar(relativo, motivo):
    caminho = str(relativo or "nota").replace("\\", "/")
    chave = (caminho, str(motivo or "leitura"))
    if chave in _AVISOS:
        return
    if len(_AVISOS) > 4000:
        _AVISOS.clear()
    _AVISOS.add(chave)
    from .log import LOG

    LOG.warning("ignorado %s motivo=%s", chave[0], chave[1])


def pastas_ignoradas():
    from .ajustes import pastas_ignoradas_raw
    from .privacidade import _relativo

    achadas = []
    for parte in re.split(r"[,;\n]+", pastas_ignoradas_raw()):
        limpa = _relativo(parte)
        if len(limpa) < 3 or limpa in achadas:
            continue
        achadas.append(limpa)
    return tuple(achadas)


def _prefixo_no_vault(base):
    from .ajustes import vault_dir

    vault = vault_dir()
    if vault is None:
        return ""
    try:
        relativo = base.relative_to(vault.resolve()).as_posix()
    except (OSError, ValueError):
        return ""
    return "" if relativo == "." else relativo


def iter_markdown(root, ignorar=True):
    """Notas .md dentro do vault. Não segue link simbólico nem pasta oculta."""

    from .routines import SKIP_DIRS

    raiz = Path(root)
    try:
        base = raiz.resolve()
    except OSError:
        return
    if not base.is_dir():
        return
    ignoradas = pastas_ignoradas() if ignorar else ()
    prefixo = ""
    corte = len(str(base)) + 1
    if ignoradas:
        from .privacidade import _pasta_casa

        prefixo = _prefixo_no_vault(base)
        if prefixo and _pasta_casa(prefixo, ignoradas):
            return
    pendentes = [base]
    while pendentes:
        atual = pendentes.pop()
        try:
            entradas = list(os.scandir(atual))
        except OSError:
            avisar(_relativo(base, atual), "leitura")
            continue
        diretorios = []
        arquivos = []
        for entrada in entradas:
            nome = entrada.name
            if not nome or nome.startswith(".") or nome in SKIP_DIRS:
                continue
            try:
                if entrada.is_symlink():
                    continue
                if entrada.is_dir(follow_symlinks=False):
                    if ignoradas:
                        relativo = entrada.path[corte:].replace(os.sep, "/")
                        if prefixo:
                            relativo = prefixo + "/" + relativo
                        if _pasta_casa(relativo, ignoradas):
                            continue
                    diretorios.append(entrada.path)
                elif nome.lower().endswith(".md") and entrada.is_file(follow_symlinks=False):
                    arquivos.append(entrada.path)
            except OSError:
                avisar(nome, "leitura")
                continue
        diretorios.sort()
        arquivos.sort()
        for caminho in reversed(diretorios):
            pendentes.append(caminho)
        for caminho in arquivos:
            yield Path(caminho)


def ler_nota(path, relativo=""):
    """Texto da nota, ou None se o arquivo deve ser ignorado.

    O segundo item é o sha256 dos bytes lidos. Vazio se nem chegou a ler.
    """

    texto, digest, _sigilosa = ler_nota_marcada(path, relativo)
    return texto, digest


def ler_nota_marcada(path, relativo=""):
    from .routines import MAX_NOTE_CHARS

    alvo = Path(path)
    nome = relativo or alvo.name
    try:
        tamanho = alvo.stat().st_size
    except OSError:
        avisar(nome, "leitura")
        return None, "", False
    if tamanho > MAX_BYTES:
        avisar(nome, "enorme")
        return None, "", False
    try:
        bruto = alvo.read_bytes()
    except OSError:
        avisar(nome, "leitura")
        return None, "", False
    digest = hashlib.sha256(bruto).hexdigest()
    if b"\x00" in bruto[:8192]:
        avisar(nome, "binario")
        return None, digest, False
    try:
        texto = texto_de_bytes(bruto)
    except UnicodeDecodeError:
        avisar(nome, "codificacao")
        return None, digest, False
    sigilosa = _eh_sigilosa(texto)
    if len(texto) > MAX_NOTE_CHARS:
        texto = texto[:MAX_NOTE_CHARS]
    if any(len(linha) > MAX_LINHA for linha in texto.splitlines()):
        texto = "\n".join(linha[:MAX_LINHA] for linha in texto.splitlines())
        avisar(nome, "linha-longa")
    if sigilosa and not _eh_sigilosa(texto):
        texto = _marca_sigilosa() + texto
    _avisar_frontmatter(texto, nome)
    _avisar_link(texto, nome)
    return texto, digest, sigilosa


def _avisar_frontmatter(texto, nome):
    if not (texto or "").startswith("---"):
        return
    fim = texto.find("\n---", 3)
    if fim == -1:
        avisar(nome, "frontmatter")
        return
    for linha in texto[3:fim].splitlines():
        faixa = linha.strip()
        if not faixa or faixa.startswith("#") or faixa.startswith("- "):
            continue
        if linha[:1] in {" ", "\t"}:
            continue
        if ":" not in linha:
            avisar(nome, "frontmatter")
            return


def _avisar_link(texto, nome):
    for linha in (texto or "").splitlines():
        if "[[" in linha and "]]" not in linha:
            avisar(nome, "link")
            return


def texto_de_bytes(bruto):
    """UTF-8 ou UTF-16 com BOM. O BOM do Bloco de Notas não esconde a tag."""
    if bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        texto = bruto.decode("utf-16")
        if texto.startswith("\ufeff"):
            texto = texto[1:]
        return texto
    if bruto.startswith(b"\xef\xbb\xbf"):
        bruto = bruto[3:]
    return bruto.decode("utf-8")


def ler_texto(path):
    return texto_de_bytes(Path(path).read_bytes())


def _eh_sigilosa(texto):
    try:
        from .privacidade import _tem_tag
    except Exception:
        return False
    try:
        return bool(_tem_tag(texto))
    except Exception:
        return False


def _marca_sigilosa():
    try:
        from .privacidade import tag_sigilosa
    except Exception:
        return "#sigiloso\n"
    try:
        tag = tag_sigilosa() or "sigiloso"
    except Exception:
        tag = "sigiloso"
    return "#" + tag + "\n"


def _relativo(base, caminho):
    try:
        return Path(caminho).resolve().relative_to(base).as_posix()
    except (OSError, ValueError):
        return Path(caminho).name
