import os
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.reminders import ReminderService
from jarvis.routines import (
    agenda_path,
    alert_speech,
    append_capture,
    classify,
    daily_note_path,
    list_due,
    load_places,
    mark_reminded,
    offer_choice,
    parse_reminder,
    run_routine,
    search_notes,
    week_note_path,
    write_summary,
)
from jarvis.vault import SyncResult

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 8, 0, tzinfo=TZ)


EXTERNAL_ENV = (
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "GMAIL_IMAP_HOST",
    "GMAIL_IMAP_PORT",
    "JARVIS_GH_BIN",
)


class RoutineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = {key: os.environ.get(key) for key in EXTERNAL_ENV}
        self._home = os.environ.get("JARVIS_HOME")
        for key in EXTERNAL_ENV:
            os.environ.pop(key, None)
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")

    def tearDown(self):
        import shutil

        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self._home is None:
            os.environ.pop("JARVIS_HOME", None)
        else:
            os.environ["JARVIS_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_routine_without_vault_does_not_call_claude(self):
        saved = os.environ.get("JARVIS_WORKSPACE")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ.pop("JARVIS_VAULT", None)
        try:
            from jarvis.brain import Brain

            brain = Brain()
            self.assertIn("não está configurado", brain.ask("bom dia"))
            self.assertIsNone(brain.vault)
        finally:
            if saved is None:
                os.environ.pop("JARVIS_WORKSPACE", None)
            else:
                os.environ["JARVIS_WORKSPACE"] = saved

    def test_classify_phrases(self):
        self.assertEqual(classify("Hey Jarvis, bom dia").kind, "briefing")
        self.assertEqual(classify("o que tenho para hoje").kind, "briefing")
        agenda = classify("o que tenho amanhã?")
        self.assertEqual(agenda.kind, "agenda")
        self.assertEqual(agenda.query, "amanha")
        self.assertEqual(classify("o que tenho hoje").query, "hoje")
        self.assertEqual(classify("minha agenda de depois de amanhã").query, "depois de amanha")
        self.assertEqual(classify("adia o lembrete de pagar o boleto para amanhã às 10").kind, "snooze")
        self.assertEqual(classify("cancela o lembrete de pagar o boleto").kind, "cancel")
        self.assertEqual(classify("Hey Jarvis, adiar lembrete").kind, "snooze")
        capture = classify("Anota na pasta IA que a revisao ficou para sexta")
        self.assertEqual(capture.kind, "capture")
        self.assertEqual(capture.text, "a revisao ficou para sexta")
        self.assertEqual(classify("anota").text, "")
        search = classify("o que eu escrevi sobre o Farol?")
        self.assertEqual(search.kind, "search")
        self.assertEqual(search.query, "Farol")
        noted = classify("o que anotei sobre o Farol?")
        self.assertEqual(noted.kind, "search")
        self.assertEqual(noted.query, "Farol")
        self.assertEqual(classify("onde anotei Farol").kind, "search")
        self.assertEqual(classify("Me lembra de pagar o boleto amanha as 9").kind, "reminder")
        self.assertEqual(classify("me lembra de tomar o remedio todo dia às 9").kind, "reminder")
        self.assertEqual(classify("me lembra todo dia às 9 de beber água").kind, "reminder")
        self.assertEqual(classify("resume os recados").kind, "inbox_summary")
        self.assertEqual(classify("Hey Jarvis, resumo da caixa de entrada").kind, "inbox_summary")
        self.assertEqual(classify("tem recado novo?").kind, "inbox_summary")
        self.assertEqual(classify("o que tenho no laboratorio?").kind, "chat")
        self.assertEqual(classify("e amanha?").kind, "chat")
        self.assertEqual(classify("Valeu, Jarvis").kind, "dismiss")
        self.assertEqual(classify("valeu, jarvis").kind, "dismiss")
        self.assertEqual(classify("Hey Jarvis, até logo, Jarvis").kind, "dismiss")
        self.assertEqual(classify("como foi minha semana?").kind, "week")
        self.assertEqual(classify("revisão da semana").kind, "week")
        done = classify("marca como feito pagar a conta de luz")
        self.assertEqual(done.kind, "done")
        self.assertEqual(done.text, "pagar a conta de luz")
        done = classify("marcar como concluída a tarefa enviar o relatorio")
        self.assertEqual(done.kind, "done")
        self.assertEqual(done.text, "enviar o relatorio")
        self.assertEqual(classify("o que tenho no Jira?").kind, "jira")
        self.assertEqual(classify("como estão meus PRs?").kind, "github")
        self.assertEqual(classify("tenho e-mail importante?").kind, "mail")
        self.assertEqual(classify("o que os assistentes mandaram?").kind, "inbox")
        profile = classify("lembra que eu gosto de café sem açúcar")
        self.assertEqual(profile.kind, "profile")
        self.assertEqual(profile.text, "gosto de café sem açúcar")
        self.assertEqual(classify("me lembra de pagar o boleto amanha as 9").kind, "reminder")
        outbox = classify("pede pro Codex revisar o PR")
        self.assertEqual(outbox.kind, "outbox")
        self.assertEqual(outbox.query, "Codex")
        self.assertEqual(outbox.text, "revisar o PR")
        self.assertEqual(classify("quais minhas prioridades hoje?").kind, "focus")
        self.assertEqual(classify("Hey Jarvis, foco do dia").kind, "focus")
        self.assertEqual(classify("ajuda").kind, "help")
        self.assertEqual(classify("Hey Jarvis, o que você faz?").kind, "help")
        self.assertEqual(classify("quais os comandos").kind, "help")
        self.assertEqual(classify("o que tenho hoje").kind, "agenda")
        yesterday = classify("o que eu te pedi ontem?")
        self.assertEqual(yesterday.kind, "history")
        self.assertEqual(yesterday.query, "ontem")
        self.assertEqual(classify("o que eu te pedi hoje").query, "hoje")
        self.assertEqual(classify("me lembra de pagar o boleto amanha as 9").kind, "reminder")

    def test_parse_reminder_dates(self):
        when, text, error, repeat = parse_reminder("me lembra de pagar o boleto amanha as 9", NOW)
        self.assertEqual(error, "")
        self.assertEqual(repeat, "")
        self.assertEqual(text, "pagar o boleto")
        self.assertEqual(when, datetime(2026, 10, 29, 9, 0, tzinfo=TZ))
        afternoon, _text, error, repeat = parse_reminder(
            "me lembra de buscar o carro amanhã às 15h", NOW
        )
        self.assertEqual(error, "")
        self.assertEqual(repeat, "")
        self.assertEqual(afternoon, datetime(2026, 10, 29, 15, 0, tzinfo=TZ))
        bare, _text, error, repeat = parse_reminder("me lembra de sair hoje 18h", NOW)
        self.assertEqual(error, "")
        self.assertEqual(bare, datetime(2026, 10, 28, 18, 0, tzinfo=TZ))
        night, _text, error, _repeat = parse_reminder("lembre de fechar a loja amanhã às 9 da noite", NOW)
        self.assertEqual(error, "")
        self.assertEqual(night, datetime(2026, 10, 29, 21, 0, tzinfo=TZ))
        monday, _text, error, _repeat = parse_reminder("me lembra de ligar segunda as 10", NOW)
        self.assertEqual(error, "")
        self.assertEqual(monday, datetime(2026, 11, 2, 10, 0, tzinfo=TZ))
        later, _text, error, _repeat = parse_reminder("me lembra de revisar quarta as 9:30", NOW)
        self.assertEqual(error, "")
        self.assertEqual(later, datetime(2026, 10, 28, 9, 30, tzinfo=TZ))
        _when, _text, error, _repeat = parse_reminder("me lembra de correr hoje as 7", NOW)
        self.assertIn("passou", error)
        month, _text, error, _repeat = parse_reminder("me lembra de viajar dia 30 de novembro as 15:10", NOW)
        self.assertEqual(error, "")
        self.assertEqual(month, datetime(2026, 11, 30, 15, 10, tzinfo=TZ))
        daily, text, error, repeat = parse_reminder(
            "me lembra de tomar o remedio todo dia às 9", NOW
        )
        self.assertEqual(error, "")
        self.assertEqual(text, "tomar o remedio")
        self.assertEqual(repeat, "dia")
        self.assertEqual(daily, datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        early, _text, error, repeat = parse_reminder("me lembra de alongar todo dia às 7", NOW)
        self.assertEqual(error, "")
        self.assertEqual(repeat, "dia")
        self.assertEqual(early, datetime(2026, 10, 29, 7, 0, tzinfo=TZ))
        habit, text, error, repeat = parse_reminder("me lembra todo dia às 9 de beber água", NOW)
        self.assertEqual(error, "")
        self.assertEqual(text, "beber água")
        self.assertEqual(repeat, "dia")
        self.assertEqual(habit, datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        weekly, _text, error, repeat = parse_reminder("me lembra de revisar toda segunda às 10", NOW)
        self.assertEqual(error, "")
        self.assertEqual(repeat, "segunda")
        self.assertEqual(weekly, datetime(2026, 11, 2, 10, 0, tzinfo=TZ))
        useful, _text, error, repeat = parse_reminder("me lembra de abrir a loja nos dias úteis às 8", NOW)
        self.assertEqual(error, "")
        self.assertEqual(repeat, "uteis")
        self.assertEqual(useful, datetime(2026, 10, 28, 8, 0, tzinfo=TZ))
        weekend = datetime(2026, 10, 31, 11, 0, tzinfo=TZ)
        monday, _text, error, repeat = parse_reminder(
            "me lembra de abrir a loja nos dias úteis às 8", weekend
        )
        self.assertEqual(error, "")
        self.assertEqual(repeat, "uteis")
        self.assertEqual(monday, datetime(2026, 11, 2, 8, 0, tzinfo=TZ))

    def test_daily_note_follows_agents_then_obsidian_then_dates(self):
        (self.tmp / "AGENTS.md").write_text(
            "Fuso America/Sao_Paulo.\nnota diária: `Diario/AAAA-MM-DD.md`\n",
            encoding="utf-8",
        )
        places = load_places(self.tmp)
        self.assertEqual(places.timezone_name, "America/Sao_Paulo")
        self.assertEqual(
            daily_note_path(self.tmp, places, NOW.date()),
            self.tmp / "Diario" / "2026-10-28.md",
        )
        (self.tmp / "AGENTS.md").write_text("Sem caminho.\n", encoding="utf-8")
        obsidian = self.tmp / ".obsidian"
        obsidian.mkdir()
        (obsidian / "daily-notes.json").write_text(
            '{"folder": "Notas", "format": "YYYY-MM-DD", "template": "Modelos/Dia.md"}\n',
            encoding="utf-8",
        )
        template = self.tmp / "Modelos"
        template.mkdir()
        (template / "Dia.md").write_text("---\ntipo: dia\n---\n\n# {{date}}\n", encoding="utf-8")
        places = load_places(self.tmp)
        path = append_capture(self.tmp, places, "comprar cafe", NOW)
        self.assertEqual(path, self.tmp / "Notas" / "2026-10-28.md")
        body = path.read_text(encoding="utf-8")
        self.assertTrue(body.startswith("---\ntipo: dia\n---\n"))
        self.assertIn("# 2026-10-28", body)
        self.assertIn("- 08:00 comprar cafe", body)
        append_capture(self.tmp, places, "ligar", NOW)
        again = path.read_text(encoding="utf-8")
        self.assertEqual(again.count("tipo: dia"), 1)
        self.assertIn("- 08:00 ligar", again)
        (obsidian / "daily-notes.json").unlink()
        dated = self.tmp / "Agenda"
        dated.mkdir()
        older = (self.tmp / "Notas" / "2026-10-28.md")
        os.utime(older, (1_000_000_000, 1_000_000_000))
        fresh = dated / "2026-10-01.md"
        fresh.write_text("velha\n", encoding="utf-8")
        os.utime(fresh, (NOW.timestamp(), NOW.timestamp()))
        places = load_places(self.tmp)
        self.assertEqual(
            daily_note_path(self.tmp, places, NOW.date()),
            dated / "2026-10-28.md",
        )

    def test_agenda_and_briefing_and_search(self):
        agenda = self.tmp / "Agenda Profissional"
        agenda.mkdir()
        (agenda / "Hoje.md").write_text(
            "- [ ] Revisar proposta\n- [x] Feito\n- item solto\n",
            encoding="utf-8",
        )
        recent = self.tmp / "Farol.md"
        recent.write_text("# Farol\n\nA revisão ficou para sexta.\n", encoding="utf-8")
        os.utime(recent, (NOW.timestamp(), NOW.timestamp()))
        places = load_places(self.tmp)
        self.assertEqual(agenda_path(self.tmp, places), agenda)
        speech = run_routine(self.tmp, classify("bom dia"), NOW)
        self.assertIn("quarta-feira, 28 de outubro de 2026", speech)
        self.assertIn("Revisar proposta", speech)
        self.assertNotIn("Feito", speech)
        self.assertIn("Farol", speech)
        self.assertNotIn("No Jira", speech)
        self.assertNotIn("Nos PRs", speech)
        hits = search_notes(self.tmp, "revisão sexta")
        self.assertEqual(hits[0].title, "Farol")
        self.assertEqual(hits[0].relative, "Farol.md")
        answer = run_routine(self.tmp, classify("o que eu escrevi sobre revisão?"), NOW)
        self.assertIn("Na nota Farol", answer)
        self.assertIn("caminho Farol.md", answer)
        self.assertIn("sexta", answer)

    def test_search_prefers_the_close_excerpt_and_names_the_path(self):
        loose = self.tmp / "Notas"
        loose.mkdir()
        (loose / "solta.md").write_text(
            "# Solta\n\nA revisão ficou em aberto.\n\nOutro dia, sexta.\n",
            encoding="utf-8",
        )
        tight_dir = self.tmp / "Diario"
        tight_dir.mkdir()
        (tight_dir / "Play.md").write_text(
            "---\ntags: [revisão]\n---\n\n# Play\n\nA revisão ficou para sexta.\n",
            encoding="utf-8",
        )
        hidden = self.tmp / ".obsidian"
        hidden.mkdir()
        (hidden / "escondido.md").write_text(
            "A revisão ficou para sexta no obsidian.\n",
            encoding="utf-8",
        )
        hits = search_notes(self.tmp, "revisão sexta")
        self.assertEqual(hits[0].relative, "Diario/Play.md")
        self.assertIn("revisão ficou para sexta", hits[0].snippet)
        self.assertNotIn("tags", hits[0].snippet)
        self.assertTrue(all(".obsidian" not in hit.relative for hit in hits))
        answer = run_routine(self.tmp, classify("o que anotei sobre a revisão de sexta?"), NOW)
        self.assertIn("caminho Diario/Play.md", answer)
        self.assertIn("revisão ficou para sexta", answer)
        self.assertNotIn("\u2014", answer)
        self.assertNotIn(".obsidian", answer)

    def test_capture_keeps_existing_frontmatter(self):
        places = load_places(self.tmp)
        path = daily_note_path(self.tmp, places, NOW.date())
        path.write_text("---\ntags: [a]\n---\n\n# Dia\n", encoding="utf-8")
        run_routine(self.tmp, classify("anota que comprar pao"), NOW)
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\ntags: [a]\n---\n"))
        self.assertIn("- 08:00 comprar pao", text)
        self.assertNotIn("senhor", text)

    def test_read_only_does_not_write(self):
        called = []
        reply = run_routine(
            self.tmp,
            classify("anota que segredo"),
            NOW,
            read_only=True,
            before_write=lambda: called.append(1),
        )
        self.assertIn("bloqueado", reply)
        self.assertEqual(called, [])
        self.assertFalse((self.tmp / "2026-10-28.md").exists())

    def test_reminder_survives_reread_and_alerts_once(self):
        (self.tmp / "AGENTS.md").write_text(
            "lembretes: `IA/Lembretes.md`\n",
            encoding="utf-8",
        )
        reply = run_routine(self.tmp, classify("me lembra de pagar o boleto amanha as 9"), NOW)
        self.assertIn("amanhã", reply)
        self.assertIn("pagar o boleto", reply)
        note = self.tmp / "IA" / "Lembretes.md"
        self.assertIn("- [ ] pagar o boleto @ 2026-10-29 09:00", note.read_text(encoding="utf-8"))
        due = list_due(self.tmp, datetime(2026, 10, 29, 9, 0, tzinfo=TZ))
        self.assertEqual(len(due), 1)
        self.assertEqual(list_due(self.tmp, NOW), [])
        marked = mark_reminded(due)
        self.assertEqual(len(marked), 1)
        self.assertIn("@avisado", note.read_text(encoding="utf-8"))
        self.assertEqual(list_due(self.tmp, datetime(2026, 10, 30, 9, 0, tzinfo=TZ)), [])
        self.assertIn("pagar o boleto", alert_speech(marked))

    def test_recurring_reminder_advances_and_is_delivered_again(self):
        (self.tmp / "AGENTS.md").write_text(
            "lembretes: `IA/Lembretes.md`\n",
            encoding="utf-8",
        )
        reply = run_routine(
            self.tmp,
            classify("me lembra de tomar o remedio todo dia às 9"),
            NOW,
        )
        self.assertIn("todo dia", reply)
        self.assertIn("a partir de hoje", reply)
        self.assertIn("tomar o remedio", reply)
        self.assertNotIn("\u2014", reply)
        note = self.tmp / "IA" / "Lembretes.md"
        self.assertIn(
            "- [ ] tomar o remedio @ 2026-10-28 09:00 @repete dia",
            note.read_text(encoding="utf-8"),
        )
        blocked = run_routine(
            self.tmp,
            classify("me lembra de alongar todos os dias às 7"),
            NOW,
            read_only=True,
        )
        self.assertIn("bloqueado", blocked)
        self.assertNotIn("alongar", note.read_text(encoding="utf-8"))
        due = list_due(self.tmp, datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        self.assertEqual(len(due), 1)
        spoken = []
        relayed = []

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False

            def resync_snapshot(self):
                return None

            def publish(self, text):
                return SyncResult(True, "local", "ok")

            def hud_payload(self):
                return {"pending": 0}

        class Bus:
            def transcript(self, role, text):
                return None

            def state(self, value):
                return None

        service = ReminderService(
            Vault(self.tmp),
            speak=spoken.append,
            bus=Bus(),
            lock=threading.Lock(),
            also=relayed.append,
        )
        service.tick(datetime(2026, 10, 28, 9, 0, tzinfo=TZ))
        self.assertEqual(spoken, ["Senhor, lembrete: tomar o remedio."])
        self.assertEqual(relayed, spoken)
        rolled = note.read_text(encoding="utf-8")
        self.assertIn("@ 2026-10-29 09:00 @repete dia", rolled)
        self.assertNotIn("@avisado", rolled)
        service.tick(datetime(2026, 10, 28, 12, 0, tzinfo=TZ))
        self.assertEqual(len(spoken), 1)
        late = datetime(2026, 10, 31, 18, 0, tzinfo=TZ)
        service.tick(late)
        self.assertEqual(len(spoken), 2)
        jumped = note.read_text(encoding="utf-8")
        self.assertIn("@ 2026-11-01 09:00 @repete dia", jumped)
        self.assertNotIn("@avisado", jumped)
        weekly = run_routine(
            self.tmp,
            classify("me lembra de pagar o aluguel toda sexta-feira às 15h"),
            NOW,
        )
        self.assertIn("toda sexta", weekly)
        self.assertIn("@repete sexta", note.read_text(encoding="utf-8"))

    def test_service_speaks_due_reminder_from_disk(self):
        note = self.tmp / "notas.md"
        note.write_text("- [ ] buscar o carro @ 2020-01-01 09:00\n", encoding="utf-8")
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
                return {
                    "type": "vault",
                    "detail": "ok",
                    "pending": 0,
                    "pending_known": True,
                    "action": "ready",
                    "ok": True,
                }

        class Bus:
            def __init__(self):
                self.events = []

            def transcript(self, role, text):
                self.events.append((role, text))

            def state(self, value):
                self.events.append(("state", value))

        vault = Vault(self.tmp)
        bus = Bus()
        service = ReminderService(
            vault,
            speak=spoken.append,
            bus=bus,
            lock=threading.Lock(),
            on_status=lambda payload: bus.events.append(("vault", payload["pending"])),
        )
        service.tick(datetime(2026, 10, 28, 12, 0, tzinfo=TZ))
        self.assertEqual(spoken, ["Senhor, lembrete: buscar o carro."])
        self.assertEqual(vault.published, "lembrete avisado")
        self.assertIn(("reply", spoken[0]), bus.events)
        service.tick(datetime(2026, 10, 28, 12, 5, tzinfo=TZ))
        self.assertEqual(spoken, ["Senhor, lembrete: buscar o carro."])

    def test_week_offers_to_save_and_done_asks_when_ambiguous(self):
        note = self.tmp / "Diario.md"
        note.write_text(
            "# Diario\n\n- [x] enviar o relatorio\n- [ ] revisar a proposta\n",
            encoding="utf-8",
        )
        os.utime(note, (NOW.timestamp(), NOW.timestamp()))
        old = self.tmp / "Arquivo antigo.md"
        old.write_text("# Arquivo antigo\n\n- [ ] tarefa velha\n", encoding="utf-8")
        os.utime(old, (1_600_000_000, 1_600_000_000))
        session = {}
        reply = run_routine(self.tmp, classify("como foi minha semana?"), NOW, session=session)
        self.assertIn("Quer que eu grave esse resumo, senhor?", reply)
        self.assertIn("enviar o relatorio", reply)
        self.assertIn("revisar a proposta", reply)
        self.assertNotIn("tarefa velha", reply)
        self.assertNotIn("Arquivo antigo", reply)
        pending = session["pending"]
        self.assertEqual(pending["kind"], "week")
        self.assertEqual(pending["relative"], "semana-2026-10-26.md")
        self.assertIn("## Feitas", pending["body"])
        self.assertIn("## Pendentes", pending["body"])
        self.assertIn("enviar o relatorio", pending["body"])
        self.assertNotIn("senhor", pending["body"])
        self.assertFalse((self.tmp / pending["relative"]).exists())
        self.assertEqual(offer_choice("sim", pending), "yes")
        self.assertEqual(offer_choice("pode gravar", pending), "yes")
        self.assertEqual(offer_choice("não", pending), "no")
        self.assertEqual(offer_choice("deixa", pending), "no")
        self.assertIsNone(offer_choice("talvez amanha", pending))
        path = write_summary(self.tmp / pending["relative"], pending["body"])
        self.assertIn("revisar a proposta", path.read_text(encoding="utf-8"))
        blocked = {}
        quiet = run_routine(
            self.tmp,
            classify("resumo da semana"),
            NOW,
            read_only=True,
            session=blocked,
        )
        self.assertIn("bloqueado", quiet)
        self.assertNotIn("pending", blocked)

        (self.tmp / "AGENTS.md").write_text(
            "revisão semanal: `Revisoes/AAAA-MM-DD.md`\n",
            encoding="utf-8",
        )
        places = load_places(self.tmp)
        self.assertEqual(
            week_note_path(self.tmp, places, NOW.date()),
            self.tmp / "Revisoes" / "2026-10-26.md",
        )
        kept = self.tmp / "semana.md"
        kept.write_text("---\ntags: [semana]\n---\n\nvelho\n", encoding="utf-8")
        write_summary(kept, "# Semana\n")
        kept_text = kept.read_text(encoding="utf-8")
        self.assertTrue(kept_text.startswith("---\ntags: [semana]\n---\n"))
        self.assertIn("# Semana", kept_text)
        self.assertNotIn("velho", kept_text)

        (self.tmp / "casa.md").write_text(
            "- [ ] pagar a conta de luz da casa\n",
            encoding="utf-8",
        )
        (self.tmp / "escritorio.md").write_text(
            "- [ ] pagar a conta de luz do escritorio\n",
            encoding="utf-8",
        )
        session = {}
        reply = run_routine(
            self.tmp,
            classify("marca como feito pagar a conta de luz"),
            NOW,
            session=session,
        )
        self.assertIn("Diga o número", reply)
        self.assertEqual(session["pending"]["kind"], "done")
        self.assertEqual(len(session["pending"]["options"]), 2)
        self.assertIn("- [ ]", (self.tmp / "casa.md").read_text(encoding="utf-8"))
        self.assertEqual(offer_choice("1", session["pending"]), 0)
        self.assertEqual(offer_choice("segunda", session["pending"]), 1)
        self.assertEqual(offer_choice("não", session["pending"]), "no")
        self.assertIsNone(offer_choice("sim", session["pending"]))
        solo = self.tmp / "solo"
        solo.mkdir()
        (solo / "conta.md").write_text("- [ ] pagar a conta de luz\n", encoding="utf-8")
        for path in (self.tmp / "casa.md", self.tmp / "escritorio.md"):
            path.unlink()
        reply = run_routine(solo, classify("marca como feito pagar a conta de luz"), NOW)
        self.assertIn("Marquei como feito", reply)
        marked = (solo / "conta.md").read_text(encoding="utf-8")
        self.assertIn("- [x] pagar a conta de luz", marked)

    def test_agenda_reads_dated_notes_and_reminders(self):
        agenda = self.tmp / "Agenda Profissional"
        agenda.mkdir()
        (agenda / "2026-10-28.md").write_text(
            "# Quarta\n\n- 09:00 Daily do time\n- 14h30 Reunião com o cliente\n- [x] já foi\n",
            encoding="utf-8",
        )
        (agenda / "Hoje.md").write_text("- [ ] Revisar proposta\n", encoding="utf-8")
        (agenda / "Entrevista.md").write_text(
            "---\ndata: 2026-10-29\nhora: 11:00\n---\n\n# Entrevista\n",
            encoding="utf-8",
        )
        (agenda / "Solta.md").write_text(
            "- 2026-10-30 16:00 visita\n- 09:00 não é deste dia\n",
            encoding="utf-8",
        )
        reminders = self.tmp / "IA"
        reminders.mkdir()
        (reminders / "Lembretes.md").write_text(
            "- [ ] pagar o boleto @ 2026-10-29 09:00\n"
            "- [ ] outra coisa @ 2026-11-02 09:00\n"
            "- [x] encerrado @ 2026-10-29 08:00\n",
            encoding="utf-8",
        )
        today = run_routine(self.tmp, classify("o que tenho hoje"), NOW)
        self.assertIn("Daily do time", today)
        self.assertIn("Reunião com o cliente", today)
        self.assertNotIn("já foi", today)
        self.assertNotIn("Revisar proposta", today)
        self.assertNotIn("pagar o boleto", today)
        self.assertNotIn("Entrevista", today)
        self.assertNotIn("\u2014", today)
        self.assertNotIn("\u2013", today)
        tomorrow = run_routine(self.tmp, classify("o que tenho para amanhã"), NOW)
        self.assertIn("Entrevista", tomorrow)
        self.assertIn("pagar o boleto", tomorrow)
        self.assertNotIn("Daily do time", tomorrow)
        self.assertNotIn("encerrado", tomorrow)
        later = run_routine(self.tmp, classify("compromissos de depois de amanhã"), NOW)
        self.assertIn("visita", later)
        self.assertNotIn("não é deste dia", later)
        briefing = run_routine(self.tmp, classify("bom dia"), NOW)
        self.assertIn("Agenda de hoje", briefing)
        self.assertIn("Daily do time", briefing)
        self.assertIn("Revisar proposta", briefing)
        self.assertNotIn("já foi", briefing)
        empty = self.tmp / "vazio"
        empty.mkdir()
        quiet = run_routine(empty, classify("agenda"), NOW)
        self.assertIn("Não há compromisso hoje", quiet)

    def test_postpone_and_cancel_reminder(self):
        note = self.tmp / "lembretes.md"
        note.write_text(
            "- [ ] pagar o boleto @ 2026-10-29 09:00\n"
            "- [ ] tomar o remedio @ 2026-10-28 09:00 @repete dia @avisado\n"
            "- [ ] ligar para o cliente @ 2026-10-30 15:00\n",
            encoding="utf-8",
        )
        reply = run_routine(
            self.tmp,
            classify("adia o lembrete de pagar o boleto para amanhã às 11"),
            NOW,
        )
        self.assertIn("Adiei", reply)
        self.assertIn("amanhã", reply)
        self.assertIn("11", reply)
        text = note.read_text(encoding="utf-8")
        self.assertIn("- [ ] pagar o boleto @ 2026-10-29 11:00", text)
        self.assertNotIn("senhor", text)
        moved = run_routine(self.tmp, classify("adiar lembrete de tomar o remedio em uma hora"), NOW)
        self.assertIn("hoje", moved)
        self.assertIn("9", moved)
        text = note.read_text(encoding="utf-8")
        self.assertIn("- [ ] tomar o remedio @ 2026-10-28 09:00 @repete dia", text)
        self.assertNotIn("@avisado", text)
        blocked = run_routine(
            self.tmp,
            classify("cancela o lembrete de ligar para o cliente"),
            NOW,
            read_only=True,
        )
        self.assertIn("bloqueado", blocked)
        self.assertIn("- [ ] ligar para o cliente", note.read_text(encoding="utf-8"))
        session = {}
        ambiguous = run_routine(self.tmp, classify("cancela o lembrete"), NOW, session=session)
        self.assertIn("Diga o número", ambiguous)
        self.assertEqual(session["pending"]["kind"], "cancel")
        self.assertGreaterEqual(len(session["pending"]["options"]), 2)
        self.assertEqual(offer_choice("não", session["pending"]), "no")
        self.assertIsNone(offer_choice("sim", session["pending"]))
        solo = self.tmp / "solo"
        solo.mkdir()
        (solo / "um.md").write_text("- [ ] buscar o carro @ 2026-10-28 18:00\n", encoding="utf-8")
        bare = run_routine(solo, classify("adia o lembrete"), NOW)
        self.assertIn("hoje", bare)
        self.assertIn("19", bare)
        self.assertIn("@ 2026-10-28 19:00", (solo / "um.md").read_text(encoding="utf-8"))
        kept = run_routine(solo, classify("adia o lembrete para amanhã"), NOW)
        self.assertIn("amanhã", kept)
        self.assertIn("@ 2026-10-29 19:00", (solo / "um.md").read_text(encoding="utf-8"))
        saved_env = os.environ.get("JARVIS_VAULT")
        saved_ws = os.environ.get("JARVIS_WORKSPACE")
        os.environ.pop("JARVIS_VAULT", None)
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        try:
            from jarvis.brain import Brain

            brain = Brain()
        finally:
            if saved_env is None:
                os.environ.pop("JARVIS_VAULT", None)
            else:
                os.environ["JARVIS_VAULT"] = saved_env
            if saved_ws is None:
                os.environ.pop("JARVIS_WORKSPACE", None)
            else:
                os.environ["JARVIS_WORKSPACE"] = saved_ws
        from jarvis.vault import SyncResult

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False

            def prepare(self):
                return SyncResult(True, "ready", "ok")

            def publish(self, text):
                return SyncResult(True, "skipped", "ok")

            def resync_snapshot(self):
                return None

            def hud_payload(self):
                return {"pending": 0}

        brain.vault = Vault(self.tmp)
        brain.pending = session["pending"]
        chosen = brain.ask("1")
        self.assertIn("Cancelei o lembrete", chosen)
        self.assertIn("- [x]", note.read_text(encoding="utf-8"))
        self.assertIn("@cancelado", note.read_text(encoding="utf-8"))
        brain.pending = {
            "kind": "snooze",
            "options": session["pending"]["options"],
        }
        left = brain.ask("não")
        self.assertIn("Deixei o lembrete como está", left)
        past = run_routine(self.tmp, classify("adia o lembrete de pagar o boleto para hoje às 7"), NOW)
        self.assertIn("passou", past)

    def test_hud_markup_has_vault_status(self):
        html = (ROOT / "jarvis" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="vaultDetail"', html)
        self.assertIn('id="vaultPending"', html)
        self.assertIn("setVault", html)
        self.assertNotIn("\u2014", html)
        self.assertNotIn("\u2013", html)


if __name__ == "__main__":
    unittest.main()
