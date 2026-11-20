import json
import os
import shutil
import stat
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

from jarvis import doctor
from jarvis.brain import Brain
from jarvis.chat import HELP
from jarvis.readwise import (
    FALTA_TOKEN,
    NADA_NOVO,
    PASTA_FORA,
    PASTA_OBSIDIAN,
    TOKEN_RECUSADO,
    import_highlights,
    state_path,
)
from jarvis.review import parse_card_line
from jarvis.routines import classify, help_speech, run_routine
from tests.test_vault import make_pair, show

TOKEN = "rw-sintetico"
NOW = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)
SECRET = "senha: abcdefghijklmnop"


def sample_book():
    return {
        "user_book_id": 41,
        "title": "Farol sintetico",
        "author": "Ada Exemplar",
        "source": "kindle",
        "source_url": "https://exemplo.test/farol",
        "book_tags": [{"name": "farol"}, {"name": "leitura"}],
        "highlights": [
            {
                "id": 7,
                "text": "Texto do destaque sintetico.",
                "note": "Anotacao sintetica.",
                "tags": [{"name": "farol"}],
            },
            {
                "id": 8,
                "text": "Outro destaque sintetico.",
                "note": "",
                "tags": [],
            },
            {
                "id": 9,
                "text": "Destaque com cartao pronto.",
                "note": "Qual a tese? ::: A tese e sintetica.",
                "tags": [],
            },
            {
                "id": 10,
                "text": SECRET,
                "note": "",
                "tags": [],
            },
        ],
    }


class Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Transport:
    def __init__(self, pages):
        self.pages = list(pages)
        self.urls = []
        self.headers = []

    def __call__(self, request, timeout=30):
        del timeout
        self.urls.append(request.full_url)
        self.headers.append(request.get_header("Authorization"))
        payload = self.pages.pop(0) if self.pages else {"results": [], "nextPageCursor": None}
        return Response(payload)


class ReadwiseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        self.vault.mkdir()
        self.keys = (
            "JARVIS_HOME",
            "JARVIS_VAULT",
            "JARVIS_VAULT_REMOTE",
            "JARVIS_VAULT_SYNC",
            "JARVIS_READWISE_PASTA",
            "JARVIS_PROMPT_FILE",
            "JARVIS_WORKSPACE",
            "READWISE_TOKEN",
        )
        self.saved = {key: os.environ.get(key) for key in self.keys}
        for key in self.keys:
            os.environ.pop(key, None)
        os.environ["JARVIS_HOME"] = str(self.home)
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "workspace")
        os.environ["READWISE_TOKEN"] = TOKEN

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_importa_uma_nota_por_livro_sem_duplicar(self):
        page = {"results": [sample_book()], "nextPageCursor": None}
        first = Transport([page])
        result = import_highlights(self.vault, now=NOW, opener=first)
        self.assertTrue(result.ok)
        self.assertIn("Importei 3 destaques em 1 nota", result.speech)
        self.assertIn("Um trecho foi recusado", result.speech)
        note = self.vault / "Leituras" / "Readwise" / "farol-sintetico-41.md"
        text = note.read_text(encoding="utf-8")
        self.assertIn('title: "Farol sintetico"', text)
        self.assertIn('author: "Ada Exemplar"', text)
        self.assertIn('source: "kindle"', text)
        self.assertIn('url: "https://exemplo.test/farol"', text)
        self.assertIn('  - "farol"', text)
        self.assertIn('  - "leitura"', text)
        self.assertEqual(text.count('  - "farol"'), 1)
        self.assertIn("readwise_id: 41", text)
        self.assertIn("# Farol sintetico", text)
        self.assertIn("> Texto do destaque sintetico.", text)
        self.assertIn("> Outro destaque sintetico.", text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(TOKEN, text)
        self.assertEqual(text.count("<!-- rw:7 -->"), 1)
        self.assertEqual(text.count("<!-- rw:8 -->"), 1)
        self.assertEqual(text.count("<!-- rw:9 -->"), 1)
        self.assertEqual(text.count("<!-- rw:10 -->"), 0)
        self.assertIn("Qual a tese? ::: A tese e sintetica.", text)
        generated = [
            line
            for line in text.splitlines()
            if ":::" in line and "Qual a tese?" not in line
        ]
        self.assertEqual(len(generated), 1)
        parsed = parse_card_line(generated[0])
        self.assertEqual(parsed[1], "Anotacao sintetica.")
        self.assertNotIn(":::", "\n".join(
            line for line in text.splitlines() if "Outro destaque" in line or line.startswith("> Outro")
        ))
        quote_eight = next(line for line in text.splitlines() if "Outro destaque" in line)
        self.assertTrue(quote_eight.startswith("> "))
        self.assertNotIn(":::", quote_eight)

        again = Transport([page])
        second = import_highlights(self.vault, now=NOW, opener=again)
        self.assertIn(NADA_NOVO, second.speech)
        self.assertIn("Um trecho foi recusado", second.speech)
        self.assertEqual(note.read_text(encoding="utf-8"), text)
        self.assertEqual(text.count("<!-- rw:7 -->"), 1)
        self.assertNotIn(TOKEN, again.urls[0])
        self.assertTrue(again.headers[0].endswith(TOKEN))
        self.assertIn("updatedAfter", again.urls[0])
        self.assertNotIn("updatedAfter", first.urls[0])
        state = json.loads(state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["updated_after"], "2026-11-11T15:00:00Z")
        self.assertEqual(state["page_cursor"], "")
        self.assertNotIn(TOKEN, state_path().read_text(encoding="utf-8"))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(state_path().stat().st_mode) & 0o077, 0)

        revised = sample_book()
        revised["highlights"][0]["text"] = "Texto revisado sintetico."
        third = Transport([{"results": [revised], "nextPageCursor": None}])
        updated = import_highlights(self.vault, now=NOW, opener=third)
        self.assertIn("Atualizei 1 em 1 nota", updated.speech)
        rewritten = note.read_text(encoding="utf-8")
        self.assertEqual(rewritten.count("<!-- rw:7 -->"), 1)
        self.assertIn("> Texto revisado sintetico.", rewritten)
        self.assertNotIn("> Texto do destaque sintetico.", rewritten)
        self.assertEqual(rewritten.count("Anotacao sintetica."), 2)

    def test_cursor_incremental_e_pagina(self):
        first = Transport(
            [
                {
                    "results": [
                        {
                            "user_book_id": 41,
                            "title": "Farol sintetico",
                            "author": "Ada Exemplar",
                            "source": "kindle",
                            "source_url": "https://exemplo.test/farol",
                            "book_tags": [],
                            "highlights": [
                                {"id": 7, "text": "Primeira pagina sintetica.", "note": ""}
                            ],
                        }
                    ],
                    "nextPageCursor": "cursor-sintetico",
                },
                {
                    "results": [
                        {
                            "user_book_id": 42,
                            "title": "Segundo livro sintetico",
                            "author": "Ada Exemplar",
                            "source": "reader",
                            "source_url": "https://exemplo.test/segundo",
                            "book_tags": [],
                            "highlights": [
                                {"id": 11, "text": "Segunda pagina sintetica.", "note": "Nota da segunda."}
                            ],
                        }
                    ],
                    "nextPageCursor": None,
                },
            ]
        )
        result = import_highlights(self.vault, now=NOW, opener=first)
        self.assertIn("Importei 2 destaques em 2 notas", result.speech)
        self.assertIn("pageCursor=cursor-sintetico", first.urls[1])
        self.assertNotIn(TOKEN, first.urls[0] + first.urls[1])
        second_note = self.vault / "Leituras" / "Readwise" / "segundo-livro-sintetico-42.md"
        second_text = second_note.read_text(encoding="utf-8")
        self.assertIn("Nota da segunda.", second_text)
        self.assertEqual(second_text.count(":::"), 1)
        state = json.loads(state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["page_cursor"], "")
        self.assertEqual(state["updated_after"], "2026-11-11T15:00:00Z")

        follow = Transport([{"results": [], "nextPageCursor": None}])
        empty = import_highlights(self.vault, now=NOW, opener=follow)
        self.assertEqual(empty.speech, NADA_NOVO)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(follow.urls[0]).query)
        self.assertEqual(query["updatedAfter"], ["2026-11-11T15:00:00Z"])
        self.assertNotIn(TOKEN, follow.urls[0])

    def test_falha_no_meio_guarda_o_cursor_sem_o_token(self):
        def opener(request, timeout=30):
            del timeout
            if "pageCursor" not in request.full_url:
                return Response(
                    {
                        "results": [
                            {
                                "user_book_id": 41,
                                "title": "Farol sintetico",
                                "author": "Ada Exemplar",
                                "source": "kindle",
                                "source_url": "",
                                "highlights": [
                                    {"id": 7, "text": "Primeira pagina sintetica.", "note": ""}
                                ],
                            }
                        ],
                        "nextPageCursor": "cursor-sintetico",
                    }
                )
            raise urllib.error.URLError("rede")

        with self.assertLogs("jarvis", level="ERROR") as logs:
            result = import_highlights(self.vault, now=NOW, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("Não consegui buscar", result.speech)
        self.assertNotIn(TOKEN, result.speech)
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        state = json.loads(state_path().read_text(encoding="utf-8"))
        self.assertEqual(state["page_cursor"], "cursor-sintetico")
        self.assertEqual(state["updated_after"], "")
        self.assertTrue((self.vault / "Leituras" / "Readwise" / "farol-sintetico-41.md").is_file())

    def test_token_ausente_ou_recusado_nao_grava(self):
        os.environ.pop("READWISE_TOKEN", None)
        called = []

        def opener(request, timeout=30):
            del request, timeout
            called.append(True)
            raise AssertionError("nao deveria consultar")

        missing = import_highlights(self.vault, now=NOW, opener=opener)
        self.assertEqual(missing.speech, FALTA_TOKEN)
        self.assertFalse(missing.ok)
        self.assertEqual(called, [])
        self.assertFalse(state_path().exists())

        os.environ["READWISE_TOKEN"] = TOKEN

        def denied(request, timeout=30):
            del timeout
            raise urllib.error.HTTPError(
                "https://readwise.io/api/v2/export/",
                401,
                "Unauthorized",
                Message(),
                None,
            )

        with self.assertLogs("jarvis", level="ERROR") as logs:
            refused = import_highlights(self.vault, now=NOW, opener=denied)
        self.assertEqual(refused.speech, TOKEN_RECUSADO)
        self.assertNotIn(TOKEN, refused.speech)
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.assertFalse(state_path().exists())
        self.assertFalse((self.vault / "Leituras").exists())

    def test_pasta_fora_do_vault_e_obsidian_nao_gravam(self):
        def opener(request, timeout=30):
            del request, timeout
            raise AssertionError("nao deveria consultar")

        os.environ["JARVIS_READWISE_PASTA"] = "../fora"
        outside = import_highlights(self.vault, now=NOW, opener=opener)
        self.assertEqual(outside.speech, PASTA_FORA)
        self.assertFalse((self.tmp / "fora").exists())

        os.environ["JARVIS_READWISE_PASTA"] = ".obsidian/notas"
        blocked = import_highlights(self.vault, now=NOW, opener=opener)
        self.assertEqual(blocked.speech, PASTA_OBSIDIAN)
        self.assertFalse((self.vault / ".obsidian").exists())

        os.environ["JARVIS_READWISE_PASTA"] = "Sinteticas/Destaques"
        page = {
            "results": [
                {
                    "user_book_id": 41,
                    "title": "Farol sintetico",
                    "author": "Ada Exemplar",
                    "source": "kindle",
                    "source_url": "https://exemplo.test/farol",
                    "book_tags": [],
                    "highlights": [
                        {"id": 7, "text": "Texto do destaque sintetico.", "note": ""}
                    ],
                }
            ],
            "nextPageCursor": None,
        }
        placed = import_highlights(self.vault, now=NOW, opener=Transport([page]))
        self.assertTrue(placed.ok)
        self.assertTrue(
            (self.vault / "Sinteticas" / "Destaques" / "farol-sintetico-41.md").is_file()
        )

    def test_comando_e_ajuda(self):
        intent = classify("importa meus destaques")
        self.assertEqual(intent.kind, "readwise")
        self.assertEqual(classify("Importar os destaques do Readwise.").kind, "readwise")
        self.assertNotEqual(classify("o que voce sabe").kind, "readwise")
        self.assertIn("importa meus destaques", help_speech())
        self.assertIn("importa meus destaques", HELP)
        os.environ.pop("READWISE_TOKEN", None)
        reply = run_routine(self.vault, intent, NOW)
        self.assertEqual(reply, FALTA_TOKEN)
        self.assertFalse(list(self.vault.rglob("*.md")))

    def test_comando_de_voz_grava_e_envia(self):
        repos = self.tmp / "repos"
        repos.mkdir()
        bare, _work, local = make_pair(repos)
        os.environ["JARVIS_VAULT"] = str(local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        page = {
            "results": [
                {
                    "user_book_id": 41,
                    "title": "Farol sintetico",
                    "author": "Ada Exemplar",
                    "source": "kindle",
                    "source_url": "https://exemplo.test/farol",
                    "book_tags": [{"name": "farol"}],
                    "highlights": [
                        {
                            "id": 7,
                            "text": "Texto do destaque sintetico.",
                            "note": "Anotacao sintetica.",
                        }
                    ],
                }
            ],
            "nextPageCursor": None,
        }

        import jarvis.readwise as readwise

        original = readwise.urlopen
        readwise.urlopen = Transport([page])
        try:
            brain = Brain()
            reply = brain.ask("importa meus destaques")
        finally:
            readwise.urlopen = original
        self.assertIn("Importei 1 destaque em 1 nota", reply)
        self.assertNotIn(TOKEN, reply)
        stored = show(bare, "main:Leituras/Readwise/farol-sintetico-41.md")
        self.assertIn("> Texto do destaque sintetico.", stored)
        self.assertIn("Anotacao sintetica.", stored)
        self.assertNotIn(TOKEN, stored)
        self.assertNotIn(SECRET, stored)
        log = __import__("subprocess").run(
            ["git", "--git-dir", str(bare), "log", "-1", "--format=%s"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("importa meus destaques", log.stdout)
        self.assertNotIn(TOKEN, log.stdout)

    def test_cli_sem_token_e_com_sync(self):
        from jarvis.readwise import main

        os.environ.pop("READWISE_TOKEN", None)
        code = main([])
        self.assertEqual(code, 1)

        os.environ["READWISE_TOKEN"] = TOKEN
        code = main([])
        self.assertEqual(code, 1)

        repos = self.tmp / "repos-cli"
        repos.mkdir()
        bare, _work, local = make_pair(repos)
        os.environ["JARVIS_VAULT"] = str(local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        page = {
            "results": [
                {
                    "user_book_id": 41,
                    "title": "Farol sintetico",
                    "author": "Ada Exemplar",
                    "source": "article",
                    "source_url": "https://exemplo.test/farol",
                    "book_tags": [],
                    "highlights": [
                        {"id": 7, "text": "Texto do destaque sintetico.", "note": ""}
                    ],
                }
            ],
            "nextPageCursor": None,
        }
        code = main([], opener=Transport([page]), now=NOW)
        self.assertEqual(code, 0)
        stored = show(bare, "main:Leituras/Readwise/farol-sintetico-41.md")
        self.assertIn("> Texto do destaque sintetico.", stored)
        self.assertNotIn(":::", stored)
        self.assertNotIn(TOKEN, stored)
        missing = __import__("subprocess").run(
            ["git", "--git-dir", str(bare), "cat-file", "-e", "main:.obsidian/app.json"],
            capture_output=True,
        )
        self.assertNotEqual(missing.returncode, 0)

    def test_doctor_nao_mostra_o_token(self):
        doctor.results.clear()
        text = []

        def capture():
            import io
            from contextlib import redirect_stdout

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                doctor.check_integrations(github_state="missing", env={"READWISE_TOKEN": TOKEN})
            text.append(buffer.getvalue())

        capture()
        self.assertIn("Readwise: token presente", text[0])
        self.assertNotIn(TOKEN, text[0])
        doctor.results.clear()

    def test_fontes_sem_traco_longo(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "jarvis/readwise.py",
            "tests/test_readwise.py",
        ):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)
        self.assertNotIn(TOKEN, (root / "jarvis" / "readwise.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
