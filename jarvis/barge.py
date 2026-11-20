"""Corta a fala quando chega o wake word, 'Jarvis, para' ou uma tecla.

O microfone e o teclado entram por objetos com read() e pressed().
Os testes passam falsos e não abrem o áudio de verdade.
"""

import os
import sys
import time

from . import config
from .ears import EarsError, load_mic
from .routines import fold, normalize_phrase
from .wakeword import FRAME_SAMPLES

STOP_PHRASES = {
    "para",
    "jarvis para",
    "para jarvis",
    "hey jarvis",
    "ei jarvis",
}


def is_stop_phrase(text):
    compact = fold(" ".join((text or "").replace(",", " ").split()).strip(" \t.!?"))
    if compact in STOP_PHRASES:
        return True
    return fold(normalize_phrase(text or "")) in STOP_PHRASES


class StdinKeys:
    """Tecla no terminal, sem bloquear. No Windows usa msvcrt."""

    def pressed(self):
        try:
            if os.name == "nt":
                import msvcrt

                if not msvcrt.kbhit():
                    return False
                msvcrt.getwch()
                return True
            import select

            ready, _write, _error = select.select([sys.stdin], [], [], 0)
            if not ready:
                return False
            sys.stdin.read(1)
            return True
        except Exception:
            return False


def stdin_keys_if_tty():
    stream = getattr(sys, "stdin", None)
    isatty = getattr(stream, "isatty", None)
    try:
        if isatty is None or not isatty():
            return None
    except Exception:
        return None
    return StdinKeys()


class _MicFrames:
    def __init__(self):
        self.np, self.sd = load_mic()
        self.stream = self.sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
        )
        self.stream.__enter__()

    def read(self):
        frame, _overflow = self.stream.read(FRAME_SAMPLES)
        return frame

    def close(self):
        try:
            self.stream.__exit__(None, None, None)
        except Exception:
            return


def watch(stop, wake, ears, frames=None, keys=None):
    model = getattr(wake, "model", None) if wake is not None else None
    can_hear = ears is not None and getattr(ears, "model", None) is not None
    if frames is None and keys is None and model is None and not can_hear:
        return
    owned = None
    if frames is None and (model is not None or can_hear):
        try:
            owned = _MicFrames()
            frames = owned
        except EarsError:
            if keys is None:
                return
            frames = None
    try:
        _loop(stop, model, ears, can_hear, frames, keys)
    except Exception:
        return
    finally:
        if owned is not None:
            owned.close()


def _loop(stop, model, ears, can_hear, frames, keys):
    voiced = []
    silent = 0
    hot = False
    while not stop.is_set():
        if keys is not None and keys.pressed():
            stop.set()
            return
        if frames is None:
            time.sleep(0.03)
            continue
        frame = frames.read()
        if frame is None:
            return
        if model is not None and _score(model, frame) >= config.WAKE_THRESHOLD:
            stop.set()
            return
        if not can_hear:
            continue
        rms = _rms(frame)
        if rms >= max(0.03, config.SILENCE_THRESHOLD):
            hot = True
            silent = 0
            voiced.append(frame)
            if len(voiced) >= 40 and _matches(ears, voiced):
                stop.set()
                return
            if len(voiced) >= 40:
                voiced = []
                hot = False
        elif hot:
            silent += 1
            voiced.append(frame)
            if silent >= 6:
                if _matches(ears, voiced):
                    stop.set()
                    return
                voiced = []
                hot = False
                silent = 0


def _score(model, frame):
    try:
        scores = model.predict(frame)
    except Exception:
        return 0.0
    if not scores:
        return 0.0
    try:
        return max(scores.values())
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _rms(frame):
    try:
        import numpy as np

        squeezed = np.squeeze(frame).astype(np.float32)
        return float(np.sqrt(np.mean(np.square(squeezed)))) / 32768.0
    except Exception:
        return 0.0


def _matches(ears, frames):
    if not frames or ears is None or ears.model is None:
        return False
    try:
        import numpy as np
    except (ImportError, OSError):
        return False
    audio = np.concatenate(frames).astype(np.float32).reshape(-1) / 32768.0
    try:
        segments, _info = ears.model.transcribe(
            audio, language=config.LANGUAGE, beam_size=1, vad_filter=True
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception:
        return False
    return is_stop_phrase(text)
