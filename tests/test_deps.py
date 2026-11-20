import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packaging.requirements import Requirement

from jarvis.deps import (
    pip_commands,
    requirements_without_wake,
    tflite_unavailable,
    wakeword_usable,
)


class DependencySplitTest(unittest.TestCase):
    def test_linux_python_313_skips_openwakeword_and_keeps_the_rest(self):
        reqs = _requirements(ROOT / "requirements.txt")
        names = [item.name for item in reqs]
        for name in (
            "sounddevice",
            "edge-tts",
            "soundfile",
            "numpy",
            "onnxruntime",
            "faster-whisper",
        ):
            match = next(item for item in reqs if item.name == name)
            self.assertIsNone(match.marker, name)
        self.assertNotIn("tflite-runtime", names)
        wake = next(item for item in reqs if item.name == "openwakeword")
        self.assertFalse(
            wake.marker.evaluate({"python_version": "3.13", "platform_system": "Linux"})
        )
        self.assertFalse(
            wake.marker.evaluate({"python_version": "3.12", "platform_system": "Linux"})
        )
        self.assertTrue(
            wake.marker.evaluate({"python_version": "3.11", "platform_system": "Linux"})
        )
        self.assertTrue(
            wake.marker.evaluate({"python_version": "3.13", "platform_system": "Darwin"})
        )
        self.assertTrue(
            wake.marker.evaluate({"python_version": "3.13", "platform_system": "Windows"})
        )

    def test_wake_files_skip_tflite_and_use_onnx_install(self):
        deps = (ROOT / "requirements-wake-deps.txt").read_text(encoding="utf-8")
        wake = (ROOT / "requirements-wake.txt").read_text(encoding="utf-8")
        self.assertIn("openwakeword>=0.6", wake)
        self.assertNotIn("--no-deps", _code_lines(wake))
        self.assertNotIn("tflite", deps.lower())
        self.assertNotIn("tflite", _code_lines(wake))
        self.assertNotIn("sounddevice", deps)
        self.assertNotIn("edge-tts", deps)
        self.assertNotIn("soundfile", deps)
        for name in ("tqdm", "scipy", "scikit-learn", "requests"):
            self.assertIn(name, deps)

    def test_fallback_requirements_drop_only_the_wake_line(self):
        filtered = requirements_without_wake(
            "sounddevice>=0.4.6\n"
            "edge-tts>=6.1\n"
            "soundfile>=0.12\n"
            "openwakeword>=0.6; python_version < \"3.12\" or platform_system != \"Linux\"\n"
            "# tflite-runtime fica de fora\n"
        )
        self.assertIn("sounddevice>=0.4.6", filtered)
        self.assertIn("edge-tts>=6.1", filtered)
        self.assertIn("soundfile>=0.12", filtered)
        self.assertNotIn("openwakeword", filtered)
        self.assertNotIn("tflite", filtered.lower())

    def test_pip_commands_keep_wake_away_from_audio_and_voice(self):
        commands = pip_commands(
            ["sounddevice", "edge-tts", "soundfile", "openwakeword>=0.6"],
            "python",
            ROOT,
        )
        self.assertEqual(
            commands[0],
            ["python", "-m", "pip", "install", "sounddevice", "edge-tts", "soundfile"],
        )
        joined = [" ".join(command) for command in commands[1:]]
        self.assertTrue(any("requirements-wake-deps.txt" in item for item in joined))
        wake_cmd = next(
            command for command in commands if str(command[-1]).endswith("requirements-wake.txt")
        )
        self.assertIn("--no-deps", wake_cmd)
        self.assertNotIn("--no-deps", commands[0])
        for command in commands:
            blob = " ".join(command)
            if "openwakeword" in blob or "requirements-wake" in blob:
                self.assertNotIn("sounddevice", command)
                self.assertNotIn("edge-tts", command)
                self.assertNotIn("soundfile", command)

    def test_tflite_gap_is_linux_from_python_312(self):
        self.assertTrue(tflite_unavailable("Linux", (3, 13, 0)))
        self.assertTrue(tflite_unavailable("Linux", (3, 12, 1)))
        self.assertFalse(tflite_unavailable("Linux", (3, 11, 9)))
        self.assertFalse(tflite_unavailable("Darwin", (3, 13, 0)))
        self.assertFalse(tflite_unavailable("Windows", (3, 13, 0)))

    def test_wakeword_usable_requires_the_onnx_argument(self):
        import types
        from unittest import mock

        package = types.ModuleType("openwakeword")
        package.__path__ = []
        model_mod = types.ModuleType("openwakeword.model")

        class Model:
            def __init__(self):
                return None

        model_mod.Model = Model
        modules = {"openwakeword": package, "openwakeword.model": model_mod}
        with mock.patch.dict(sys.modules, modules):
            with mock.patch("inspect.getsource", return_value="def __init__(self): pass"):
                self.assertFalse(wakeword_usable())
            with mock.patch(
                "inspect.getsource",
                return_value="def __init__(self, inference_framework='onnx'): pass",
            ):
                self.assertTrue(wakeword_usable())


def _requirements(path):
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        found.append(Requirement(stripped))
    return found


def _code_lines(text):
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


if __name__ == "__main__":
    unittest.main()
