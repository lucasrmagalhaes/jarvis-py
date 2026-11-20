import platform
import queue

from . import config


class EarsError(Exception):
    pass


def load_mic():
    """Importa o áudio só quando o microfone vai abrir.

    Modo texto, Telegram e os testes não precisam de sounddevice.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except (ImportError, OSError) as error:
        raise EarsError(
            "não há áudio disponível; use o modo texto ou instale as dependências de voz"
        ) from error
    return np, sd


def mic_permission_hint():
    system = platform.system()
    if system == "Darwin":
        return (
            "verifique a permissão em Ajustes do Sistema > "
            "Privacidade e Segurança > Microfone"
        )
    if system == "Windows":
        return "verifique a permissão em Configurações > Privacidade > Microfone"
    return "verifique a permissão de microfone do sistema"


class Ears:
    def __init__(self):
        self.model = None

    def load(self):
        if self.model is None:
            from .stt import open_transcriber

            self.model = open_transcriber()

    def record(self, no_speech_seconds=None):
        np, sd = load_mic()
        blocks = queue.Queue()

        def callback(indata, frames, time_info, status):
            blocks.put(indata.copy())

        if no_speech_seconds is None:
            no_speech_seconds = config.NO_SPEECH_SECONDS

        captured = []
        pre_speech = []
        calibration = []
        speech_started = False
        silent_blocks = 0
        threshold = config.SILENCE_THRESHOLD
        calibration_blocks = int(config.CALIBRATION_SECONDS / config.BLOCK_SECONDS)
        pre_speech_limit = int(config.PRE_SPEECH_SECONDS / config.BLOCK_SECONDS)
        no_speech_limit = int(no_speech_seconds / config.BLOCK_SECONDS)
        max_blocks = int(config.MAX_RECORD_SECONDS / config.BLOCK_SECONDS)
        silence_limit = int(config.SILENCE_SECONDS / config.BLOCK_SECONDS)

        try:
            with sd.InputStream(
                samplerate=config.SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=int(config.SAMPLE_RATE * config.BLOCK_SECONDS),
                callback=callback,
            ):
                for index in range(max_blocks):
                    try:
                        block = blocks.get(timeout=2.0)
                    except queue.Empty as error:
                        raise EarsError("o microfone parou de enviar áudio") from error

                    rms = float(np.sqrt(np.mean(np.square(block))))

                    if index < calibration_blocks:
                        calibration.append(rms)
                        pre_speech.append(block)
                        continue
                    if index == calibration_blocks and calibration:
                        ambient = float(np.median(calibration))
                        threshold = max(threshold, ambient * 2.5)

                    if speech_started:
                        captured.append(block)
                        if rms >= threshold:
                            silent_blocks = 0
                        else:
                            silent_blocks += 1
                            if silent_blocks >= silence_limit:
                                break
                    elif rms >= threshold:
                        speech_started = True
                        captured.extend(pre_speech)
                        captured.append(block)
                    else:
                        pre_speech.append(block)
                        if len(pre_speech) > pre_speech_limit:
                            pre_speech.pop(0)
                        if index >= no_speech_limit:
                            return None
        except sd.PortAudioError as error:
            raise EarsError(
                f"não consegui acessar o microfone; {mic_permission_hint()}"
            ) from error

        if not speech_started:
            return None
        return np.concatenate(captured).flatten()

    def transcribe(self, audio):
        self.load()
        segments, _ = self.model.transcribe(
            audio, language=config.LANGUAGE, beam_size=5, vad_filter=True
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text or None

    def listen(self, no_speech_seconds=None):
        audio = self.record(no_speech_seconds=no_speech_seconds)
        if audio is None:
            return None
        return self.transcribe(audio)
