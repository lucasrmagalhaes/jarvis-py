import json
import os
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis.brain import UNTRUSTED, VAULT_RULES
from jarvis.guardas import (
    FALA_BLOQUEIO,
    GuardError,
    arquivo_de_hooks,
    avaliar_ferramenta,
    caminho_bloqueado,
    escrever,
    main,
    texto_secreto,
)
from jarvis.routines import classify, run_routine

NOW = datetime(2026, 10, 28, 11, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


class GuardaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._home = os.environ.get("JARVIS_HOME")
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        self.addCleanup(self._restore_home)

    def _restore_home(self):
        if self._home is None:
            os.environ.pop("JARVIS_HOME", None)
        else:
            os.environ["JARVIS_HOME"] = self._home

    def test_bloqueia_obsidian_credencial_e_segredo(self):
        self.assertIsNotNone(caminho_bloqueado(self.tmp / ".obsidian" / "app.json"))
        self.assertIsNotNone(caminho_bloqueado(self.tmp / "notas" / ".env"))
        self.assertIsNotNone(caminho_bloqueado(self.tmp / "id_rsa"))
        self.assertIsNotNone(caminho_bloqueado(self.tmp / "chave.pem"))
        self.assertIsNone(caminho_bloqueado(self.tmp / "Diario" / "nota.md"))
        self.assertFalse(texto_secreto("Comprar cafe amanha."))
        self.assertTrue(texto_secreto("senha: abcdefghijklmnop"))
        self.assertTrue(texto_secreto("-----BEGIN RSA PRIVATE KEY-----\nABC\n"))
        self.assertTrue(texto_secreto("ghp_" + ("a" * 36)))
        note = self.tmp / "Diario" / "nota.md"
        note.parent.mkdir()
        with self.assertRaises(GuardError):
            escrever(self.tmp / ".obsidian" / "app.json", "{}\n")
        self.assertFalse((self.tmp / ".obsidian").exists())
        with self.assertRaises(GuardError):
            escrever(note, "token: abcdefghijklmnop\n")
        self.assertFalse(note.exists())
        escrever(note, "Comprar cafe.\n")
        self.assertIn("Comprar cafe", note.read_text(encoding="utf-8"))

    def test_anota_com_cara_de_segredo_nao_grava_e_nao_repete_o_texto(self):
        root = self.tmp / "vault"
        root.mkdir()
        secret = "abcdefghijklmnop"
        reply = run_routine(root, classify("anota que a senha: " + secret), NOW)
        self.assertIn("bloqueada", reply)
        self.assertEqual(reply, FALA_BLOQUEIO)
        self.assertNotIn(secret, reply)
        self.assertEqual(list(root.rglob("*.md")), [])
        ok = run_routine(root, classify("anota que comprar cafe"), NOW)
        self.assertIn("Anotei", ok)
        self.assertTrue(list(root.rglob("*.md")))

    def test_hook_recusa_e_deixa_passar_nota_comum(self):
        blocked = avaliar_ferramenta(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(self.tmp / ".obsidian" / "app.json"),
                    "content": "{}\n",
                },
            }
        )
        self.assertIn("bloqueada", blocked.casefold())
        edit = avaliar_ferramenta(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(self.tmp / "nota.md"),
                    "old_string": "cafe",
                    "new_string": "senha: abcdefghijklmnop",
                },
            }
        )
        self.assertIn("segredo", edit.casefold())
        self.assertNotIn("abcdefghijklmnop", edit)
        allowed = avaliar_ferramenta(
            {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(self.tmp / "Diario" / "nota.md"),
                    "content": "Comprar cafe.\n",
                },
            }
        )
        self.assertIsNone(allowed)
        payload = json.dumps(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": str(self.tmp / "nota.md"),
                    "edits": [{"old_string": "a", "new_string": "ghp_" + ("b" * 30)}],
                },
            }
        )
        with mock.patch("sys.stdin", StringIO(payload)):
            with mock.patch("sys.stderr", StringIO()) as err:
                code = main([])
        self.assertEqual(code, 2)
        self.assertNotIn("ghp_", err.getvalue())

    def test_prompt_marca_webfetch_e_inbox_e_o_hook_nao_leva_segredo(self):
        self.assertIn('<dado-nao-confiavel origem="WebFetch">', UNTRUSTED)
        self.assertIn('<dado-nao-confiavel origem="Jarvis/Inbox">', UNTRUSTED)
        self.assertNotIn("Tecnologia", VAULT_RULES)
        self.assertNotIn("Tecnologia", UNTRUSTED)
        path = arquivo_de_hooks()
        data = json.loads(path.read_text(encoding="utf-8"))
        hook = data["hooks"]["PreToolUse"][0]
        self.assertIn("Write", hook["matcher"])
        command = hook["hooks"][0]["command"]
        self.assertIn("jarvis.guardas", command)
        self.assertNotIn("PRIVATE KEY", command)
        self.assertNotIn("JIRA_TOKEN", path.read_text(encoding="utf-8"))
