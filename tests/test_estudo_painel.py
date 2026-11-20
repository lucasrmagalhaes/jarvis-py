"""Teste falado, notas relacionadas, bom dia, índice e resumo do painel.

Os textos das notas são sintéticos. Nada aqui veio de um vault real.
"""

import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis import config
from jarvis.brain import Brain
from jarvis.chat import HELP
from jarvis.checkins import briefing_due
from jarvis.companion import Companion
from jarvis.consult import reset_libraries
from jarvis.estudo import compare_answers
from jarvis.external import MAIL_FAIL
from jarvis.panel import PanelBus, QuietPanelServer, handle_extra
from jarvis.pedidos import log_path, record_turn, summary
from jarvis.relacionadas import related_notes, related_speech
from jarvis.resumo import build_resumo, render_resumo
from jarvis.review import record_grade, review_path, scan_cards
from jarvis.routines import classify, help_speech, hybrid_notes, run_routine
from jarvis.telegram import TelegramBot

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 9, 0, tzinfo=TZ)
ROOT = Path(__file__).resolve().parents[1]
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_WORKSPACE",
    "JARVIS_REVISAO",
    "JARVIS_REVISAO_LIMITE",
    "JARVIS_ESTUDO_LIMITE",
    "JARVIS_ESTUDO_CEREBRO",
    "JARVIS_INDICE",
    "JARVIS_CONSULT_MODEL",
    "JARVIS_PROMPT_FILE",
    "JARVIS_STATE",
    "JARVIS_LOG",
    "JARVIS_BRIEFING_TELEGRAM",
    "JARVIS_BRIEFING_HORA",
    "JARVIS_CHECKIN",
    "JARVIS_CHECKIN_MORNING",
    "JARVIS_CHECKIN_EVENING",
    "JARVIS_DIGEST",
    "JARVIS_GH_BIN",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "GMAIL_IMAP_HOST",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
)
SECRET = "corpo-secreto-9917"
QUESTION = "Qual a cor da fita de teste?"
ANSWER = "amarela"


