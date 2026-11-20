import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.alerts import pause_alerts, silence
from jarvis.radar import decide
from jarvis.reminders import ReminderService
from jarvis.routines import classify, focus_speech
from jarvis.state import load

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
NEXT = NOW + timedelta(days=1)
ENV = (
    "JARVIS_STATE",
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_WORKSPACE",
    "JARVIS_GH_BIN",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
)


def _jira(status):
    return {
        "github": ("off", []),
        "jira": ("ok", [{"key": "ABC-1", "status": status, "summary": "Subir o HUD"}]),
        "mail": ("off", []),
    }


class AlertControlTest(unittest.TestCase):
    def test_today_holds_the_change_and_always_absorbs_it(self):
        self.assertEqual(classify("silencia esse aviso hoje").kind, "mute_today")
        self.assertEqual(classify("silencia sempre").kind, "mute_always")
        self.assertEqual(classify("silencia esse aviso sempre").kind, "mute_always")
        self.assertEqual(classify("pausa os alertas até amanhã").kind, "pause_alerts")
        self.assertNotEqual(
            classify("silencia esse aviso hoje").kind,
            classify("silencia sempre").kind,
        )

        _speech, seeded = decide({}, _jira("A fazer"), NOW, 0)
        spoken, state = decide(seeded, _jira("Em andamento"), NOW, 0)
        self.assertIn("ABC-1 mudou para Em andamento", spoken)
        self.assertIn("jira:ABC-1", state["spoken_ids"])
        self.assertNotIn("\u2014", spoken)

        held, kept = decide(
            state,
            _jira("Feito"),
            LATER,
            0,
            control={"today": ["jira:ABC-1"], "always": []},
        )
        self.assertEqual(held, "")
        self.assertEqual(kept["jira"]["ABC-1"], "Em andamento")
        later, resumed = decide(kept, _jira("Feito"), NEXT, 0)
        self.assertIn("Feito", later)
        self.assertEqual(resumed["jira"]["ABC-1"], "Feito")

        quiet, absorbed = decide(
            state,
            _jira("Feito"),
            LATER,
            0,
            control={"always": ["jira:ABC-1"], "today": []},
        )
        self.assertEqual(quiet, "")
        self.assertEqual(absorbed["jira"]["ABC-1"], "Feito")
        still, final = decide(
            absorbed,
            _jira("Concluída"),
            NEXT,
            0,
            control={"always": ["jira:ABC-1"], "today": []},
        )
        self.assertEqual(still, "")
        self.assertEqual(final["jira"]["ABC-1"], "Concluída")

    def test_pause_keeps_the_change_for_tomorrow(self):
        _speech, seeded = decide({}, _jira("A fazer"), NOW, 0)
        paused, kept = decide(
            seeded,
            _jira("Em andamento"),
            NOW,
            0,
            control={"paused": True},
        )
        self.assertEqual(paused, "")
        self.assertEqual(kept["jira"]["ABC-1"], "A fazer")
        spoken, nxt = decide(kept, _jira("Em andamento"), NEXT, 0)
        self.assertIn("Em andamento", spoken)
        self.assertEqual(nxt["jira"]["ABC-1"], "Em andamento")


class AlertVoiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_STATE"] = str(self.tmp / "state.json")
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_GH_BIN"] = "/bin/false"

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_voice_silence_today_is_not_forever(self):
        from jarvis.brain import Brain
        from jarvis.radar import RadarService

        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            if calls["n"] == 1:
                return _jira("A fazer")
            if calls["n"] == 2:
                return _jira("Em andamento")
            return _jira("Feito")

        spoken = []
        service = RadarService(speak=spoken.append, bus=None, lock=None, fetch=fetch, cooldown=0)
        self.assertEqual(service.tick(NOW), "")
        heard = service.tick(LATER)
        self.assertIn("Em andamento", heard)
        self.assertEqual(silence("today", LATER), "Silenciei esse aviso até o fim do dia, senhor.")
        self.assertEqual(service.tick(LATER + timedelta(minutes=5)), "")
        stored = load()
        self.assertEqual(stored["radar"]["jira"]["ABC-1"], "Em andamento")
        self.assertIn("jira:ABC-1", stored["alerts"]["today"]["2026-10-29"])
        tomorrow = service.tick(NEXT)
        self.assertIn("Feito", tomorrow)

        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        reply = brain.ask("pausa os alertas até amanhã")
        self.assertIn("até amanhã", reply)
        self.assertNotIn("\u2014", reply)
        self.assertTrue(load()["alerts"]["paused_until"])

    def test_silence_always_uses_a_different_store(self):
        from jarvis.radar import RadarService

        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            if calls["n"] == 1:
                return _jira("A fazer")
            if calls["n"] == 2:
                return _jira("Em andamento")
            return _jira("Feito")

        service = RadarService(speak=lambda _text: None, bus=None, lock=None, fetch=fetch, cooldown=0)
        service.tick(NOW)
        service.tick(LATER)
        self.assertIn("de vez", silence("always", LATER))
        self.assertEqual(service.tick(LATER + timedelta(minutes=30)), "")
        self.assertEqual(load()["radar"]["jira"]["ABC-1"], "Feito")
        self.assertIn("jira:ABC-1", load()["alerts"]["always"])
        self.assertNotIn("Feito", json.dumps(load()["alerts"]))


class ReminderPauseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_STATE"] = str(self.tmp / "state.json")
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.note = self.vault / "lembretes.md"
        self.note.write_text(
            "- [ ] regar a samambaia de teste @ 2026-10-28 08:00\n"
            "- [ ] regar a samambaia de teste @ 2026-10-29 09:00\n",
            encoding="utf-8",
        )
        self.before = self.note.read_bytes()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _service(self, spoken):
        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False
                self.calls = []

            def resync_snapshot(self):
                self.calls.append("snap")

            def publish(self, text):
                self.calls.append(text)

            def hud_payload(self):
                return {}

        class Bus:
            def transcript(self, role, text):
                return None

            def state(self, value):
                return None

        self.fake = Vault(self.vault)
        return ReminderService(self.fake, spoken.append, Bus(), threading.RLock())

    def test_pause_does_not_mark_the_reminder(self):
        moment = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        self.assertIn("amanhã", pause_alerts(moment))
        spoken = []
        service = self._service(spoken)
        service.tick(moment)
        self.assertEqual(spoken, [])
        self.assertEqual(self.note.read_bytes(), self.before)
        self.assertEqual(self.fake.calls, [])

    def test_today_allows_the_same_reminder_tomorrow(self):
        moment = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        tomorrow = datetime(2026, 10, 29, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        spoken = []
        service = self._service(spoken)
        service.tick(moment)
        self.assertEqual(len(spoken), 1)
        self.assertIn("samambaia", spoken[0])
        self.assertIn("até o fim do dia", silence("today", moment))
        service.tick(tomorrow)
        self.assertEqual(len(spoken), 2)
        self.assertNotIn("\u2014", spoken[1])

    def test_always_marks_the_next_day_without_speaking(self):
        moment = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        tomorrow = datetime(2026, 10, 29, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        spoken = []
        service = self._service(spoken)
        service.tick(moment)
        self.assertEqual(len(spoken), 1)
        self.assertIn("de vez", silence("always", moment))
        service.tick(tomorrow)
        self.assertEqual(len(spoken), 1)
        text = self.note.read_text(encoding="utf-8")
        self.assertEqual(text.count("@avisado"), 2)


class FocusReasonTest(unittest.TestCase):
    def test_old_reminder_names_the_date(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "lembretes.md").write_text(
                "- [ ] devolver o livro emprestado @ 2026-09-01 09:00\n",
                encoding="utf-8",
            )
            moment = datetime(2026, 10, 28, 8, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
            speech = focus_speech(tmp, moment, jira_loader=lambda: None, github_loader=lambda: None)
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn(
            "lembrete atrasado: devolver o livro emprestado, está atrasado desde 1 de setembro.",
            speech,
        )
        self.assertNotIn("\u2014", speech)
        self.assertNotIn("\u2013", speech)
