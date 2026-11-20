"""Estado local em ~/.jarvis. Não vai para o vault e não guarda segredo."""

import json

from . import config
from .trava import TravaOcupada, gravar_atomico, trava_arquivo


def state_path():
    return config.state_file()


def load():
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def update(mutator):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with trava_arquivo(
            path.with_suffix(".lock"),
            espera=2,
            mensagem="estado do Jarvis ocupado",
        ):
            data = load()
            mutator(data)
            _save(path, data)
            return data
    except TravaOcupada as error:
        raise TimeoutError("estado do Jarvis ocupado") from error


def _save(path, data):
    gravar_atomico(
        path,
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        mode=0o600,
    )
