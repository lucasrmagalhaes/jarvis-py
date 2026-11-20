"""Trava de arquivo e gravação atômica, no Windows e no Linux.

A trava nasce com criação exclusiva e guarda o pid. Processo vivo
não perde a trava por idade. Processo morto deixa a trava livre.
A gravação escreve um temporário no mesmo diretório e troca com
os.replace, que no Windows substitui o destino sem apagar antes.
"""

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_LOCAL = threading.local()
_PAUSA = 0.02


class TravaOcupada(TimeoutError):
    pass


def processo_vivo(pid):
    try:
        numero = int(pid)
    except (TypeError, ValueError):
        return False
    if numero <= 0:
        return False
    if os.name == "nt":
        return _vivo_windows(numero)
    try:
        os.kill(numero, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def trava_arquivo(path, espera=5, idade_vazia=5, mensagem="arquivo ocupado"):
    return _Trava(Path(path), espera, idade_vazia, mensagem)


def caminho_fila():
    from . import config

    return config.jarvis_home() / "vault-escrita.lock"


def espera_fila():
    try:
        from .ajustes import vault_git_timeout

        return max(5, int(vault_git_timeout()) + 15)
    except (TypeError, ValueError):
        return 135


@contextmanager
def fila_escrita():
    """Uma fila só para git e escrita de nota. Não se cruzam."""
    with trava_arquivo(caminho_fila(), espera=espera_fila(), mensagem="vault ocupado"):
        yield


def gravar_atomico(path, dados, mode=None):
    """Grava no mesmo diretório e troca o arquivo. Não deixa conteúdo pela metade."""
    from .paths import caminho_de_abertura

    alvo = Path(path)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(dados, str):
        bruto = dados.encode("utf-8")
    else:
        bruto = bytes(dados)
    abertura = 0o666 if mode is None else mode
    nome = ".{0}.{1}.{2}.tmp".format(
        alvo.name,
        os.getpid(),
        threading.get_ident(),
    )
    temporario = alvo.parent / nome
    temporario_txt = caminho_de_abertura(temporario)
    alvo_txt = caminho_de_abertura(alvo)
    descritor = os.open(temporario_txt, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, abertura)
    try:
        vista = memoryview(bruto)
        while vista:
            escrito = os.write(descritor, vista)
            if escrito <= 0:
                raise OSError("gravacao interrompida")
            vista = vista[escrito:]
        os.fsync(descritor)
    except Exception:
        os.close(descritor)
        try:
            temporario.unlink()
        except OSError:
            pass
        raise
    os.close(descritor)
    ultimo = None
    for _tentativa in range(8):
        try:
            os.replace(temporario_txt, alvo_txt)
            ultimo = None
            break
        except PermissionError as erro:
            ultimo = erro
            time.sleep(0.05)
    if ultimo is not None:
        try:
            temporario.unlink()
        except OSError:
            pass
        raise ultimo
    if mode is not None:
        try:
            os.chmod(alvo, mode)
        except OSError:
            pass


def sincronizar(path):
    try:
        descritor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descritor)
    except OSError:
        pass
    finally:
        os.close(descritor)


class _Trava:
    def __init__(self, path, espera, idade_vazia, mensagem):
        self.path = path
        self.espera = espera
        self.idade_vazia = idade_vazia
        self.mensagem = mensagem
        self._chave = str(path)

    def __enter__(self):
        estado = _estado()
        item = estado.get(self._chave)
        if item is not None:
            item["n"] += 1
            return self
        _adquirir(self.path, self.espera, self.idade_vazia, self.mensagem)
        estado[self._chave] = {"n": 1}
        return self

    def __exit__(self, exc_type, exc, tb):
        estado = _estado()
        item = estado.get(self._chave)
        if item is None:
            return False
        item["n"] -= 1
        if item["n"] <= 0:
            estado.pop(self._chave, None)
            _soltar(self.path)
        return False


def _estado():
    estado = getattr(_LOCAL, "estado", None)
    if estado is None:
        estado = {}
        _LOCAL.estado = estado
    return estado


def _adquirir(path, espera, idade_vazia, mensagem):
    path.parent.mkdir(parents=True, exist_ok=True)
    limite = time.monotonic() + espera
    while True:
        try:
            descritor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _morta(path, idade_vazia):
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= limite:
                raise TravaOcupada(mensagem)
            time.sleep(_PAUSA)
            continue
        try:
            os.write(descritor, str(os.getpid()).encode("ascii"))
        finally:
            os.close(descritor)
        return


def _soltar(path):
    try:
        path.unlink()
    except OSError:
        pass


def _morta(path, idade_vazia):
    try:
        bruto = path.read_text(encoding="ascii", errors="replace").strip()
        pid = int(bruto)
    except (OSError, ValueError):
        try:
            idade = time.time() - path.stat().st_mtime
        except OSError:
            return False
        return idade > idade_vazia
    if processo_vivo(pid):
        return False
    return True


def _vivo_windows(pid):
    import ctypes

    acesso = 0x1000
    nucleo = ctypes.windll.kernel32
    handle = nucleo.OpenProcess(acesso, False, pid)
    if not handle:
        return False
    nucleo.CloseHandle(handle)
    return True
