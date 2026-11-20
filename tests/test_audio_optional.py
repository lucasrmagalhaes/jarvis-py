import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODULES = (
    "jarvis/ears.py",
    "jarvis/wakeword.py",
    "jarvis/barge.py",
    "jarvis/main.py",
    "jarvis/chat.py",
    "jarvis/telegram.py",
    "jarvis/voice.py",
)


class AudioOptionalTest(unittest.TestCase):
    def test_modules_do_not_import_sounddevice_at_load(self):
        for name in MODULES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("import sounddevice") or stripped.startswith(
                    "from sounddevice"
                ):
                    self.assertTrue(
                        line.startswith(" ") or line.startswith("\t"),
                        name,
                    )
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)

    def test_text_and_telegram_import_without_sounddevice(self):
        script = r"""
import sys
import threading

class Blocker:
    def find_spec(self, fullname, path, target=None):
        if fullname == "sounddevice" or fullname.startswith("sounddevice."):
            raise ImportError("sem audio")
        return None

sys.meta_path.insert(0, Blocker())

import jarvis.main
import jarvis.chat
import jarvis.telegram
import jarvis.barge
import jarvis.ears
import jarvis.wakeword
from jarvis.barge import is_stop_phrase, watch
from jarvis.ears import Ears, EarsError, load_mic
from jarvis.wakeword import WakeWord

assert is_stop_phrase("Jarvis, para")

try:
    load_mic()
except EarsError as error:
    assert "não há áudio" in str(error)
else:
    raise SystemExit("load_mic deveria falhar")

try:
    Ears().record()
except EarsError as error:
    assert "não há áudio" in str(error)
else:
    raise SystemExit("record deveria falhar")

try:
    WakeWord().wait()
except EarsError as error:
    assert "não há áudio" in str(error)
else:
    raise SystemExit("wait deveria falhar")

class FakeEars:
    model = object()

watch(threading.Event(), None, FakeEars())
print("ok")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)
        self.assertNotIn("InputStream", result.stderr)
