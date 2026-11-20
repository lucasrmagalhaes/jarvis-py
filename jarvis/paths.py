"""Caminhos relativos que continuam dentro da pasta no Windows e no Linux."""

import os
import stat
from pathlib import Path


def windows_drive(text):
    """True para C:/nota ou C:\\nota. No Windows isso é caminho absoluto."""
    raw = str(text or "").replace("\\", "/").strip()
    return len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":"


def caminho_relativo(raw, limite=None, exigir_md=False):
    """Caminho relativo saneado, ou vazio se sair da pasta.

    Segmentos "." somem. ".." , absoluto, unidade Windows e nome oculto recusam.
    """
    text = str(raw or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or windows_drive(text):
        return ""
    parts = [part for part in text.split("/") if part and part != "."]
    if not parts or any(part == ".." or part.startswith(".") for part in parts):
        return ""
    joined = "/".join(parts)
    if exigir_md and not joined.lower().endswith(".md"):
        return ""
    if limite:
        return joined[:limite]
    return joined


def relativo_oferta(raw):
    """True se o caminho da oferta pode ser gravado. "a/./b" recusa."""
    text = str(raw or "").replace("\\", "/").strip()
    if windows_drive(text) or not text or text.startswith("/") or text.startswith("."):
        return False
    parts = [part for part in text.split("/") if part]
    if not parts or any(part == ".." or part.startswith(".") for part in parts):
        return False
    return True


def relativo_consulta(raw):
    """True para caminho da consulta. Não normaliza barra invertida nem barra dupla."""
    if windows_drive(raw) or not raw or raw.startswith("/") or raw.startswith("."):
        return False
    parts = str(raw).split("/")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        return False
    return True


def caminho_de_abertura(path, sistema=None):
    """Caminho para open e replace. No Windows, caminho longo ganha prefixo estendido."""
    sistema = os.name if sistema is None else sistema
    texto = os.fspath(path)
    if sistema != "nt":
        return texto
    if texto.startswith("\\\\?\\"):
        return texto
    if len(texto) < 248:
        return texto
    absoluto = os.path.abspath(texto)
    if absoluto.startswith("\\\\?\\"):
        return absoluto
    if absoluto.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absoluto[2:]
    return "\\\\?\\" + absoluto


def abrir_leitura(path):
    """Abre em binário. No Windows, caminho longo usa o prefixo estendido."""
    return open(caminho_de_abertura(path), "rb")


def tamanho_arquivo(path):
    return os.stat(caminho_de_abertura(path)).st_size


def e_arquivo_regular(path):
    try:
        modo = os.stat(caminho_de_abertura(path)).st_mode
    except OSError:
        return False
    return stat.S_ISREG(modo)


def e_atalho(path):
    try:
        modo = os.lstat(caminho_de_abertura(path)).st_mode
    except OSError:
        return False
    return stat.S_ISLNK(modo)


def esta_dentro(path, raiz, oserror=False):
    """True se path resolvido fica dentro de raiz. oserror=True engole OSError."""
    try:
        Path(path).resolve().relative_to(Path(raiz).resolve())
    except ValueError:
        return False
    except OSError:
        if oserror:
            return False
        raise
    return True
