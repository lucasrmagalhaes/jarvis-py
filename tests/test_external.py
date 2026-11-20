import json
import os
import stat
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from jarvis.external import (
    GITHUB_FAIL,
    GITHUB_MISSING,
    JIRA_FAIL,
    JIRA_MISSING,
    MAIL_FAIL,
    MAIL_MISSING,
    github_speech,
    jira_speech,
    mail_speech,
)
from jarvis.routines import classify, run_routine

ROOT = Path(__file__).resolve().parents[1]
NOW_ENV = (
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "GMAIL_IMAP_HOST",
    "JARVIS_GH_BIN",
)


class ExternalTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in NOW_ENV}
        for key in NOW_ENV:
            os.environ.pop(key, None)
        self.tmp = Path(__import__("tempfile").mkdtemp())

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_config_is_a_short_phrase(self):
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        self.assertEqual(jira_speech(), JIRA_MISSING)
        self.assertEqual(github_speech(), GITHUB_MISSING)
        self.assertEqual(mail_speech(), MAIL_MISSING)
        self.assertNotIn("vault", jira_speech())

    def test_jira_reads_issues_without_putting_the_token_in_the_url(self):
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
                                    "status": {
                                        "name": "A fazer",
                                        "statusCategory": {"key": "new"},
                                    },
                                },
                            },
                            {
                                "key": "ABC-3",
                                "fields": {
                                    "summary": "Fechada",
                                    "status": {
                                        "name": "Concluída",
                                        "statusCategory": {"key": "done"},
                                    },
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
            seen["auth"] = request.get_header("Authorization")
            self.assertEqual(timeout, 15)
            return Response()

        speech = jira_speech(opener=opener)
        self.assertEqual(seen["method"], "GET")
        self.assertIn("/rest/api/3/search/jql", seen["url"])
        self.assertNotIn("token-secreto", seen["url"])
        self.assertNotIn("pessoa@example.com", seen["url"])
        self.assertTrue(seen["auth"].startswith("Basic "))
        self.assertIn("em andamento: ABC-1 Subir o HUD", speech)
        self.assertIn("a fazer: ABC-2 Revisar o texto", speech)
        self.assertNotIn("ABC-3", speech)
        self.assertNotIn("token-secreto", speech)

        def boom(_request, timeout=15):
            raise urllib.error.URLError("token-secreto")

        failed = jira_speech(opener=boom)
        self.assertEqual(failed, JIRA_FAIL)
        self.assertNotIn("token-secreto", failed)

    def test_briefing_includes_jira_only_when_configured(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        moment = datetime(2026, 10, 28, 8, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        plain = run_routine(self.tmp, classify("bom dia"), moment)
        self.assertNotIn("Jira", plain)
        os.environ["JIRA_URL"] = "https://example.atlassian.net"
        os.environ["JIRA_EMAIL"] = "pessoa@example.com"
        os.environ["JIRA_TOKEN"] = "token-secreto"
        original = urllib.request.urlopen

        class Response:
            def read(self):
                return b'{"issues": []}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        urllib.request.urlopen = lambda request, timeout=15: Response()
        try:
            brief = run_routine(self.tmp, classify("bom dia"), moment)
        finally:
            urllib.request.urlopen = original
        self.assertIn("No Jira, nada em aberto.", brief)
        self.assertIn("Bom dia", brief)

    def test_github_lists_open_prs_and_reviews_read_only(self):
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
        speech = github_speech()
        self.assertIn("exemplo/jarvis 12, Ajuste do HUD", speech)
        self.assertIn("exemplo/vault 4, Revisar vault", speech)
        calls = (self.tmp / "calls.log").read_text(encoding="utf-8").splitlines()
        self.assertTrue(all(line.startswith("auth\tstatus") or line.startswith("search\tprs") for line in calls))
        parts = [part for line in calls for part in line.split("\t")]
        for forbidden in ("create", "comment", "merge", "close", "review"):
            self.assertNotIn(forbidden, parts)
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        self.assertEqual(github_speech(briefing=True), "")

    def test_github_failure_stays_short(self):
        script = self.tmp / "gh"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if sys.argv[1:3] == ['auth', 'status']:\n"
            "    raise SystemExit(0)\n"
            "sys.stderr.write('token-secreto\\n')\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        os.environ["JARVIS_GH_BIN"] = str(script)
        speech = github_speech()
        self.assertEqual(speech, GITHUB_FAIL)
        self.assertNotIn("token-secreto", speech)

    def test_mail_reads_unseen_with_peek_and_never_sends(self):
        os.environ["GMAIL_EMAIL"] = "pessoa@example.com"
        os.environ["GMAIL_APP_PASSWORD"] = "ab cd ef gh"
        calls = []

        class Fake:
            def login(self, user, password):
                calls.append(("login", user, password))

            def select(self, mailbox, readonly=False):
                calls.append(("select", mailbox, readonly))
                return "OK", [b"1"]

            def search(self, charset, *criteria):
                calls.append(("search", criteria))
                return "OK", [b"1"]

            def fetch(self, number, spec):
                calls.append(("fetch", spec))
                header = b"From: Ana <ana@example.com>\r\nSubject: Boleto de outubro\r\n"
                return "OK", [(b"1", header)]

            def logout(self):
                calls.append(("logout",))

            def store(self, *_args):
                raise AssertionError("store")

            def append(self, *_args):
                raise AssertionError("append")

        speech = mail_speech(connect=lambda host, port: Fake())
        self.assertEqual(calls[0], ("login", "pessoa@example.com", "abcdefgh"))
        self.assertEqual(calls[1], ("select", "INBOX", True))
        fetched = next(item for item in calls if item[0] == "fetch")
        self.assertIn("BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]", fetched[1])
        self.assertEqual(calls[-1], ("logout",))
        self.assertNotIn("store", [item[0] for item in calls])
        self.assertIn("Ana", speech)
        self.assertIn("Boleto de outubro", speech)
        self.assertNotIn("abcdefgh", speech)

        class Boom:
            def login(self, user, password):
                raise RuntimeError("senha ab cd ef gh")

            def logout(self):
                calls.append(("boom-logout",))

        failed = mail_speech(connect=lambda host, port: Boom())
        self.assertEqual(failed, MAIL_FAIL)
        self.assertNotIn("ab cd", failed)
        self.assertIn(("boom-logout",), calls)
