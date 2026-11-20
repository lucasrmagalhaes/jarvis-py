import unittest
from io import StringIO
from pathlib import Path

from jarvis.chat import HELP, loop

ROOT = Path(__file__).resolve().parents[1]


class ChatTest(unittest.TestCase):
    def test_loop_uses_the_brain_and_exits_without_microphone(self):
        seen = []

        def ask(text):
            seen.append(text)
            return "Bom dia, senhor."

        source = StringIO("bom dia\n\n/ajuda\n/sair\n")
        output = StringIO()
        loop(ask, source.readline, output.write)
        text = output.getvalue()
        self.assertEqual(seen, ["bom dia"])
        self.assertIn("JARVIS: Bom dia, senhor.", text)
        self.assertIn(HELP, text)
        self.assertIn("Encerrando os sistemas", text)
        self.assertIn("sem microfone", text)

    def test_empty_stdin_ends_the_loop(self):
        source = StringIO("")
        output = StringIO()
        loop(lambda text: "não", source.readline, output.write)
        self.assertNotIn("JARVIS: não", output.getvalue())

    def test_chat_module_does_not_touch_the_microphone(self):
        source = (ROOT / "jarvis" / "chat.py").read_text(encoding="utf-8")
        self.assertNotIn("sounddevice", source)
        self.assertNotIn("wakeword", source)
        self.assertNotIn("faster_whisper", source)
        self.assertNotIn("\u2014", source)
        self.assertNotIn("\u2013", source)


if __name__ == "__main__":
    unittest.main()
