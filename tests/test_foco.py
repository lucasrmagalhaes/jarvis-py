import json
import os
import stat
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.capture import save_drop
from jarvis.journal import history_speech, read_day, record
from jarvis.routines import classify, focus_speech, run_routine

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 8, 0, tzinfo=TZ)
EXTERNAL = (
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "JARVIS_GH_BIN",
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_WORKSPACE",
    "GH_CALLS",
)


class FocusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.saved = {key: os.environ.get(key) for key in EXTERNAL}
        for key in EXTERNAL:
            os.environ.pop(key, None)
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        (self.vault / "lembretes.md").write_text(
            "- [ ] pagar o boleto @ 2026-10-27 09:00\n"
            "- [ ] ligar para o cliente @ 2026-10-28 18:00\n"
            "- [x] feito @ 2026-10-27 08:00\n",
            encoding="utf-8",
        )
        agenda = self.vault / "Agenda Profissional"
        agenda.mkdir()
        (agenda / "2026-10-28.md").write_text(
            "15:00 revisão com o cliente\n- [ ] enviar proposta\n",
            encoding="utf-8",
        )

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_top_three_cross_reminders_and_agenda_without_writing(self):
        import jarvis.external as external

        called = []
        original = external.mail_speech

        def boom(*_args, **_kwargs):
            called.append("mail")
            return "enviou"

        external.mail_speech = boom
        before = self._files()
        try:
            speech = run_routine(self.vault, classify("quais são minhas prioridades hoje?"), NOW)
        finally:
            external.mail_speech = original
        self.assertEqual(called, [])
        self.assertEqual(before, self._files())
        self.assertTrue(speech.startswith("Três prioridades hoje, senhor."))
        self.assertIn(
            "Primeira, lembrete atrasado: pagar o boleto, está atrasado desde terça.",
            speech,
        )
        self.assertIn(
            "Segunda, agenda às 15: revisão com o cliente, está marcado para as 15.",
            speech,
        )
        self.assertIn(
            "Terceira, lembrete às 18: ligar para o cliente, está marcado para as 18.",
            speech,
        )
        self.assertIn("Há mais além dessas três.", speech)
        self.assertNotIn("enviar proposta", speech)
        self.assertNotIn("feito", speech)
        self.assertNotIn("\u2014", speech)
        self.assertNotIn("Jira", speech)
        self.assertNotIn("PR", speech)

    def test_top_three_put_review_and_jira_ahead_of_later_agenda(self):
        os.environ["JIRA_URL"] = "https://example.atlassian.net"
        os.environ["JIRA_EMAIL"] = "pessoa@example.com"
        os.environ["JIRA_TOKEN"] = "token-secreto"
        script = self.tmp / "gh"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "path = os.environ['GH_CALLS']\n"
            "with open(path, 'a', encoding='utf-8') as handle:\n"
            "    handle.write('\\t'.join(sys.argv[1:]) + '\\n')\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['auth', 'status']:\n"
            "    raise SystemExit(0)\n"
            "if '--review-requested=@me' in args:\n"
            "    json.dump([{'number': 4, 'title': 'Revisar vault', "
            "'repository': {'nameWithOwner': 'exemplo/vault'}}], sys.stdout)\n"
            "    raise SystemExit(0)\n"
            "if '--author=@me' in args:\n"
            "    json.dump([{'number': 12, 'title': 'Ajuste do HUD', "
            "'repository': {'nameWithOwner': 'exemplo/jarvis'}}], sys.stdout)\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        os.environ["JARVIS_GH_BIN"] = str(script)
        os.environ["GH_CALLS"] = str(self.tmp / "calls.log")
        seen = {}

        class Response:
            def read(self):
                return json.dumps(
                    {
                        "issues": [
                            {
                                "key": "ABC-1",
                                "fields": {
                                    "summary": "Subir o HUD",
                                    "status": {
                                        "name": "Em andamento",
                                        "statusCategory": {"key": "indeterminate"},
                                    },
                                },
                            },
                            {
                                "key": "ABC-2",
                                "fields": {
                                    "summary": "Revisar o texto",
                                    "status": {"name": "A fazer", "statusCategory": {"key": "new"}},
                                },
                            },
                            {
                                "key": "ABC-3",
                                "fields": {
                                    "summary": "Fechada",
                                    "status": {"name": "Concluída", "statusCategory": {"key": "done"}},
                                },
                            },
                        ]
                    }
                ).encode()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, timeout=15):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            self.assertEqual(timeout, 15)
            return Response()

        original = urllib.request.urlopen
        urllib.request.urlopen = opener
        try:
            speech = run_routine(self.vault, classify("foco do dia"), NOW)
        finally:
            urllib.request.urlopen = original
        self.assertEqual(seen["method"], "GET")
        self.assertNotIn("token-secreto", seen["url"])
        self.assertNotIn("token-secreto", speech)
        self.assertIn(
            "Primeira, lembrete atrasado: pagar o boleto, está atrasado desde terça.",
            speech,
        )
        self.assertIn(
            "Segunda, review pendente: exemplo/vault 4, Revisar vault, há review pedido.",
            speech,
        )
        self.assertIn(
            "Terceira, no Jira em andamento: ABC-1 Subir o HUD, está em andamento.",
            speech,
        )
        self.assertNotIn("revisão com o cliente", speech)
        self.assertNotIn("Ajuste do HUD", speech)
        self.assertNotIn("ABC-2", speech)
        self.assertNotIn("ABC-3", speech)
        calls = (self.tmp / "calls.log").read_text(encoding="utf-8").splitlines()
        parts = [part for line in calls for part in line.split("\t")]
        for forbidden in ("create", "comment", "merge", "close", "review"):
            self.assertNotIn(forbidden, parts)
        self.assertTrue(any(line.startswith("search\tprs") for line in calls))

    def test_missing_external_source_is_a_short_clause(self):
        speech = focus_speech(
            self.vault,
            NOW,
            jira_loader=lambda: False,
            github_loader=lambda: None,
        )
        self.assertIn("pagar o boleto", speech)
        self.assertIn("Não consegui consultar o Jira.", speech)
        self.assertNotIn("Não consegui consultar os PRs.", speech)

    def test_without_vault_only_reads_jira_and_pulls(self):
        speech = focus_speech(
            None,
            NOW,
            jira_loader=lambda: [{"label": "ABC-9 Item", "bucket": "progress"}],
            github_loader=lambda: None,
        )
        self.assertIn("Sem o vault eu não li lembretes nem agenda", speech)
        self.assertIn("ABC-9 Item", speech)
        empty = focus_speech(None, NOW, jira_loader=lambda: None, github_loader=lambda: None)
        self.assertIn("Não há prioridade marcada para hoje", empty)

    def _files(self):
        found = {}
        for path in self.vault.rglob("*"):
            if path.is_file():
                found[path.relative_to(self.vault).as_posix()] = path.read_bytes()
        return found


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.saved = {key: os.environ.get(key) for key in EXTERNAL}
        for key in EXTERNAL:
            os.environ.pop(key, None)
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

    def test_yesterday_comes_from_the_log_and_not_from_claude(self):
        from jarvis.brain import Brain

        yesterday = datetime(2026, 10, 29, 21, 4, tzinfo=TZ)
        today = datetime(2026, 10, 30, 9, 0, tzinfo=TZ)
        record("me lembra de pagar o boleto", yesterday)
        record("o que tenho hoje", today)
        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        brain.clock = lambda: today
        reply = brain.ask("o que eu te pedi ontem?")
        self.assertIn("Ontem o senhor pediu: me lembra de pagar o boleto.", reply)
        self.assertNotIn("o que tenho hoje", reply)
        self.assertNotIn("o que eu te pedi ontem", reply)
        self.assertNotIn("\u2014", reply)
        logged = "\n".join(read_day(today.date()))
        self.assertIn("o que eu te pedi ontem", logged)
        self.assertNotIn("Não há pedido", logged)
        self.assertNotIn("pagar o boleto", logged)
        again = brain.ask("o que eu te pedi hoje")
        self.assertIn("o que tenho hoje", again)
        self.assertIn("o que eu te pedi ontem", again)
        self.assertNotIn("o que eu te pedi hoje", again)
        path = self.tmp / "home" / "logs" / "interacoes" / "2026-10-30.log"
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.tmp / "ws" / "logs").exists())

    def test_day_follows_sao_paulo_when_the_clock_is_utc(self):
        from jarvis.brain import Brain

        record("ligar para a oficina", datetime(2026, 10, 28, 18, 0, tzinfo=TZ))
        brain = Brain()
        brain._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("claude"))
        brain.clock = lambda: datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)
        reply = brain.ask("o que eu te pedi ontem?")
        self.assertIn("oficina", reply)
        hoje = history_speech(datetime(2026, 10, 30, 9, 0, tzinfo=TZ), "hoje")
        self.assertIn("Não há pedido registrado hoje", hoje)

    def test_old_days_are_pruned(self):
        folder = self.tmp / "home" / "logs" / "interacoes"
        folder.mkdir(parents=True)
        old = folder / "2020-01-01.log"
        old.write_text('{"em": "2020-01-01T08:00:00-03:00", "pedido": "velho"}\n', encoding="utf-8")
        record("agora", NOW)
        self.assertFalse(old.exists())
        self.assertIn("agora", read_day(NOW.date()))


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp())
        self.saved = {key: os.environ.get(key) for key in EXTERNAL}
        for key in EXTERNAL:
            os.environ.pop(key, None)
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        obs = self.vault / ".obsidian"
        obs.mkdir()
        (obs / "app.json").write_text("{}\n", encoding="utf-8")
        (self.vault / "AGENTS.md").write_text(
            "inbox de notas: `.obsidian/Notas`\n",
            encoding="utf-8",
        )

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rejected_folder_falls_back_and_does_not_touch_obsidian(self):
        speech = save_drop(
            self.vault,
            {
                "kind": "link",
                "url": "https://example.com/a",
                "title": "Manual",
                "tags": ["docs"],
            },
            NOW,
        )
        note = self.vault / "Jarvis" / "Notas" / "2026-10-28-080000-manual.md"
        self.assertTrue(note.is_file(), speech)
        body = note.read_text(encoding="utf-8")
        self.assertIn("titulo: Manual", body)
        self.assertIn("  - inbox", body)
        self.assertIn("  - docs", body)
        self.assertIn("https://example.com/a", body)
        self.assertNotIn("senhor", body.casefold())
        self.assertIn("Jarvis/Notas/2026-10-28-080000-manual.md", speech)
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_text(encoding="utf-8"), "{}\n")
        self.assertEqual(list((self.vault / ".obsidian").rglob("*.md")), [])
        logged = read_day(NOW.date())
        self.assertIn("https://example.com/a Manual", logged)
        self.assertFalse(any("senhor" in line.casefold() for line in logged))
        self.assertFalse(any("Guardei" in line for line in logged))

        huge = self.tmp / "huge.jpg"
        huge.write_bytes(b"x" * (8_000_000 + 1))
        refused = save_drop(
            self.vault,
            {"kind": "photo", "path": huge, "suffix": ".jpg", "title": "Grande", "tags": []},
            NOW,
        )
        self.assertIn("grande demais", refused)
        self.assertFalse((self.vault / "Jarvis" / "Notas" / "anexos").exists())
        blocked = save_drop(
            self.vault,
            {"kind": "link", "url": "https://example.com/b", "title": "Outro", "tags": []},
            NOW,
            read_only=True,
        )
        self.assertIn("bloqueado", blocked)
        names = [path.name for path in (self.vault / "Jarvis" / "Notas").glob("*.md")]
        self.assertEqual(names, ["2026-10-28-080000-manual.md"])
        self.assertEqual((self.vault / ".obsidian" / "app.json").read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
