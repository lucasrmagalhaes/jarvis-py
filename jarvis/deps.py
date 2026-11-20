"""Pacotes que o Jarvis precisa para ouvir, acordar e falar.

A palavra de ativação fica fora do lote principal. No Linux, o openwakeword 0.6
pede tflite-runtime, e esse pacote não tem wheel a partir do Python 3.12. Se ele
entrar no mesmo pip, sounddevice, edge-tts e soundfile também deixam de instalar.
O modelo sobe com inference_framework=onnx.
"""

import platform
import sys
from pathlib import Path

REQUIRED = {
    "numpy": "numpy",
    "sounddevice": "sounddevice",
    "faster_whisper": "faster-whisper",
    "onnxruntime": "onnxruntime",
}
OPTIONAL = {"edge_tts": "edge-tts", "soundfile": "soundfile"}

WAKE_PACKAGE = "openwakeword>=0.6"
WAKE_REQUIREMENTS = "requirements-wake.txt"
WAKE_DEPS_REQUIREMENTS = "requirements-wake-deps.txt"

_MODULES = {
    "faster-whisper": "faster_whisper",
    "edge-tts": "edge_tts",
    "scikit-learn": "sklearn",
}


def importable(module):
    try:
        __import__(module)
    except (ImportError, OSError):
        return False
    return True


def missing_packages(mapping):
    missing = []
    for module, package in mapping.items():
        if not importable(module):
            missing.append(package)
    return missing


def package_name(package):
    name = str(package).split("[", 1)[0].strip()
    for separator in ("===", "==", "!=", "<=", ">=", "~=", "<", ">"):
        name = name.split(separator, 1)[0]
    return name.strip()


def is_wake_package(package):
    return package_name(package) == "openwakeword"


def package_module(package):
    name = package_name(package)
    return _MODULES.get(name, name.replace("-", "_"))


def tflite_unavailable(system=None, version=None):
    """tflite-runtime não publica wheel no Linux para Python 3.12 ou mais novo."""
    host = platform.system() if system is None else system
    current = sys.version_info if version is None else version
    return host == "Linux" and tuple(current[:2]) >= (3, 12)


def wakeword_usable():
    """O pacote importa e a classe Model aceita o backend ONNX."""
    try:
        from openwakeword.model import Model
    except Exception:
        return False
    try:
        import inspect

        source = inspect.getsource(Model)
    except (OSError, TypeError):
        source = ""
    if "inference_framework" in source:
        return True
    return _version_at_least(_package_version("openwakeword"), (0, 6))


def package_ready(package):
    if is_wake_package(package):
        return wakeword_usable()
    return importable(package_module(package))


def wakeword_hint():
    alternative = "Sem a palavra de ativação, use o modo texto: python -m jarvis.chat."
    if tflite_unavailable():
        return (
            "O tflite-runtime não tem wheel para este Python no Linux. "
            "A palavra de ativação usa o backend ONNX e não bloqueia o resto. "
            + alternative
        )
    return alternative


def requirements_without_wake(text):
    """Tira openwakeword e tflite de um requirements, preservando o resto."""
    kept = []
    for line in text.splitlines():
        lowered = line.lower()
        if "openwakeword" in lowered or "tflite" in lowered:
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    return (body + "\n") if body else ""


def core_pip_args(python, root):
    return [python, "-m", "pip", "install", "-r", str(Path(root) / "requirements.txt")]


def wake_dep_pip_args(python, root):
    return [
        python,
        "-m",
        "pip",
        "install",
        "-r",
        str(Path(root) / WAKE_DEPS_REQUIREMENTS),
    ]


def wake_pip_args(python, root):
    return [
        python,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "-r",
        str(Path(root) / WAKE_REQUIREMENTS),
    ]


def pip_commands(packages, python, root):
    """Um comando por grupo. A palavra de ativação não divide o pip com o resto."""
    commands = []
    rest = [package for package in packages if not is_wake_package(package)]
    wake = [package for package in packages if is_wake_package(package)]
    if rest:
        commands.append([python, "-m", "pip", "install", *rest])
    if wake:
        commands.append(wake_dep_pip_args(python, root))
        commands.append(wake_pip_args(python, root))
    return commands


def _package_version(name):
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return ""


def _version_at_least(raw, minimum):
    numbers = []
    for piece in str(raw).split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        if digits == "":
            break
        numbers.append(int(digits))
    if len(numbers) < len(minimum):
        return False
    return tuple(numbers[: len(minimum)]) >= tuple(minimum)
