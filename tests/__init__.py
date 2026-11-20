import atexit
import os
import shutil
import tempfile
from pathlib import Path

_PRESERVAR = {"JARVIS_SKIP_HARDWARE"}
_PREFIXOS = ("JARVIS_", "JIRA_", "GMAIL_", "TELEGRAM_", "READWISE_")


def _isolar():
    raiz = Path(tempfile.mkdtemp(prefix="jarvis-suite-")).resolve()
    casa = raiz / "casa"
    (casa / ".jarvis").mkdir(parents=True)
    git_global = raiz / "gitconfig"
    git_global.write_text("", encoding="utf-8")
    for nome in list(os.environ):
        if nome.startswith(_PREFIXOS) and nome not in _PRESERVAR:
            del os.environ[nome]
    os.environ["HOME"] = str(casa)
    os.environ["USERPROFILE"] = str(casa)
    os.environ["JARVIS_HOME"] = str(casa / ".jarvis")
    os.environ["JARVIS_ENV_FILE"] = str(casa / ".jarvis" / ".env")
    os.environ["JARVIS_LOG"] = str(casa / ".jarvis" / "logs" / "jarvis.log")
    os.environ["GIT_CONFIG_GLOBAL"] = str(git_global)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ.pop("XDG_CONFIG_HOME", None)
    atexit.register(shutil.rmtree, str(raiz), True)
    return raiz


RAIZ_DA_SUITE = _isolar()
