import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.external import github_review_sample, important_mail_sample, jira_status_sample
from jarvis.radar import RadarService, decide

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=20)
ENV = (
    "JARVIS_STATE",
    "JARVIS_GH_BIN",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "GH_CALLS",
)


class RadarDecideTest(unittest.TestCase):
    def test_first_look_is_silent_and_a_change_speaks_once(self):
        samples = {
            "github": ("ok", [{"id": "exemplo/jarvis#12", "label": "exemplo/jarvis 12, HUD"}]),
            "jira": ("ok", [{"key": "ABC-1", "status": "A fazer", "summary": "Subir"}]),
            "mail": ("ok", [{"id": "m0", "sender": "Ana", "subject": "Antigo"}]),
        }
        speech, state = decide({}, samples, NOW, 900)
        self.assertEqual(speech, "")
        self.assertEqual(state["github"], ["exemplo/jarvis#12"])
        self.assertEqual(state["jira"]["ABC-1"], "A fazer")
        self.assertNotIn("HUD", json.dumps(state))
        self.assertNotIn("Subir", json.dumps(state))

        samples["github"] = (
            "ok",
            [
                {"id": "exemplo/jarvis#12", "label": "exemplo/jarvis 12, HUD"},
                {"id": "exemplo/jarvis#13", "label": "exemplo/jarvis 13, Voz"},
            ],
        )
        samples["jira"] = (
            "ok",
            [{"key": "ABC-1", "status": "Em revisão", "summary": "Subir o HUD"}],
        )
        samples["mail"] = (
            "ok",
            [{"id": "m1", "sender": "Ana", "subject": "Boleto"}],
        )
        again, nxt = decide(state, samples, NOW, 900)
        self.assertIn("review pedido", again)
        self.assertIn("exemplo/jarvis 13, Voz", again)
        self.assertIn("ABC-1 mudou para Em revisão", again)
        self.assertIn("Subir o HUD", again)
        self.assertIn("Ana", again)
        self.assertIn("Boleto", again)
        self.assertNotIn("\u2014", again)
        self.assertIn("exemplo/jarvis#13", nxt["github"])
        self.assertEqual(nxt["jira"]["ABC-1"], "Em revisão")
        self.assertIn("m0", nxt["mail"])
        self.assertIn("m1", nxt["mail"])
        self.assertNotIn("Boleto", json.dumps(nxt))
        self.assertNotIn("Antigo", json.dumps(nxt))

        quiet, kept = decide(nxt, samples, LATER, 900)
        self.assertEqual(quiet, "")
        self.assertEqual(kept["jira"]["ABC-1"], "Em revisão")

    def test_new_jira_key_does_not_speak_and_cooldown_holds_the_change(self):
        state = {
            "seeded": {"github": True, "jira": True, "mail": True},
            "github": [],
            "jira": {"ABC-1": "A fazer"},
            "mail": [],
            "last_spoken": NOW.isoformat(),
        }
        samples = {
            "github": ("off", []),
            "jira": (
                "ok",
                [
                    {"key": "ABC-1", "status": "Feito", "summary": "Subir"},
                    {"key": "ABC-2", "status": "A fazer", "summary": "Nova"},
                ],
            ),
            "mail": ("off", []),
        }
        held, kept = decide(state, samples, NOW + timedelta(minutes=5), 900)
        self.assertEqual(held, "")
        self.assertEqual(kept["jira"]["ABC-1"], "A fazer")
        self.assertNotIn("ABC-2", kept["jira"])

        speech, nxt = decide(kept, samples, LATER, 900)
        self.assertIn("ABC-1 mudou para Feito", speech)
        self.assertNotIn("ABC-2", speech)
        self.assertEqual(nxt["jira"]["ABC-2"], "A fazer")
        self.assertEqual(nxt["jira"]["ABC-1"], "Feito")

    def test_cap_and_error_do_not_wipe_or_drip(self):
        state = {
            "seeded": {"github": True, "jira": True, "mail": True},
            "github": [],
            "jira": {},
            "mail": [],
            "last_spoken": "",
        }
        items = [
            {"id": f"exemplo/jarvis#{number}", "label": f"PR {number}"}
            for number in range(1, 5)
        ]
        speech, nxt = decide({"seeded": state["seeded"], "github": [], "jira": {}, "mail": [], "last_spoken": ""}, {"github": ("ok", items), "jira": ("error", []), "mail": ("error", [])}, NOW, 900)
        self.assertIn("PR 1", speech)
        self.assertIn("PR 3", speech)
        self.assertNotIn("PR 4.", speech)
        self.assertIn("E mais 1", speech)
        self.assertEqual(len(nxt["github"]), 4)
        failed, kept = decide(nxt, {"github": ("error", []), "jira": ("ok", []), "mail": ("off", [])}, LATER, 900)
        self.assertEqual(failed, "")
        self.assertEqual(kept["github"], nxt["github"])

    def test_login_later_still_seeds_without_speaking(self):
        speech, state = decide({}, {"github": ("off", []), "jira": ("off", []), "mail": ("off", [])}, NOW, 900)
        self.assertEqual(speech, "")
        self.assertFalse(state["seeded"]["github"])
        quiet, nxt = decide(
            state,
            {"github": ("ok", [{"id": "exemplo/jarvis#9", "label": "PR 9"}]), "jira": ("off", []), "mail": ("off", [])},
            LATER,
            900,
        )
        self.assertEqual(quiet, "")
        self.assertEqual(nxt["github"], ["exemplo/jarvis#9"])


class RadarServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_STATE"] = str(self.tmp / "state.json")

    def tearDown(self):
        import shutil

        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tick_speaks_once_by_voice_and_telegram(self):
        spoken = []
        sent = []
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "github": ("ok", [{"id": "exemplo/jarvis#1", "label": "PR 1"}]),
                    "jira": ("off", []),
                    "mail": ("off", []),
                }
            return {
                "github": (
                    "ok",
                    [
                        {"id": "exemplo/jarvis#1", "label": "PR 1"},
                        {"id": "exemplo/jarvis#2", "label": "PR 2"},
                    ],
                ),
                "jira": ("off", []),
                "mail": ("off", []),
            }

        class Bus:
            def __init__(self):
                self.events = []

            def transcript(self, role, text):
                self.events.append((role, text))

            def state(self, value):
                self.events.append(("state", value))

        bus = Bus()
        service = RadarService(
            speak=spoken.append,
            bus=bus,
            lock=None,
            also=sent.append,
            fetch=fetch,
            cooldown=900,
        )
        self.assertEqual(service.tick(NOW), "")
        self.assertEqual(spoken, [])
        heard = service.tick(LATER)
        self.assertIn("PR 2", heard)
        self.assertEqual(spoken, [heard])
        self.assertEqual(sent, [heard])
        self.assertEqual(service.tick(LATER + timedelta(minutes=20)), "")
        self.assertEqual(len(spoken), 1)
        stored = json.loads((self.tmp / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn("PR 2", json.dumps(stored["radar"]["github"]))


class RadarSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)

    def tearDown(self):
        import shutil

        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sources_do_not_send_mail_or_force_push(self):
        for name in ("jarvis/external.py", "jarvis/radar.py", "jarvis/doctor.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("smtplib", text, name)
            self.assertNotIn("sendmail", text, name)
            self.assertNotIn("--force", text, name)
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)

    def test_github_review_sample_is_read_only(self):
        script = self.tmp / "gh"
        calls = self.tmp / "calls.log"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "path = os.environ['GH_CALLS']\n"
            "with open(path, 'a', encoding='utf-8') as handle:\n"
            "    handle.write('\\t'.join(sys.argv[1:]) + '\\n')\n"
            "args = sys.argv[1:]\n"
            "if args[:2] == ['auth', 'status']:\n"
            "    raise SystemExit(0)\n"
            "if args[:2] == ['search', 'prs']:\n"
            "    json.dump([\n"
            "        {'number': 12, 'title': 'HUD', 'url': 'https://github.com/exemplo/jarvis/pull/12',\n"
            "         'repository': {'nameWithOwner': 'exemplo/jarvis'}},\n"
            "        {'number': 4, 'title': 'Sem review', 'url': 'https://github.com/exemplo/jarvis/pull/4',\n"
            "         'repository': {'nameWithOwner': 'exemplo/jarvis'}}\n"
            "    ], sys.stdout)\n"
            "    raise SystemExit(0)\n"
            "if args[:2] == ['pr', 'view'] and args[2] == '12':\n"
            "    json.dump({'title': 'HUD', 'reviewRequests': [{'login': 'ana'}]}, sys.stdout)\n"
            "    raise SystemExit(0)\n"
            "if args[:2] == ['pr', 'view']:\n"
            "    json.dump({'title': 'Sem review', 'reviewRequests': []}, sys.stdout)\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        os.environ["JARVIS_GH_BIN"] = str(script)
        os.environ["GH_CALLS"] = str(calls)
        status, items = github_review_sample()
        self.assertEqual(status, "ok")
        self.assertEqual(items, [{"id": "exemplo/jarvis#12", "label": "exemplo/jarvis 12, HUD"}])
        lines = calls.read_text(encoding="utf-8").splitlines()
        parts = [part for line in lines for part in line.split("\t")]
        for forbidden in ("comment", "review", "merge", "close", "approve", "create", "edit"):
            self.assertNotIn(forbidden, parts)
        self.assertTrue(any(line.startswith("pr\tview\t12") for line in lines))

    def test_jira_status_sample_is_get_only(self):
        os.environ["JIRA_URL"] = "https://example.atlassian.net"
        os.environ["JIRA_EMAIL"] = "pessoa@example.com"
        os.environ["JIRA_TOKEN"] = "token-secreto"
        seen = {}

        class Response:
            def read(self):
                return json.dumps(
                    {
                        "issues": [
                            {
                                "key": "ABC-9",
                                "fields": {
                                    "summary": "Fechar o dia",
                                    "status": {"name": "Em andamento"},
                                },
                            }
                        ]
                    }
                ).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, timeout=15):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["timeout"] = timeout
            return Response()

        status, items = jira_status_sample(opener=opener)
        self.assertEqual(status, "ok")
        self.assertEqual(items[0]["key"], "ABC-9")
        self.assertEqual(items[0]["status"], "Em andamento")
        self.assertEqual(seen["method"], "GET")
        self.assertIn("/rest/api/3/search/jql", seen["url"])
        self.assertNotIn("token-secreto", seen["url"])
        self.assertNotIn("PUT", seen["method"])

    def test_important_mail_peeks_and_hashes(self):
        os.environ["GMAIL_EMAIL"] = "pessoa@example.com"
        os.environ["GMAIL_APP_PASSWORD"] = "ab cd ef gh"
        calls = []

        class Fake:
            def login(self, user, password):
                calls.append(("login", user))

            def select(self, mailbox, readonly=False):
                calls.append(("select", mailbox, readonly))
                return "OK", [b"1"]

            def search(self, charset, *criteria):
                calls.append(("search", criteria))
                return "OK", [b"1"]

            def fetch(self, number, spec):
                calls.append(("fetch", spec))
                header = (
                    b"From: Ana <ana@example.com>\r\n"
                    b"Subject: Boleto\r\n"
                    b"Date: Wed, 28 Oct 2026 10:00:00 -0300\r\n"
                )
                return "OK", [(b"1", header)]

            def logout(self):
                calls.append(("logout",))

            def store(self, *_args):
                raise AssertionError("store")

            def append(self, *_args):
                raise AssertionError("append")

        status, items = important_mail_sample(connect=lambda host, port: Fake())
        self.assertEqual(status, "ok")
        self.assertEqual(calls[1], ("select", "INBOX", True))
        self.assertIn("X-GM-RAW", calls[2][1])
        self.assertIn("is:important is:unread", calls[2][1])
        self.assertIn("BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)]", calls[3][1])
        self.assertEqual(calls[-1], ("logout",))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["sender"].split()[0], "Ana")
        self.assertEqual(items[0]["subject"], "Boleto")
        self.assertEqual(len(items[0]["id"]), 16)
        digest = hashlib.sha256(
            (items[0]["sender"] + "\n" + items[0]["subject"] + "\n" + "Wed, 28 Oct 2026 10:00:00 -0300").encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        self.assertEqual(items[0]["id"], digest)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            failed_status, failed_items = important_mail_sample(
                connect=lambda host, port: (_ for _ in ()).throw(RuntimeError("senha ab cd ef gh"))
            )
        self.assertEqual(failed_status, "error")
        self.assertEqual(failed_items, [])
        self.assertNotIn("ab cd", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
