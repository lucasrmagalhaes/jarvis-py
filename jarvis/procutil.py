"""Argumentos de subprocesso para git, claude e gh.

A lista vai direto para o subprocesso, sem invocar o shell.
No Windows, um .cmd ou .bat passa por cmd /c com o caminho resolvido.
"""

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def resolve_executable(name):
    raw = str(name or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_file():
        return str(candidate)
    return shutil.which(raw)


def command_argv(executable, *args, platform_name=None):
    """Lista pronta para o subprocesso. Não invoque o shell com este retorno."""
    resolved = resolve_executable(executable)
    if not resolved:
        return None
    if resolved.lower().endswith((".cmd", ".bat")):
        cmd = shutil.which("cmd") or "cmd"
        return [cmd, "/c", resolved, *args]
    system = platform_name or os.name
    if system == "nt" and _python_script(resolved):
        return [sys.executable, resolved, *args]
    return [resolved, *args]


class RunText:
    """Saída de um processo de texto. timed_out e os_error separam os erros."""

    def __init__(self, code, out, err, timed_out=False, os_error=False):
        self.code = code
        self.out = out or ""
        self.err = err or ""
        self.timed_out = timed_out
        self.os_error = os_error


def run_text(argv, timeout, env=None, input_text=None, cwd=None):
    """Roda argv sem shell e devolve a saída em texto. Timeout vira código 124."""
    try:
        process = subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=None if cwd is None else str(cwd),
        )
    except subprocess.TimeoutExpired:
        return RunText(124, "", "tempo esgotado", timed_out=True)
    except OSError as error:
        return RunText(1, "", str(error), os_error=True)
    return RunText(process.returncode, process.stdout, process.stderr)


_ATIVOS = set()
_ATIVOS_LOCK = threading.Lock()
_NOMES_EXTERNOS = {
    "ffmpeg",
    "ffmpeg.exe",
    "ffplay",
    "ffplay.exe",
    "ffprobe",
    "ffprobe.exe",
    "claude",
    "claude.exe",
}


def popen_vigiado(args, **kwargs):
    """Abre um processo rastreado. No encerramento ele é morto, com os filhos."""
    if os.name == "nt":
        bandeira = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | bandeira
    else:
        kwargs.setdefault("start_new_session", True)
    processo = subprocess.Popen(args, **kwargs)
    registrar(processo)
    return processo


def registrar(processo):
    if processo is None:
        return
    with _ATIVOS_LOCK:
        _ATIVOS.add(processo)


def esquecer(processo):
    if processo is None:
        return
    with _ATIVOS_LOCK:
        _ATIVOS.discard(processo)


def matar(processo, espera=1):
    if processo is None:
        return
    if processo.poll() is not None:
        esquecer(processo)
        return
    if os.name == "nt":
        _taskkill(processo.pid)
    else:
        _terminar_posix(processo, espera)
    try:
        processo.wait(timeout=espera)
    except subprocess.TimeoutExpired:
        try:
            processo.kill()
        except OSError:
            pass
        try:
            processo.wait(timeout=espera)
        except subprocess.TimeoutExpired:
            pass
    esquecer(processo)


def encerrar_filhos():
    with _ATIVOS_LOCK:
        ativos = list(_ATIVOS)
    for processo in ativos:
        matar(processo)
    encerrar_descendentes()


def encerrar_descendentes(listar=None, matar_pid=None, pid=None):
    """Mata ffmpeg e claude que ficaram filhos deste processo."""
    atual = os.getpid() if pid is None else pid
    ler = listar or listar_filhos
    matar_um = matar_pid or _matar_pid
    try:
        filhos = list(ler(atual))
    except Exception:
        return
    for filho, nome in filhos:
        base = os.path.basename(str(nome or "")).lower()
        if base in _NOMES_EXTERNOS and filho != atual:
            matar_um(filho)


def listar_filhos(pid):
    if Path("/proc").is_dir():
        return _filhos_proc(pid)
    if os.name == "nt":
        return _filhos_windows(pid)
    return _filhos_ps(pid)


def _terminar_posix(processo, espera):
    try:
        grupo = os.getpgid(processo.pid)
    except (OSError, ProcessLookupError):
        grupo = None
    proprio = os.getpgrp()
    if grupo is not None and grupo == processo.pid and grupo != proprio:
        try:
            os.killpg(grupo, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            processo.terminate()
    else:
        try:
            processo.terminate()
        except OSError:
            return
    try:
        processo.wait(timeout=espera)
    except subprocess.TimeoutExpired:
        if grupo is not None and grupo == processo.pid and grupo != proprio:
            try:
                os.killpg(grupo, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                processo.kill()
        else:
            try:
                processo.kill()
            except OSError:
                pass


def _taskkill(pid):
    if not pid or pid == os.getpid():
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _matar_pid(pid):
    if not pid or pid == os.getpid():
        return
    if os.name == "nt":
        _taskkill(pid)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    time.sleep(0.2)
    try:
        os.kill(pid, 0)
    except OSError:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _filhos_proc(pid):
    encontrados = []
    for entrada in Path("/proc").iterdir():
        if not entrada.name.isdigit():
            continue
        try:
            bruto = (entrada / "stat").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fim = bruto.rfind(")")
        inicio = bruto.find("(")
        if fim < 0 or inicio < 0 or fim < inicio:
            continue
        resto = bruto[fim + 2 :].split()
        if len(resto) < 2:
            continue
        try:
            pai = int(resto[1])
            filho = int(entrada.name)
        except ValueError:
            continue
        if pai == pid:
            encontrados.append((filho, bruto[inicio + 1 : fim]))
    return encontrados


def _filhos_ps(pid):
    try:
        resultado = subprocess.run(
            ["ps", "-o", "pid=,ppid=,comm=", "-ax"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    encontrados = []
    for linha in (resultado.stdout or "").splitlines():
        partes = linha.split(None, 2)
        if len(partes) < 3:
            continue
        try:
            filho = int(partes[0])
            pai = int(partes[1])
        except ValueError:
            continue
        if pai == pid:
            encontrados.append((filho, partes[2]))
    return encontrados


def _filhos_windows(pid):
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []
    classe = wintypes.DWORD
    instantaneo = 0x00000002

    class Entrada(ctypes.Structure):
        _fields_ = [
            ("dwSize", classe),
            ("cntUsage", classe),
            ("th32ProcessID", classe),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", classe),
            ("cntThreads", classe),
            ("th32ParentProcessID", classe),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", classe),
            ("szExeFile", ctypes.c_char * 260),
        ]

    nucleo = ctypes.windll.kernel32
    foto = nucleo.CreateToolhelp32Snapshot(instantaneo, 0)
    if foto in (-1, 0xFFFFFFFF):
        return []
    entrada = Entrada()
    entrada.dwSize = ctypes.sizeof(Entrada)
    encontrados = []
    try:
        if not nucleo.Process32First(foto, ctypes.byref(entrada)):
            return []
        while True:
            if int(entrada.th32ParentProcessID) == int(pid):
                nome = entrada.szExeFile.split(b"\0", 1)[0].decode("mbcs", errors="replace")
                encontrados.append((int(entrada.th32ProcessID), nome))
            if not nucleo.Process32Next(foto, ctypes.byref(entrada)):
                break
    finally:
        nucleo.CloseHandle(foto)
    return encontrados


def _python_script(path):
    if path.lower().endswith(".py"):
        return True
    try:
        with open(path, "rb") as handle:
            head = handle.read(160)
    except OSError:
        return False
    if not head.startswith(b"#!"):
        return False
    return b"python" in head.lower()