def _files(root):
    found = {}
    for path in Path(root).rglob("*"):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def _note(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Rodada17Test(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_STATE"] = str(self.tmp / "home" / "state.json")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        os.environ["JARVIS_REVISAO"] = str(self.tmp / "home" / "revisao.json")
        os.environ["JARVIS_CONSULT_MODEL"] = "off"
        os.environ["JARVIS_GH_BIN"] = str(self.tmp / "sem-gh")
        os.environ["JARVIS_CHECKIN"] = "off"
        os.environ["JARVIS_DIGEST"] = "off"
        os.environ["JARVIS_BRIEFING_TELEGRAM"] = "off"
        reset_libraries()

    def tearDown(self):
        reset_libraries()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_estudo_filtra_corrige_e_grava_so_fora_do_vault(self):
        self.assertEqual(classify("Me testa sobre a fita nos livros.").kind, "study")
        self.assertIn("fita", classify("me testa sobre a fita").query)
        self.assertIn("me testa sobre um tema", help_speech(True))
        self.assertIn("me testa sobre", HELP)
        self.assertNotIn("\u2014", help_speech(True))
        self.assertNotIn("\u2014", HELP)

        _note(
            self.vault / "Tecnologia" / "Cursos" / "curso.md",
            f"# Curso\n\nQuantos elasticos o curso pede? ::: nove\n\n{SECRET} no curso\n",
        )
        _note(
            self.vault / "Tecnologia" / "zzz-hoje.md",
            f"# Hoje\n\nQual a fita de hoje? ::: verde\n\n{SECRET} hoje\n",
        )
        _note(
            self.vault / "Tecnologia" / "aaa-futuro.md",
            f"# Futuro\n\nQual a fita de amanha? ::: azul\n\n{SECRET} futuro\n",
        )
        _note(
            self.vault / ".obsidian" / "oculto.md",
            f"# Oculto\n\nQual a fita oculta? ::: preta\n\n{SECRET} oculto\n",
        )
        _note(
            self.vault / "Tecnologia" / "vaso.md",
            "---\ntags:\n  - cacto\n---\n# Vaso de teste\n\n"
            f"Qual o vaso sintetico? ::: barro\n\n{SECRET} vaso\n",
        )
        before = _files(self.vault)
        futuro = next(card for card in scan_cards(self.vault) if card["answer"] == "azul")
        record_grade(futuro, "acertei", date(2026, 10, 28))
        os.environ["JARVIS_REVISAO"] = str(self.tmp / "home" / "revisao.json")

        brain = self._brain()
        opening = brain.ask("me testa sobre fita")
        self.assertIn("Pergunta:", opening)
        self.assertIn("Qual a fita de hoje?", opening)
        self.assertNotIn("amanha", opening)
        self.assertNotIn("oculta", opening)
        self.assertNotIn(SECRET, opening)
        self.assertNotIn("\u2014", opening)

        heard = brain.ask("verde")
        self.assertIn("Certo", heard)
        self.assertIn("verde", heard)
        self.assertIn("Qual a fita de amanha?", heard)
        missed = brain.ask("laranja")
        self.assertIn("Não foi dessa vez", missed)
        self.assertIn("azul", missed)
        self.assertIn("Teste encerrado", missed)
        self.assertEqual(before, _files(self.vault))
        state = json.loads(review_path().read_text(encoding="utf-8"))
        self.assertEqual(state["daily"]["count"], 3)
        self.assertIn("2026-10-28", state["days"])
        self.assertNotIn("Qual a fita de hoje?", json.dumps(state))
        self.assertNotIn(SECRET, json.dumps(state))
        self.assertIsNone(state.get("session"))

        again = self._brain()
        started = again.ask("me testa sobre cacto")
        self.assertIn("Qual o vaso sintetico?", started)
        self.assertNotIn(SECRET, started)
        other = self._brain()
        closed = other.ask("barro")
        self.assertIn("Certo", closed)
        self.assertIn("barro", closed)
        self.assertEqual(before, _files(self.vault))

        books = self._brain()
        scoped = books.ask("me testa sobre elasticos nos livros")
        self.assertIn("Não encontrei cartão", scoped)
        _note(
            self.vault / "Tecnologia" / "Livros" / "elastico.md",
            "# Elastico\n\nQuantos elasticos o modelo usa? ::: dois\n",
        )
        before = _files(self.vault)
        scoped = books.ask("me testa sobre elasticos nos livros")
        self.assertIn("Quantos elasticos o modelo usa?", scoped)
        self.assertNotIn("curso pede", scoped)
        self.assertEqual(books.ask("tchau jarvis"), "Encerrei o teste, senhor.")
        self.assertIn("Pergunta:", books.ask("me testa sobre elasticos nos livros"))
        dropped = books.ask("silencia sempre")
        self.assertNotIn("Pergunta:", dropped)
        self.assertNotIn("Certo", dropped)
        self.assertIsNone(books.pending)
        self.assertEqual(before, _files(self.vault))

        log = log_path().read_text(encoding="utf-8")
        self.assertNotIn("Qual a fita de hoje?", log)
        self.assertNotIn(SECRET, log)
        self.assertNotIn("verde", log)
        self.assertNotIn("pedido", log)
        payload = json.loads(log.splitlines()[-1])
        self.assertEqual(set(payload), {"em", "intencao", "duracao", "sucesso"})

    def test_comparacao_local_e_cerebro_so_na_faixa_cinza(self):
        calls = []

        def judge(expected, spoken):
            calls.append((expected, spoken))
            return True

        self.assertTrue(compare_answers("amarela", "amarela", judge))
        self.assertFalse(calls)
        self.assertFalse(compare_answers("amarela", "azul marinho", judge))
        self.assertFalse(calls)
        self.assertTrue(compare_answers("farol amarelo de teste", "farol de", judge))
        self.assertEqual(len(calls), 1)

        def refuse(expected, spoken):
            return False

        self.assertFalse(compare_answers("farol amarelo de teste", "farol de", refuse))

        def boom(expected, spoken):
            raise RuntimeError("rede")

        self.assertFalse(compare_answers("farol amarelo de teste", "farol de", boom))

        _note(
            self.vault / "Notas" / "farol.md",
            "# Farol\n\nQual o tom do farol? ::: farol amarelo de teste\n",
        )
        brain = self._brain()
        brain.ask("me testa sobre farol")
        plain = brain.ask("farol de")
        self.assertIn("Não foi dessa vez", plain)
        self.assertEqual(brain.consultas, [])

        os.environ["JARVIS_ESTUDO_CEREBRO"] = "on"
        brain.consultas.clear()
        brain.ask("me testa sobre farol")
        judged = brain.ask("farol de")
        self.assertIn("Certo", judged)
        self.assertTrue(brain.consultas)
        self.assertIn("sim ou nao", brain.consultas[0].casefold())

    def test_notas_relacionadas_so_titulo_e_caminho(self):
        self.assertEqual(classify("Notas relacionadas ao farol.").kind, "related")
        self.assertEqual(classify("notas relacionadas ao farol").query, "farol")
        self.assertIn("notas relacionadas", help_speech(True))
        farol = (
            "# Farol de teste\n\n"
            "Este paragrafo sintetico descreve um farol de laboratorio, "
            "sem nenhum texto copiado de um vault real do usuario.\n\n"
            f"{SECRET} farol\n"
        )
        hortela = (
            "# Hortela de teste\n\n"
            "Este paragrafo sintetico descreve hortela de laboratorio, "
            "um aroma ficticio usado so neste teste automatizado.\n\n"
            f"{SECRET} hortela\n"
        )
        oficina = (
            "# Oficina de teste\n\n"
            "Este paragrafo sintetico descreve uma oficina de laboratorio, "
            "com bancada ficticia e nenhuma nota pessoal.\n\n"
            f"{SECRET} oficina\n"
        )
        _note(self.vault / "Tecnologia" / "farol.md", farol)
        _note(self.vault / "Tecnologia" / "hortela.md", hortela)
        _note(self.vault / "Tecnologia" / "oficina.md", oficina)

        class Embedder:
            def embed(self, texts):
                rows = []
                for text in texts:
                    folded = text.casefold()
                    if "farol" in folded:
                        rows.append([1.0, 0.0, 0.0])
                    elif "hortela" in folded:
                        rows.append([0.9, 0.1, 0.0])
                    else:
                        rows.append([0.0, 0.0, 1.0])
                return rows

        notes = related_notes(self.vault, "Farol de teste", embedder=Embedder(), limit=5)
        self.assertTrue(notes)
        self.assertEqual(notes[0]["titulo"], "Hortela de teste")
        self.assertEqual(notes[0]["caminho"], "Tecnologia/hortela.md")
        blob = json.dumps(notes, ensure_ascii=False)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn("paragrafo sintetico", blob)
        self.assertEqual(set(notes[0]), {"titulo", "caminho"})
        speech = related_speech(self.vault, "Farol de teste", embedder=Embedder())
        self.assertIn("Notas relacionadas", speech)
        self.assertIn("Hortela de teste", speech)
        self.assertIn("Tecnologia/hortela.md", speech)
        self.assertNotIn("Farol de teste", speech)
        self.assertNotIn(SECRET, speech)
        self.assertNotIn("\u2014", speech)

        _note(
            self.vault / "Tecnologia" / "rara.md",
            "# Rara de teste\n\n"
            "A quinquilharia sintetico aparece neste paragrafo longo de teste, "
            "feito apenas para o indice esparso local.\n",
        )
        reset_libraries()
        sparse = related_notes(self.vault, "quinquilharia", embedder=None)
        self.assertTrue(sparse)
        self.assertIn("rara.md", sparse[0]["caminho"])
        self.assertNotIn("quinquilharia sintetico aparece", json.dumps(sparse))

        brain = self._brain()
        said = brain.ask("notas relacionadas a quinquilharia")
        self.assertIn("Rara de teste", said)
        self.assertNotIn(SECRET, said)
        self.assertNotIn("quinquilharia sintetico aparece", said)
        empty = self.tmp / "vazio"
        empty.mkdir()
        self.assertIn("Não encontrei nota relacionada", related_speech(empty, "farol"))

    def test_indice_existente_sobe_a_nota_e_ausente_nao_muda(self):
        alvo = (
            "# Alvo de teste\n\n"
            "Um texto sintetico sobre engrenagens de laboratorio, "
            "sem a palavra que a pergunta usa.\n"
        )
        decoy = (
            "# Isca de teste\n\n"
            "Um farol sintetico aparece uma vez neste paragrafo de laboratorio.\n"
        )
        _note(self.vault / "Tecnologia" / "alvo.md", alvo)
        _note(self.vault / "Tecnologia" / "isca.md", decoy)
        plain = hybrid_notes(self.vault, "farol", limit=5)
        relatives = [hit.relative for hit in plain]
        self.assertIn("Tecnologia/isca.md", relatives)
        self.assertNotIn("Tecnologia/alvo.md", relatives)

        _note(
            self.vault / "indice.md",
            "# Farol\n\n- [[Tecnologia/alvo|Alvo de teste]]\n",
        )
        boosted = hybrid_notes(self.vault, "farol", limit=5)
        self.assertEqual(boosted[0].relative, "Tecnologia/alvo.md")
        self.assertNotIn(SECRET, boosted[0].snippet)

        os.environ["JARVIS_INDICE"] = "off"
        self.assertNotIn(
            "Tecnologia/alvo.md",
            [hit.relative for hit in hybrid_notes(self.vault, "farol", limit=5)],
        )
        os.environ["JARVIS_INDICE"] = "../fora.md"
        self.assertNotIn(
            "Tecnologia/alvo.md",
            [hit.relative for hit in hybrid_notes(self.vault, "farol", limit=5)],
        )
        outside = self.tmp / "fora.md"
        outside.write_text("# Farol\n\n[[Tecnologia/alvo]]\n", encoding="utf-8")
        os.environ["JARVIS_INDICE"] = str(outside)
        self.assertNotIn(
            "Tecnologia/alvo.md",
            [hit.relative for hit in hybrid_notes(self.vault, "farol", limit=5)],
        )
        _note(
            self.vault / ".obsidian" / "indice.md",
            "# Farol\n\n[[Tecnologia/alvo]]\n",
        )
        os.environ["JARVIS_INDICE"] = ".obsidian/indice.md"
        self.assertNotIn(
            "Tecnologia/alvo.md",
            [hit.relative for hit in hybrid_notes(self.vault, "farol", limit=5)],
        )
        os.environ.pop("JARVIS_INDICE", None)
        self.assertEqual(config.index_relative(), "indice.md")

    def test_bom_dia_junta_fontes_e_uma_falha_nao_derruba_o_resto(self):
        _note(
            self.vault / "Agenda Profissional" / "2026-10-28.md",
            "- 09:00 Daily do time\n",
        )
        _note(
            self.vault / "Notas" / "sigilo.md",
            f"# Titulo visivel\n\n{SECRET} nao pode sair no bom dia\n",
        )
        os.environ["JIRA_URL"] = "https://example.atlassian.net"
        os.environ["JIRA_EMAIL"] = "pessoa@example.com"
        os.environ["JIRA_TOKEN"] = "token-de-teste"
        os.environ["GMAIL_EMAIL"] = "pessoa@example.com"
        os.environ["GMAIL_APP_PASSWORD"] = "ab cd ef gh"
        script = self.tmp / "gh"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if sys.argv[1:3] == ['auth', 'status']:\n"
            "    raise SystemExit(0)\n"
            "if '--review-requested=@me' in sys.argv:\n"
            "    json.dump([], sys.stdout)\n"
            "    raise SystemExit(0)\n"
            "json.dump([{'number': 7, 'title': 'Ajustar farol sintetico', "
            "'repository': {'nameWithOwner': 'exemplo/lab'}}], sys.stdout)\n",
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        os.environ["JARVIS_GH_BIN"] = str(script)
        mail_calls = []

        class Mail:
            def login(self, user, password):
                mail_calls.append(("login", user))

            def select(self, mailbox, readonly=False):
                mail_calls.append(("select", mailbox, readonly))
                return "OK", [b"1"]

            def search(self, charset, *criteria):
                mail_calls.append(("search", criteria))
                return "OK", [b"1"]

            def fetch(self, number, spec):
                mail_calls.append(("fetch", spec))
                header = b"From: Ana <ana@example.com>\r\nSubject: Boleto sintetico\r\n"
                return "OK", [(b"1", header)]

            def logout(self):
                mail_calls.append(("logout",))

            def store(self, *_args):
                raise AssertionError("store")

            def append(self, *_args):
                raise AssertionError("append")

        import jarvis.external as external

        original_open = urllib.request.urlopen
        original_imap = external._imap_connect
        issue = {
            "issues": [
                {
                    "key": "LAB-1",
                    "fields": {
                        "summary": "Revisar farol sintetico",
                        "status": {"name": "A fazer", "statusCategory": {"key": "new"}},
                    },
                }
            ]
        }

        class Response:
            def read(self):
                return json.dumps(issue).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        urllib.request.urlopen = lambda request, timeout=15: Response()
        external._imap_connect = lambda host, port: Mail()
        try:
            speech = run_routine(self.vault, classify("bom dia"), NOW)
        finally:
            urllib.request.urlopen = original_open
            external._imap_connect = original_imap
        self.assertIn("Bom dia", speech)
        self.assertIn("Daily do time", speech)
        self.assertIn("Agenda de hoje", speech)
        self.assertIn("LAB-1", speech)
        self.assertIn("Ajustar farol sintetico", speech)
        self.assertIn("Boleto sintetico", speech)
        self.assertIn("E-mail, 1 não lidos", speech)
        self.assertNotIn("Ana", speech)
        self.assertNotIn(SECRET, speech)
        self.assertNotIn("token-de-teste", speech)
        self.assertNotIn("abcdefgh", speech)
        self.assertNotIn("\u2014", speech)
        self.assertEqual(mail_calls[1], ("select", "INBOX", True))
        fetched = next(item for item in mail_calls if item[0] == "fetch")
        self.assertIn("BODY.PEEK", fetched[1])
        self.assertNotIn("store", [item[0] for item in mail_calls])

        class Boom:
            def login(self, user, password):
                raise RuntimeError("senha ab cd ef gh")

            def logout(self):
                return None

        urllib.request.urlopen = lambda request, timeout=15: (_ for _ in ()).throw(RuntimeError("jira"))
        external._imap_connect = lambda host, port: Boom()
        try:
            failed = run_routine(self.vault, classify("bom dia"), NOW)
        finally:
            urllib.request.urlopen = original_open
            external._imap_connect = original_imap
        self.assertIn("Bom dia", failed)
        self.assertIn("Daily do time", failed)
        self.assertIn("Ajustar farol sintetico", failed)
        self.assertIn("Não consegui consultar o Jira", failed)
        self.assertEqual(failed.count(MAIL_FAIL) >= 1, True)
        self.assertNotIn("ab cd", failed)
        self.assertNotIn(SECRET, failed)

    def test_bom_dia_agendado_so_no_telegram_e_sem_duplicar(self):
        self.assertFalse(config.briefing_telegram())
        self.assertEqual(config.briefing_at(), (7, 30))
        early = datetime(2026, 10, 28, 7, 0, tzinfo=TZ)
        due = datetime(2026, 10, 28, 7, 31, tzinfo=TZ)
        self.assertFalse(briefing_due(early, {}, (7, 30)))
        self.assertTrue(briefing_due(due, {}, (7, 30)))
        self.assertFalse(briefing_due(due, {"briefing_telegram": "2026-10-28"}, (7, 30)))

        _note(
            self.vault / "Notas" / "sigilo.md",
            f"# Titulo visivel\n\n{SECRET} fora do telegram\n",
        )
        os.environ["JARVIS_BRIEFING_TELEGRAM"] = "on"
        os.environ["JARVIS_CHECKIN"] = "off"
        spoken = []
        api = _Api()
        bot = TelegramBot(api, 42, lambda text: text, lambda path: "")
        companion = self._companion(spoken, bot)
        self.assertIsNone(companion.tick(early))
        self.assertEqual(api.calls, [])
        self.assertEqual(spoken, [])
        sent = companion.tick(due)
        self.assertIn("Bom dia", sent)
        self.assertNotIn(SECRET, sent)
        self.assertNotIn("\u2014", sent)
        self.assertEqual(spoken, [])
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0][0], "sendMessage")
        self.assertEqual(api.calls[0][1]["chat_id"], 42)
        self.assertIsNone(companion.tick(due))
        self.assertEqual(len(api.calls), 1)

        class Boom:
            def send_text(self, text):
                raise RuntimeError("rede")

        later = datetime(2026, 10, 29, 8, 0, tzinfo=TZ)
        companion.bot = Boom()
        self.assertIsNone(companion.tick(later))
        companion.bot = bot
        retried = companion.tick(later)
        self.assertIn("Bom dia", retried)
        self.assertNotIn(SECRET, retried)
        self.assertEqual(len(api.calls), 2)

        os.environ["JARVIS_CHECKIN"] = "on"
        os.environ["JARVIS_CHECKIN_MORNING"] = "on"
        morning = self._companion(spoken, bot)
        both = morning.tick(datetime(2026, 10, 30, 8, 0, tzinfo=TZ))
        self.assertIn("Bom dia", both)
        self.assertEqual(len(api.calls), 3)
        self.assertIsNone(morning.tick(datetime(2026, 10, 30, 9, 0, tzinfo=TZ)))
        self.assertEqual(len(api.calls), 3)
        self.assertEqual(len(spoken), 1)

    def test_painel_mostra_revisao_e_log_sem_texto(self):
        _note(
            self.vault / "Notas" / "um.md",
            f"# Um\n\n{QUESTION} ::: {ANSWER}\n\n{SECRET}\n",
        )
        _note(
            self.vault / "Notas" / "dois.md",
            "# Dois\n\nQual o segundo cartao? ::: pronto\n",
        )
        cards = scan_cards(self.vault)
        first = cards[0]
        record_grade(first, "acertei", date(2026, 10, 27))
        record_grade(first, "acertei", date(2026, 10, 28))
        record_turn("study", 1.5, True, NOW)
        record_turn("related", 0.5, True, NOW)
        os.environ["JARVIS_VAULT"] = str(self.vault)
        payload = build_resumo(self.vault, NOW)
        self.assertEqual(payload["revisao"]["feitos_hoje"], 1)
        self.assertEqual(payload["revisao"]["sequencia"], 2)
        self.assertEqual(payload["revisao"]["vencidos"], 1)
        self.assertEqual(payload["pedidos"]["total"], 2)
        self.assertEqual(payload["pedidos"]["media_ms"], 1000)
        labels = {row["rotulo"]: row["vezes"] for row in payload["pedidos"]["por_intencao"]}
        self.assertEqual(labels["teste"], 1)
        self.assertEqual(labels["notas relacionadas"], 1)
        html = render_resumo(payload, "tok")
        self.assertIn("Vencidos", html)
        self.assertIn("Feitos hoje", html)
        self.assertIn("Sequência", html)
        self.assertIn("2 dias", html)
        self.assertIn("1000 ms", html)
        self.assertNotIn(QUESTION, html)
        self.assertNotIn(ANSWER, html)
        self.assertNotIn(SECRET, html)
        self.assertNotIn("\u2014", html)
        usage = summary()
        self.assertNotIn("pedido", json.dumps(usage))
        self.assertEqual(usage["media"], 1.0)

        import jarvis.resumo as resumo

        previous_moment = resumo.current_moment
        resumo.current_moment = lambda root=None: NOW
        bus = PanelBus()
        try:
            self._painel_http(bus)
        finally:
            resumo.current_moment = previous_moment

    def _painel_http(self, bus):
        denied = handle_extra("/resumo", {}, "outro", bus)
        self.assertEqual(denied[0], 403)
        from jarvis.privacidade import garantir_token

        arquivo = garantir_token()
        sem_arquivo = handle_extra("/relacionadas", {"q": ["tema"]}, bus.token, bus)
        self.assertEqual(sem_arquivo[0], 403)
        missing = handle_extra(
            "/relacionadas", {"q": ["  "], "p": [arquivo]}, bus.token, bus
        )
        self.assertEqual(missing[0], 400)
        self.assertIn("Informe o tema", missing[1].decode("utf-8"))
        page = handle_extra("/resumo", {}, bus.token, bus)
        self.assertEqual(page[0], 200)
        self.assertIn(b"Vencidos", page[1])
        self.assertNotIn(SECRET.encode(), page[1])
        raw = handle_extra("/resumo.json", {}, bus.token, bus)
        data = json.loads(raw[1].decode("utf-8"))
        self.assertEqual(data["revisao"]["sequencia"], 2)
        self.assertNotIn(SECRET, raw[1].decode("utf-8"))

        _note(
            self.vault / "Tecnologia" / "rara.md",
            "# Rara de teste\n\n"
            "A quinquilharia sintetico aparece neste paragrafo longo de teste, "
            "feito apenas para o indice esparso local.\n",
        )
        reset_libraries()
        from jarvis.privacidade import garantir_token

        arquivo = garantir_token()
        related = handle_extra(
            "/relacionadas",
            {"q": ["quinquilharia"], "p": [arquivo]},
            bus.token,
            bus,
        )
        body = json.loads(related[1].decode("utf-8"))
        self.assertEqual(related[0], 200)
        self.assertTrue(body["notas"])
        self.assertEqual(set(body["notas"][0]), {"titulo", "caminho"})
        self.assertNotIn("quinquilharia sintetico", related[1].decode("utf-8"))
        self.assertIsNone(handle_extra("/outro", {}, bus.token, bus))

        index = (ROOT / "jarvis" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("/resumo?t=__PANEL_TOKEN__", index)
        self.assertIn(">Resumo<", index)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("JARVIS_BRIEFING_TELEGRAM", readme)
        self.assertIn("JARVIS_ESTUDO_LIMITE", readme)
        self.assertIn("JARVIS_INDICE", readme)
        self.assertIn("Me testa sobre", readme)
        for name in (
            "jarvis/estudo.py",
            "jarvis/indice.py",
            "jarvis/relacionadas.py",
            "jarvis/resumo.py",
            "jarvis/panel.py",
            "jarvis/companion.py",
            "jarvis/external.py",
            "tests/test_estudo_painel.py",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)
        for name in (
            "jarvis/estudo.py",
            "jarvis/indice.py",
            "jarvis/relacionadas.py",
            "jarvis/resumo.py",
            "jarvis/external.py",
            "jarvis/companion.py",
        ):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("smtplib", text, name)
            self.assertNotIn("sendmail", text, name)

        self._http(bus)

    def _http(self, bus):
        probe = __import__("socket").socket()
        try:
            probe.bind(("127.0.0.1", config.PANEL_PORT))
        except OSError:
            probe.close()
            self.skipTest("porta do painel ocupada")
        probe.close()
        handler = type("BoundPanelHandler", (__import__("jarvis.panel", fromlist=["PanelHandler"]).PanelHandler,), {"bus": bus})
        server = QuietPanelServer(("127.0.0.1", config.PANEL_PORT), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{config.PANEL_PORT}/resumo?t={bus.token}"
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            self.assertIn("Vencidos", body)
            self.assertNotIn(SECRET, body)
            bare = f"http://127.0.0.1:{config.PANEL_PORT}/resumo"
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(bare, timeout=5)
            self.assertEqual(caught.exception.code, 403)
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def _brain(self):
        os.environ.pop("JARVIS_VAULT", None)
        brain = Brain()

        class Vault:
            def __init__(self, path):
                self.path = path
                self.blocked = False

            def prepare(self):
                raise AssertionError("prepare")

            def publish(self, _text):
                raise AssertionError("publish")

            def resync_snapshot(self):
                return None

            def hud_payload(self):
                return {}

        brain.vault = Vault(self.vault)
        brain.clock = lambda: NOW
        brain.consultas = []

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        def consult(prompt, _user, _local):
            brain.consultas.append(prompt)
            return "sim"

        brain._ask = fail
        brain._answer_consult = consult
        return brain

    def _companion(self, spoken, bot):
        holder = type("B", (), {})()
        holder.vault = type("V", (), {"path": self.vault, "blocked": False})()
        holder.pending = None
        companion = Companion(
            holder,
            speak=lambda text: spoken.append(text),
            lock=threading.RLock(),
        )
        companion._held = True
        companion.bot = bot
        return companion


class _Api:
    def __init__(self):
        self.calls = []

    def call(self, method, payload, timeout=30):
        self.calls.append((method, dict(payload)))
        return {}


if __name__ == "__main__":
    unittest.main()
