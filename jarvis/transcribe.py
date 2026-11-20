"""Transcreve um arquivo de áudio com o Whisper local. Não abre o microfone."""

import threading

from . import config

_model = None
_lock = threading.Lock()


def transcribe_file(path, timeout=None):
    limite = 120 if timeout is None else timeout
    caixa = {}

    def trabalho():
        try:
            caixa["texto"] = _transcrever(path)
        except Exception as error:
            caixa["erro"] = error

    thread = threading.Thread(target=trabalho, name="jarvis-transcricao", daemon=True)
    thread.start()
    thread.join(limite)
    if thread.is_alive():
        from .procutil import encerrar_descendentes

        encerrar_descendentes()
        raise TimeoutError("a transcrição demorou demais e foi cancelada")
    if "erro" in caixa:
        raise caixa["erro"]
    return caixa.get("texto")


def _transcrever(path):
    model = _load()
    segments, _info = model.transcribe(
        str(path),
        language=config.LANGUAGE,
        beam_size=5,
        vad_filter=True,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text or None


def _load():
    global _model
    with _lock:
        if _model is None:
            from .stt import open_transcriber

            _model = open_transcriber()
        return _model
