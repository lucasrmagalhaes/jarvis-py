import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.wakeword import INFERENCE_FRAMEWORK, WakeWord


class WakeWordBackendTest(unittest.TestCase):
    def test_load_requests_the_onnx_backend(self):
        self.assertEqual(INFERENCE_FRAMEWORK, "onnx")
        package = types.ModuleType("openwakeword")
        package.__path__ = []
        utils = types.ModuleType("openwakeword.utils")
        utils.download_models = mock.Mock(side_effect=OSError("sem rede"))
        package.utils = utils
        model_mod = types.ModuleType("openwakeword.model")
        created = mock.Mock()
        model_mod.Model = mock.Mock(return_value=created)
        modules = {
            "openwakeword": package,
            "openwakeword.utils": utils,
            "openwakeword.model": model_mod,
        }
        with mock.patch.dict(sys.modules, modules):
            word = WakeWord()
            word.load()
        self.assertIs(word.model, created)
        self.assertEqual(
            model_mod.Model.call_args.kwargs["inference_framework"],
            "onnx",
        )
        source = (ROOT / "jarvis" / "wakeword.py").read_text(encoding="utf-8")
        self.assertNotIn("\u2014", source)
        self.assertNotIn("\u2013", source)


if __name__ == "__main__":
    unittest.main()
