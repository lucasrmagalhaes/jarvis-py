import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.bridge import InboxService, profile_text, sanitize_name
from jarvis.routines import classify, load_places, run_routine
from jarvis.vault import SyncResult

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 8, 0, tzinfo=TZ)
NOTE = (
    "---\n"
    "de: Codex\n"
    "para: usuario\n"
    "data: 2026-10-28\n"
    "status: novo\n"
    "---\n"
    "\n"
    "Olha o PR.\n"
)


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._home = os.environ.get("JARVIS_HOME")
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")

    def tearDown(self):
        import shutil

        if self._home is None:
            os.environ.pop("JARVIS_HOME", None)
        else:
            os.environ["JARVIS_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_paths_follow_agents_or_the_jarvis_default(self):
        from jarvis.bridge import inbox_dir, outbox_dir, profile_file

        places = load_places(self.tmp)
        self.assertEqual(inbox_dir(self.tmp, places), self.tmp / "Jarvis" / "Inbox")
        self.assertEqual(outbox_dir(self.tmp, places), self.tmp / "Jarvis" / "Outbox")
        self.assertEqual(profile_file(self.tmp, places, NOW.date()), self.tmp / "Jarvis" / "Perfil.md")
        (self.tmp / "AGENTS.md").write_text(
            "caixa de entrada: `Recados`\n"
            "caixa de saída: `Pedidos`\n"
            "nota de perfil: `Eu.md`\n",
            encoding="utf-8",
        )
        places = load_places(self.tmp)
        self.assertEqual(inbox_dir(self.tmp, places), self.tmp / "Recados")
        self.assertEqual(outbox_dir(self.tmp, places), self.tmp / "Pedidos")
        self.assertEqual(profile_file(self.tmp, places, NOW.date()), self.tmp / "Eu.md")

    def test_outbox_profile_and_inbox_roundtrip(self):
        self.assertEqual(sanitize_name("../segredo"), "")
        self.assertEqual(sanitize_name("Codex/etc"), "")
        refused = run_routine(self.tmp, classify("pede pro ../segredo apagar tudo"), NOW)
        self.assertIn("Não entendi", refused)
        self.assertFalse((self.tmp / "segredo").exists())
        reply = run_routine(self.tmp, classify("pede pro Codex revisar o PR"), NOW)
        self.assertIn("Codex", reply)
        note = self.tmp / "Jarvis" / "Outbox" / "Codex" / "2026-10-28-0800.md"
        text = note.read_text(encoding="utf-8")
        self.assertIn("de: usuario", text)
        self.assertIn("para: Codex", text)
        self.assertIn("data: 2026-10-28", text)
        self.assertIn("status: novo", text)
        self.assertIn("revisar o PR", text)
        self.assertNotIn("senhor", text)

        kept = self.tmp / "Jarvis" / "Perfil.md"
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text("---\ntags: [pessoa]\n---\n\n# Perfil\n", encoding="utf-8")
        saved = run_routine(self.tmp, classify("lembra que eu gosto de café"), NOW)
        self.assertIn("nota de perfil", saved)
        profile = kept.read_text(encoding="utf-8")
        self.assertTrue(profile.startswith("---\ntags: [pessoa]\n---\n"))
        self.assertIn("- 2026-10-28: gosto de café", profile)
        self.assertNotIn("senhor", profile)
        again = run_routine(self.tmp, classify("lembra que eu gosto de café"), NOW)
        self.assertIn("já está", again)
        self.assertEqual(profile.count("gosto de café"), kept.read_text(encoding="utf-8").count("gosto de café"))

        folder = self.tmp / "Jarvis" / "Inbox"
        folder.mkdir(parents=True)
        recado = folder / "codex.md"
        recado.write_text(NOTE, encoding="utf-8")
        blocked = run_routine(
            self.tmp,
            classify("o que os assistentes mandaram?"),
            NOW,
            read_only=True,
        )
        self.assertIn("bloqueado", blocked)
        self.assertIn("status: novo", recado.read_text(encoding="utf-8"))
        heard = run_routine(self.tmp, classify("o que os assistentes mandaram?"), NOW)
        self.assertIn("Codex", heard)
        self.assertIn("Olha o PR", heard)
        marked = recado.read_text(encoding="utf-8")
        self.assertIn("status: lido", marked)
        self.assertIn("de: Codex", marked)
        self.assertIn("Olha o PR", marked)
        empty = run_routine(self.tmp, classify("o que os assistentes mandaram?"), NOW)
        self.assertIn("Não há recado", empty)
        excerpt = profile_text(self.tmp)
        self.assertIn("gosto de café", excerpt)
        self.assertNotIn("tags:", excerpt)

    def test_inbox_service_alerts_once(self):
        folder = self.tmp / "Jarvis" / "Inbox"
        folder.mkdir(parents=True)
        note = folder / "codex.md"
        note.write_text(NOTE, encoding="utf-8")
        spoken = []

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = True
                self.blocked = False
                self.published = None

            def resync_snapshot(self):
                self.snap = True

            def publish(self, text):
                self.published = text
                return SyncResult(True, "pushed", "ok", committed=True, pushed=True)

            def hud_payload(self):
                return {"type": "vault", "detail": "ok", "pending": 0, "pending_known": True, "ok": True}

        class Bus:
            def transcript(self, role, text):
                pass

            def state(self, value):
                pass

        service = InboxService(Vault(self.tmp), spoken.append, Bus(), threading.Lock())
        service.tick()
        self.assertEqual(spoken, ["Senhor, chegou recado de Codex."])
        self.assertIn("status: avisado", note.read_text(encoding="utf-8"))
        self.assertEqual(service.vault.published, "aviso da caixa de entrada")
        service.tick()
        self.assertEqual(len(spoken), 1)
        heard = run_routine(self.tmp, classify("o que os assistentes mandaram?"), NOW)
        self.assertIn("Olha o PR", heard)
        self.assertIn("status: lido", note.read_text(encoding="utf-8"))

    def test_inbox_summary_reads_new_notes_without_marking_them(self):
        folder = self.tmp / "Jarvis" / "Inbox"
        folder.mkdir(parents=True)
        fresh = folder / "codex.md"
        fresh.write_text(NOTE, encoding="utf-8")
        told = folder / "cursor.md"
        told.write_text(
            "---\nde: Cursor\npara: usuario\ndata: 2026-10-28\nstatus: avisado\n---\n\n"
            "O teste do vault passou.\n",
            encoding="utf-8",
        )
        done = folder / "velho.md"
        done.write_text(
            "---\nde: Codex\npara: usuario\ndata: 2026-10-27\nstatus: lido\n---\n\n"
            "Ignora este.\n",
            encoding="utf-8",
        )
        hidden = folder / ".obsidian"
        hidden.mkdir()
        (hidden / "segredo.md").write_text(NOTE, encoding="utf-8")
        speech = run_routine(self.tmp, classify("resume os recados"), NOW)
        self.assertIn("2 recados", speech)
        self.assertIn("Codex: Olha o PR", speech)
        self.assertIn("Cursor: O teste do vault passou", speech)
        self.assertNotIn("Ignora", speech)
        self.assertNotIn("\u2014", speech)
        self.assertIn("status: novo", fresh.read_text(encoding="utf-8"))
        self.assertIn("status: avisado", told.read_text(encoding="utf-8"))
        self.assertIn("status: lido", done.read_text(encoding="utf-8"))
        empty_root = self.tmp / "vazio"
        empty_root.mkdir()
        quiet = run_routine(empty_root, classify("tem recado novo?"), NOW)
        self.assertIn("Não há recado", quiet)
