from . import config
from .ears import EarsError, load_mic, mic_permission_hint

FRAME_SAMPLES = 1280
INFERENCE_FRAMEWORK = "onnx"


class WakeWord:
    def __init__(self):
        self.model = None

    def load(self):
        if self.model is None:
            import openwakeword
            from openwakeword.model import Model

            try:
                openwakeword.utils.download_models(model_names=[config.WAKE_MODEL])
            except Exception:
                pass
            self.model = Model(
                wakeword_models=[config.WAKE_MODEL],
                inference_framework=INFERENCE_FRAMEWORK,
            )

    def wait(self, stop_when=None):
        np, sd = load_mic()
        self.load()
        self.model.reset()
        try:
            with sd.InputStream(
                samplerate=config.SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
            ) as stream:
                while True:
                    if stop_when and stop_when():
                        return False
                    frame, _ = stream.read(FRAME_SAMPLES)
                    scores = self.model.predict(np.squeeze(frame))
                    if max(scores.values()) >= config.WAKE_THRESHOLD:
                        return True
        except sd.PortAudioError as error:
            raise EarsError(
                f"não consegui acessar o microfone; {mic_permission_hint()}"
            ) from error
