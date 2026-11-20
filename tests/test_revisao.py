import json
import os
import stat
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.chat import HELP
from jarvis.review import apply_sm2, parse_card_line, review_path, scan_cards
from jarvis.routines import classify
from jarvis.telegram import TelegramBot, route

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 9, 0, tzinfo=TZ)
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_WORKSPACE",
    "JARVIS_REVISAO",
    "JARVIS_REVISAO_LIMITE",
    "JARVIS_PROMPT_FILE",
    "JARVIS_LOG",
    "JARVIS_STATE",
)


def _files(root):
    found = {}
    for path in Path(root).rglob("*"):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


class ScheduleTest(unittest.TestCase):
    def test_intervals_grow_and_a_miss_resets(self):
        today = date(2026, 10, 28)
        first = apply_sm2({}, "acertei", today)
        self.assertEqual(first["interval"], 1)
        self.assertEqual(first["reps"], 1)
        self.assertEqual(first["due"], "2026-10-29")
        second = apply_sm2(first, "acertei", today)
        self.assertEqual(second["interval"], 6)
        self.assertEqual(second["reps"], 2)
        third = apply_sm2(second, "acertei", today)
        self.assertGreater(third["interval"], second["interval"])
        self.assertEqual(third["reps"], 3)
        missed = apply_sm2(third, "errei", today)
        self.assertEqual(missed["interval"], 1)
        self.assertEqual(missed["reps"], 0)
        self.assertEqual(missed["lapses"], 1)
        self.assertLess(missed["ease"], third["ease"])
        dificil = apply_sm2(second, "dificil", today)
        self.assertEqual(dificil["reps"], 3)
        self.assertGreater(dificil["interval"], 1)
        self.assertLess(dificil["interval"], third["interval"])
        facil = apply_sm2(second, "facil", today)
        self.assertEqual(facil["reps"], 3)
        self.assertGreater(facil["interval"], third["interval"])
        bom = apply_sm2({}, "bom", today)
        self.assertEqual(bom["interval"], 1)
        self.assertEqual(bom["reps"], 1)
        self.assertEqual(missed["due"], "2026-10-29")
        self.assertNotIn("\u2014", json.dumps(missed))

    def test_parser_keeps_the_answer_after_the_separator(self):
        parsed = parse_card_line("- Qual a cor da fita? ::: amarela")
        self.assertEqual(parsed, ("Qual a cor da fita?", "amarela"))
        self.assertIsNone(parse_card_line("sem separador"))
        self.assertIsNone(parse_card_line("::: sem pergunta"))


class ReviewSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        os.environ["JARVIS_REVISAO_LIMITE"] = "2"
        self.vault = self.tmp / "vault"
        book = self.vault / "Livros"
        book.mkdir(parents=True)
        (book / "Foguete de papel.md").write_text(
            "---\n"
            "titulo: nao ::: entra\n"
            "---\n"
            "\n"
            "# Foguete de papel\n"
            "\n"
            "Qual a cor da fita do foguete de papel? ::: amarela\n"
            "- Quantos elásticos o modelo usa? ::: dois\n"
            "\n"
            "```\n"
            "falso ::: segredo\n"
            "```\n",
            encoding="utf-8",
        )
        recipes = self.vault / "Receitas"
        recipes.mkdir()
        (recipes / "Bolo de nuvem.md").write_text(
            "# Bolo de nuvem\n\n"
            "Qual o fermento do bolo de nuvem? ::: ar\n",
            encoding="utf-8",
        )
        hidden = self.vault / ".obsidian"
        hidden.mkdir()
        (hidden / "secreto.md").write_text(
            "Qual a senha do cofre? ::: nao-pode-aparecer\n",
            encoding="utf-8",
        )
        self.before = _files(self.vault)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _brain(self):
        from jarvis.brain import Brain

        brain = Brain()

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False

            def prepare(self):
                raise AssertionError("a revisão não prepara o git")

            def publish(self, _text):
                raise AssertionError("a revisão não publica o vault")

        brain.vault = Vault(self.vault)
        brain.clock = lambda: NOW
        brain._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("claude"))
        return brain

    def test_day_review_asks_waits_and_grades_without_writing_the_vault(self):
        self.assertEqual(classify("Hey Jarvis, revisão do dia").kind, "review")
        self.assertEqual(classify("me pergunta sobre o livro foguete").kind, "review_book")
        self.assertEqual(classify("pausa a revisão").kind, "review_pause")
        self.assertEqual(classify("acertei").kind, "review_grade")
        self.assertEqual(classify("eu errei").query, "errei")
        cards = scan_cards(self.vault)
        self.assertEqual(len(cards), 3)
        self.assertTrue(all("nao-pode-aparecer" not in card["answer"] for card in cards))
        self.assertTrue(all("segredo" not in card["answer"] for card in cards))
        self.assertNotIn("entra", [card["answer"] for card in cards])

        brain = self._brain()
        opening = brain.ask("revisão do dia")
        self.assertIn("São 2 cartões nesta revisão, senhor.", opening)
        self.assertIn("Qual a cor da fita do foguete de papel?", opening)
        self.assertNotIn("amarela", opening)
        self.assertNotIn("resposta é", opening)
        self.assertNotIn("nao-pode-aparecer", opening)
        self.assertNotIn("segredo", opening)
        self.assertNotIn("\u2014", opening)

        revealed = brain.ask("acho que é verde")
        self.assertIn("A resposta é amarela, senhor.", revealed)
        self.assertIn("acertei ou errei", revealed)
        self.assertEqual(self.before, _files(self.vault))

        nxt = brain.ask("acertei")
        self.assertIn("Quantos elásticos o modelo usa?", nxt)
        stored = json.loads(review_path().read_text(encoding="utf-8"))
        card = next(iter(stored["cards"].values()))
        self.assertEqual(card["interval"], 1)
        self.assertEqual(card["reps"], 1)
        self.assertEqual(card["due"], "2026-10-29")
        blob = json.dumps(stored, ensure_ascii=False)
        self.assertNotIn("amarela", blob)
        self.assertNotIn("Qual a cor", blob)
        self.assertNotIn("elásticos", blob)
        if os.name != "nt":
            mode = review_path().stat().st_mode & 0o777
            self.assertEqual(mode, stat.S_IRUSR | stat.S_IWUSR)
        self.assertFalse((self.vault / "revisao.json").exists())
        self.assertEqual(self.before, _files(self.vault))

        brain.ask("dois")
        done = brain.ask("errei")
        self.assertIn("volta amanhã", done)
        self.assertIn("Revisão encerrada", done)
        again = brain.ask("revisão do dia")
        self.assertIn("O limite de hoje é 2 cartões", again)
        self.assertEqual(self.before, _files(self.vault))

    def test_book_filter_uses_the_note_path_and_survives_a_new_process(self):
        brain = self._brain()
        opening = brain.ask("me pergunta sobre o livro bolo de nuvem")
        self.assertIn("fermento do bolo de nuvem", opening)
        self.assertNotIn("fita", opening)
        self.assertNotIn("resposta é", opening)
        other = BrainPeek(self.vault)
        revealed = other.ask("minha tentativa")
        self.assertIn("A resposta é ar, senhor.", revealed)
        self.assertEqual(other.ask("acertei"), "Certo, senhor. Revisão encerrada, senhor.")
        missed = brain.ask("me pergunta sobre o livro que nao existe")
        self.assertIn("Não encontrei cartão no caminho desse livro", missed)
        self.assertEqual(self.before, _files(self.vault))

    def test_pause_stops_today_and_resume_continues(self):
        brain = self._brain()
        brain.ask("revisão do dia")
        paused = brain.ask("pausa a revisão")
        self.assertIn("Pausa na revisão", paused)
        blocked = brain.ask("revisão do dia")
        self.assertIn("pausada hoje", blocked)
        resumed = brain.ask("retoma a revisão")
        self.assertIn("Pergunta:", resumed)
        self.assertEqual(self.before, _files(self.vault))

    def test_state_file_is_refused_inside_the_vault(self):
        os.environ["JARVIS_REVISAO"] = str(self.vault / "revisao.json")
        brain = self._brain()
        reply = brain.ask("revisão do dia")
        self.assertIn("Não guardei a revisão dentro do vault", reply)
        self.assertFalse((self.vault / "revisao.json").exists())
        self.assertEqual(self.before, _files(self.vault))

    def test_telegram_and_help_use_the_same_phrases(self):
        update = {
            "message": {
                "chat": {"id": 5, "type": "private"},
                "from": {"id": 5},
                "text": "revisão do dia",
            }
        }
        decision = route(update, 5)
        self.assertEqual(decision["action"], "text")
        brain = self._brain()
        reply = brain.ask(decision["text"])
        self.assertIn("Pergunta:", reply)

        class Api:
            def __init__(self):
                self.sent = []

            def call(self, method, payload, timeout=30):
                self.sent.append((method, payload))
                return {"ok": True, "result": {}}

        api = Api()
        bot = TelegramBot(api, 5, lambda text: "eco", lambda path: "")
        bot.handle(
            {
                "message": {
                    "chat": {"id": 5, "type": "private"},
                    "from": {"id": 5},
                    "text": "/ajuda",
                }
            }
        )
        self.assertTrue(api.sent)
        folded = api.sent[0][1]["text"].casefold()
        self.assertIn("revisão do dia", folded)
        self.assertIn("acertei", folded)
        self.assertIn("silencia esse aviso hoje", folded)
        self.assertIn("silencia sempre", folded)
        self.assertIn("pausa os alertas até amanhã", folded)
        self.assertNotIn("\u2014", folded)
        self.assertNotIn("\u2013", folded)
        self.assertIn("acertei", HELP)
        self.assertNotIn("\u2014", HELP)


class BrainPeek:
    def __init__(self, vault):
        from jarvis.brain import Brain

        self.brain = Brain()

        class Vault:
            def __init__(self, path):
                self.path = path

            def prepare(self):
                raise AssertionError("prepare")

            def publish(self, _text):
                raise AssertionError("publish")

        self.brain.vault = Vault(vault)
        self.brain.clock = lambda: NOW

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        self.brain._ask = fail

    def ask(self, text):
        return self.brain.ask(text)
