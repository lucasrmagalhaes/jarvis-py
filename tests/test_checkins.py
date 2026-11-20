import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from jarvis.checkins import due_kind
from jarvis.companion import Companion, _lock_path
from jarvis.offers import load_offer, store_offer
from jarvis.routines import classify, offer_choice, run_routine
from jarvis.vault import SyncResult

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 8, 0, tzinfo=TZ)
EVENING = datetime(2026, 10, 28, 19, 0, tzinfo=TZ)
ENV = (
    "JARVIS_HOME",
    "JARVIS_STATE",
    "JARVIS_VAULT",
    "JARVIS_WORKSPACE",
    "JARVIS_CHECKIN",
    "JARVIS_CHECKIN_MORNING",
    "JARVIS_CHECKIN_EVENING",
    "JARVIS_CHECKIN_EVENING_AT",
    "JARVIS_GH_BIN",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
)


class FakeVault:
    def __init__(self, path):
        self.path = path
        self.sync = True
        self.blocked = False
        self.published = None

    def prepare(self):
        return SyncResult(True, "ready", "ok")

    def publish(self, text):
        self.published = text
        return SyncResult(True, "pushed", "ok", committed=True, pushed=True)

    def resync_snapshot(self):
        return None

    def hud_payload(self):
        return {"pending": 0}


class CheckinTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._env = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_HOME"] = str(self.home)
        os.environ["JARVIS_STATE"] = str(self.home / "state.json")
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")

    def tearDown(self):
        import shutil

        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_due_kind_morning_then_evening_once(self):
        self.assertEqual(due_kind(NOW, {}, True, True, (18, 30)), "morning")
        self.assertIsNone(due_kind(NOW, {"morning": "2026-10-28"}, True, True, (18, 30)), None)
        self.assertEqual(due_kind(EVENING, {"morning": "2026-10-28"}, True, True, (18, 30)), "evening")
        self.assertEqual(due_kind(EVENING, {}, True, True, (18, 30)), "evening")
        self.assertEqual(due_kind(EVENING, {}, True, False, (18, 30)), "morning")
        self.assertIsNone(due_kind(NOW, {}, False, False, (18, 30)))
        self.assertIsNone(
            due_kind(EVENING, {"morning": "2026-10-28", "evening": "2026-10-28"}, True, True, (18, 30))
        )

    def test_day_summary_offers_to_save_without_writing(self):
        note = self.tmp / "2026-10-28.md"
        note.write_text(
            "# Dia\n\n- 08:00 comprar cafe\n- [x] enviar o relatorio\n- [ ] revisar a proposta\n",
            encoding="utf-8",
        )
        os.utime(note, (NOW.timestamp(), NOW.timestamp()))
        old = self.tmp / "velho.md"
        old.write_text("- [ ] tarefa velha\n", encoding="utf-8")
        os.utime(old, (1_600_000_000, 1_600_000_000))
        self.assertEqual(classify("resumo do fim do dia").kind, "day")
        self.assertEqual(classify("como foi meu dia").kind, "day")
        self.assertEqual(classify("resumo do dia").kind, "briefing")
        session = {}
        reply = run_routine(self.tmp, classify("como foi meu dia?"), NOW, session=session)
        self.assertIn("fechando o dia", reply)
        self.assertIn("comprar cafe", reply)
        self.assertIn("enviar o relatorio", reply)
        self.assertIn("revisar a proposta", reply)
        self.assertNotIn("tarefa velha", reply)
        self.assertIn("Quer que eu grave esse resumo, senhor?", reply)
        pending = session["pending"]
        self.assertEqual(pending["kind"], "day")
        self.assertEqual(pending["relative"], "fim-2026-10-28.md")
        self.assertIn("comprar cafe", pending["body"])
        self.assertIn("## Amanhã", pending["body"])
        self.assertIn("Nada marcado para amanhã.", pending["body"])
        self.assertNotIn("senhor", pending["body"])
        self.assertNotIn("\u2014", pending["body"])
        self.assertNotIn("\u2013", pending["body"])
        self.assertFalse((self.tmp / pending["relative"]).exists())
        self.assertEqual(offer_choice("sim", pending), "yes")
        self.assertEqual(offer_choice("não", pending), "no")
        blocked = {}
        quiet = run_routine(
            self.tmp,
            classify("fechamento do dia"),
            NOW,
            read_only=True,
            session=blocked,
        )
        self.assertIn("bloqueado", quiet)
        self.assertNotIn("pending", blocked)

    def test_day_summary_names_finished_reminders_and_tomorrow(self):
        note = self.tmp / "2026-10-28.md"
        note.write_text(
            "# Dia\n\n"
            "- 08:00 ligar para o cliente\n"
            "- [x] pagar o boleto @ 2026-10-28 09:00\n"
            "- [x] enviar o relatorio\n"
            "- [x] ignorar isto @ 2026-10-28 10:00 @cancelado\n"
            "- [ ] revisar a proposta\n"
            "- [ ] buscar o carro @ 2026-10-29 15:00\n"
            "- [ ] viagem longa @ 2026-11-02 09:00\n",
            encoding="utf-8",
        )
        os.utime(note, (NOW.timestamp(), NOW.timestamp()))
        agenda = self.tmp / "Agenda Profissional"
        agenda.mkdir()
        (agenda / "2026-10-29.md").write_text("# Amanha\n\n- 10:00 dentista\n", encoding="utf-8")
        session = {}
        reply = run_routine(self.tmp, classify("como foi meu dia?"), NOW, session=session)
        self.assertIn("Lembretes concluídos", reply)
        self.assertIn("pagar o boleto", reply)
        self.assertIn("enviar o relatorio", reply)
        self.assertIn("revisar a proposta", reply)
        self.assertIn("Amanhã", reply)
        self.assertIn("buscar o carro", reply)
        self.assertIn("dentista", reply)
        self.assertNotIn("ignorar isto", reply)
        self.assertNotIn("viagem longa", reply)
        self.assertNotIn("\u2014", reply)
        body = session["pending"]["body"]
        self.assertIn("## Lembretes concluídos", body)
        self.assertIn("- pagar o boleto", body)
        self.assertIn("## Amanhã", body)
        self.assertIn("15:00 buscar o carro", body)
        self.assertIn("10:00 dentista", body)
        self.assertNotIn("ignorar isto", body)
        self.assertNotIn("viagem longa", body)
        self.assertNotIn("senhor", body)
        self.assertNotIn("\u2014", body)
        self.assertNotIn("\u2013", body)
        self.assertFalse((self.tmp / "fim-2026-10-28.md").exists())

    def test_yes_saves_the_day_and_no_discards_the_offer(self):
        note = self.tmp / "2026-10-28.md"
        note.write_text("- 08:00 comprar cafe\n", encoding="utf-8")
        os.utime(note, (NOW.timestamp(), NOW.timestamp()))
        session = {}
        run_routine(self.tmp, classify("resumo do fim do dia"), NOW, session=session)
        store_offer(session["pending"])
        from jarvis.brain import Brain

        saved = Brain()
        saved.vault = FakeVault(self.tmp)
        self.assertIn("Gravei o resumo do dia", saved.ask("sim"))
        body = (self.tmp / "fim-2026-10-28.md").read_text(encoding="utf-8")
        self.assertIn("comprar cafe", body)
        self.assertNotIn("senhor", body)
        self.assertIsNone(load_offer())

        store_offer(session["pending"])
        declined = Brain()
        declined.vault = FakeVault(self.tmp)
        self.assertIn("Não gravei", declined.ask("não"))
        self.assertIsNone(load_offer())

        store_offer({"kind": "day", "relative": "../segredo.md", "body": "x\n"})
        self.assertIsNone(load_offer())

    def test_companion_sends_morning_once_and_evening_with_offer(self):
        spoken = []
        brain = SimpleNamespace(vault=FakeVault(self.tmp), pending=None, on_status=None)
        companion = Companion(brain, speak=spoken.append, lock=threading.RLock())
        companion._held = True
        self.assertIn("Bom dia", companion.tick(NOW))
        self.assertIsNone(companion.tick(NOW))
        self.assertEqual(len(spoken), 1)
        reply = companion.tick(EVENING)
        self.assertIn("Quer que eu grave esse resumo", reply)
        self.assertEqual(brain.pending["kind"], "day")
        self.assertIsNotNone(load_offer())
        self.assertFalse((self.tmp / "fim-2026-10-28.md").exists())
        self.assertIsNone(companion.tick(EVENING))
        os.environ["JARVIS_CHECKIN"] = "off"
        fresh = Companion(brain, speak=spoken.append, lock=threading.RLock())
        fresh._held = True
        self.assertIsNone(fresh.tick(datetime(2026, 10, 29, 8, 0, tzinfo=TZ)))

    def test_sunday_saves_the_week_before_the_evening_summary(self):
        morning = datetime(2026, 11, 1, 8, 0, tzinfo=TZ)
        evening = datetime(2026, 11, 1, 19, 0, tzinfo=TZ)
        self.assertEqual(due_kind(morning, {}, True, True, (18, 30)), "morning")
        self.assertEqual(due_kind(evening, {}, True, True, (18, 30)), "week")
        self.assertEqual(due_kind(evening, {"week": "2026-11-01"}, True, True, (18, 30)), "evening")
        self.assertEqual(due_kind(EVENING, {}, True, True, (18, 30)), "evening")
        note = self.tmp / "Diario.md"
        note.write_text("# Diario\n\n- [x] fechar a semana\n", encoding="utf-8")
        os.utime(note, (evening.timestamp(), evening.timestamp()))
        spoken = []
        brain = SimpleNamespace(vault=FakeVault(self.tmp), pending=None, on_status=None)
        companion = Companion(brain, speak=spoken.append, lock=threading.RLock())
        companion._held = True
        hello = companion.tick(morning)
        self.assertIn("Bom dia", hello)
        self.assertIn("Não há compromisso marcado para hoje", hello)
        saved = companion.tick(evening)
        self.assertIn("Gravei o resumo da semana", saved)
        path = self.tmp / "semana-2026-10-26.md"
        body = path.read_text(encoding="utf-8")
        self.assertIn("fechar a semana", body)
        self.assertNotIn("senhor", body)
        self.assertNotIn("\u2014", body)
        self.assertNotIn("\u2013", body)
        follow = companion.tick(evening)
        self.assertIn("Quer que eu grave esse resumo", follow)
        self.assertFalse((self.tmp / "fim-2026-11-01.md").exists())
        self.assertIsNone(companion.tick(evening))
        from jarvis.routines import autosave_week

        repeat = autosave_week(self.tmp, evening)
        self.assertIn("já está no vault", repeat)
        self.assertEqual(path.read_text(encoding="utf-8"), body)
        other = self.tmp / "outro"
        other.mkdir()
        blocked = autosave_week(other, evening, read_only=True)
        self.assertIn("bloqueado", blocked)
        self.assertEqual(list(other.iterdir()), [])

    def test_only_one_process_owns_the_companion(self):
        brain = SimpleNamespace(vault=None, pending=None, on_status=None)
        first = Companion(brain, lock=threading.RLock())
        second = Companion(brain, lock=threading.RLock())
        self.assertTrue(first.start())
        self.assertFalse(second.start())
        first.stop()
        self.assertTrue(second.start())
        second.stop()
        dead = _lock_path()
        dead.parent.mkdir(parents=True, exist_ok=True)
        dead.write_text("2147483647", encoding="utf-8")
        third = Companion(brain, lock=threading.RLock())
        self.assertTrue(third.start())
        third.stop()


if __name__ == "__main__":
    unittest.main()
