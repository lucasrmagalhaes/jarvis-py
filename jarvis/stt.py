"""Escolhe o backend de transcrição e o tamanho do modelo.

JARVIS_STT=faster-whisper prefere o faster-whisper e, se ele não abrir,
usa o Whisper clássico. JARVIS_STT=whisper faz o inverso. Sem a variável,
o faster-whisper continua sendo o caminho atual.
"""

from . import config


def stt_preference():
    return config.stt_backend()


def choose_stt(preference, faster_ok, whisper_ok):
    """Qual backend fica ativo. Vazio se nenhum estiver disponível."""
    if preference == "whisper":
        if whisper_ok:
            return "whisper"
        if faster_ok:
            return "faster-whisper"
        return ""
    if faster_ok:
        return "faster-whisper"
    if whisper_ok:
        return "whisper"
    return ""


def doctor_status(preference, model, faster_ok, whisper_ok):
    chosen = choose_stt(preference, faster_ok, whisper_ok)
    if not chosen:
        return (
            "warn",
            f"nenhum backend instalado. Modelo configurado: {model}.",
            "rode: python -m jarvis.doctor --corrigir",
        )
    if preference == "faster-whisper" and chosen != "faster-whisper":
        return (
            "ok",
            f"Whisper clássico, no lugar do faster-whisper. Modelo {model}.",
            "",
        )
    if preference == "whisper" and chosen != "whisper":
        return (
            "ok",
            f"faster-whisper, no lugar do Whisper clássico. Modelo {model}.",
            "",
        )
    if chosen == "faster-whisper":
        return "ok", f"faster-whisper, modelo {model}.", ""
    return "ok", f"Whisper clássico, modelo {model}.", ""


def faster_importable():
    try:
        import faster_whisper  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def whisper_importable():
    try:
        import whisper  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def doctor_line():
    return doctor_status(
        stt_preference(),
        config.whisper_model(),
        faster_importable(),
        whisper_importable(),
    )


def open_transcriber(loaders=None):
    """Abre o backend escolhido. Se ele falhar, tenta o outro."""
    preference = stt_preference()
    model_name = config.whisper_model()
    faster_ok = faster_importable() if loaders is None else "faster-whisper" in loaders
    whisper_ok = whisper_importable() if loaders is None else "whisper" in loaders
    chosen = choose_stt(preference, faster_ok, whisper_ok)
    order = []
    if chosen:
        order.append(chosen)
    for name in ("faster-whisper", "whisper"):
        available = (name == "faster-whisper" and faster_ok) or (name == "whisper" and whisper_ok)
        if name not in order and available:
            order.append(name)
    if not order:
        order = ["faster-whisper" if preference != "whisper" else "whisper"]
    factories = loaders or {
        "faster-whisper": load_faster,
        "whisper": load_classic,
    }
    last = None
    for name in order:
        factory = factories.get(name)
        if factory is None:
            continue
        try:
            return factory(model_name)
        except Exception as error:
            last = error
    from .ears import EarsError

    raise EarsError("não consegui carregar a transcrição") from last


def load_faster(model_name):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    return FasterAdapter(model, model_name)


def load_classic(model_name):
    import whisper

    model = whisper.load_model(model_name)
    return ClassicAdapter(model, model_name)


class _Segment:
    def __init__(self, text):
        self.text = text


class FasterAdapter:
    backend = "faster-whisper"

    def __init__(self, model, model_name):
        self._model = model
        self.model_name = model_name

    def transcribe(self, audio, language=None, beam_size=5, vad_filter=True):
        return self._model.transcribe(
            audio,
            language=language or config.LANGUAGE,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )


class ClassicAdapter:
    backend = "whisper"

    def __init__(self, model, model_name):
        self._model = model
        self.model_name = model_name

    def transcribe(self, audio, language=None, beam_size=5, vad_filter=True):
        result = self._model.transcribe(
            audio,
            language=language or config.LANGUAGE,
            fp16=False,
        )
        text = ""
        if isinstance(result, dict):
            text = str(result.get("text") or "")
        cleaned = " ".join(text.split())
        if not cleaned:
            return [], None
        return [_Segment(cleaned)], None
