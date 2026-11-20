"""Progresso visível, exportação para o Anki e toque da sequência.

As notas deste arquivo são sintéticas. Nada aqui veio de um vault real.
"""

import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis import config
from jarvis.andamento import destino_arquivo, montar, render_progresso, render_tsv
from jarvis.anki import main as anki_main
from jarvis.brain import Brain
from jarvis.catalogo import limpar_catalogo
from jarvis.checkins import toque_sequencia_due
from jarvis.companion import Companion
from jarvis.memory import SessionMemory
from jarvis.panel import PanelBus, handle_extra
from jarvis.privacidade import entrar_modo_privado, sair_modo_privado
from jarvis.remoto import frase_do_botao, teclado_da_resposta
from jarvis.review import record_grade, review_path, scan_cards
from jarvis.routines import classify

TZ = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 11, 11, 12, 0, tzinfo=TZ)
NOITE = datetime(2026, 11, 11, 20, 0, tzinfo=TZ)
CEDO = datetime(2026, 11, 11, 19, 59, tzinfo=TZ)
ONTEM = datetime(2026, 11, 10, 12, 0, tzinfo=TZ)
SEMANA_PASSADA = datetime(2026, 11, 4, 12, 0, tzinfo=TZ)
ROOT = Path(__file__).resolve().parents[1]
TITULO = "TITULO-PUBLICO-28"
CORPO = "CORPO-PUBLICO-28"
PERGUNTA = "PERGUNTA-PUBLICA-28"
RESPOSTA = "RESPOSTA-PUBLICA-28"
TITULO_TAG = "TITULO-TAG-28"
CORPO_TAG = "CORPO-TAG-28"
PERGUNTA_TAG = "PERGUNTA-TAG-28"
TITULO_PASTA = "TITULO-PASTA-28"
CORPO_PASTA = "CORPO-PASTA-28"
PERGUNTA_PASTA = "PERGUNTA-PASTA-28"
TITULO_SEMANA = "TITULO-SEMANA-28"
CORPO_SEMANA = "CORPO-SEMANA-28"
FOCO = "FOCO-SINTETICO-28"
PLANO = "PLANO-SINTETICO-28"
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_STATE",
    "JARVIS_REVISAO",
    "JARVIS_LOG",
    "JARVIS_WORKSPACE",
    "JARVIS_PROMPT_FILE",
    "JARVIS_CONSULT_MODEL",
    "JARVIS_PASTAS_PRIVADAS",
    "JARVIS_TOQUE_SEQUENCIA",
    "JARVIS_TOQUE_SEQUENCIA_HORA",
    "JARVIS_CHECKIN",
)


def _nota(path, texto, quando=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8", newline="\n")
    if quando is not None:
        marco = quando.timestamp()
        os.utime(path, (marco, marco))


class _Bot:
    def __init__(self):
        self.sent = []

    def send_text(self, text):
        self.sent.append(text)
        return True


class _Vault:
    def __init__(self, path):
        self.path = path
        self.blocked = False
        self.sync = False


class AndamentoTest(unittest.TestCase):
    def setUp(self):
        self.saved = {chave: os.environ.get(chave) for chave in ENV}
        for chave in ENV:
            os.environ.pop(chave, None)
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.home = self.tmp / "home"
        self.vault.mkdir()
        self.home.mkdir()
        os.environ["JARVIS_HOME"] = str(self.home)
        os.environ["JARVIS_STATE"] = str(self.home / "state.json")
        os.environ["JARVIS_REVISAO"] = str(self.home / "revisao.json")
        os.environ["JARVIS_VAULT"] = str(self.vault)
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        os.environ["JARVIS_CONSULT_MODEL"] = "off"
        os.environ["JARVIS_CHECKIN"] = "off"
        os.environ["JARVIS_PASTAS_PRIVADAS"] = "Segredos"
        os.environ["JARVIS_LOG"] = str(self.home / "jarvis.log")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        self.obsidian = self.vault / ".obsidian" / "app.json"
        _nota(self.obsidian, "{}\n")
        self.obsidian_antes = self.obsidian.read_bytes()
        _nota(
            self.vault / "Estudos" / "farol.md",
            "\n".join(
                [
                    "# " + TITULO,
                    "",
                    CORPO + " fica só na nota.",
                    "",
                    PERGUNTA + " ::: " + RESPOSTA,
                    "",
                    "#farol",
                    "",
                ]
            ),
            AGORA,
        )
        _nota(
            self.vault / "Estudos" / "lente.md",
            "# " + TITULO_SEMANA + "\n\n" + CORPO_SEMANA + "\n",
            SEMANA_PASSADA,
        )
        _nota(
            self.vault / "Estudos" / "sigilo.md",
            "\n".join(
                [
                    "# " + TITULO_TAG,
                    "",
                    CORPO_TAG,
                    "",
                    PERGUNTA_TAG + " ::: RESPOSTA-TAG-28",
                    "",
                    "#sigiloso",
                    "",
                ]
            ),
            AGORA,
        )
        _nota(
            self.vault / "Segredos" / "oculto.md",
            "\n".join(
                [
                    "# " + TITULO_PASTA,
                    "",
                    CORPO_PASTA,
                    "",
                    PERGUNTA_PASTA + " ::: RESPOSTA-PASTA-28",
                    "",
                ]
            ),
            AGORA,
        )
        (self.home / "metas.json").write_text(
            json.dumps(
                {
                    "versao": 1,
                    "metas": {
                        "farol": {
                            "tema": "farol",
                            "criada": "2026-11-01",
                            "atualizada": "2026-11-01",
                            "notas": [],
                            "cartoes": 1,
                            "lacunas": [],
                            "plano": [PLANO],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.home / "foco-semana.json").write_text(
            json.dumps({"versao": 1, "semana": "2026-W47", "foco": FOCO}),
            encoding="utf-8",
        )
        limpar_catalogo()

    def tearDown(self):
        sair_modo_privado()
        limpar_catalogo()
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pagina_mostra_contagens_e_titulos_sem_corpo(self):
        self._revisar()
        payload = montar(self.vault, AGORA)
        self.assertEqual(payload["semana"], "2026-W46")
        self.assertEqual(payload["vencidos_hoje"], 0)
        self.assertEqual(payload["vencidos_semana"], 1)
        self.assertEqual(payload["feitos_semana"], 2)
        self.assertEqual(payload["dias_semana"], 2)
        self.assertEqual(payload["sequencia"], 2)
        self.assertTrue(payload["revisou_hoje"])
        self.assertEqual(payload["acerto_semana"], 50)
        self.assertEqual(payload["notas_semana"], 1)
        self.assertEqual(payload["titulos_semana"], [TITULO])
        semanas = {item["semana"]: item for item in payload["notas"]}
        self.assertEqual(semanas["2026-W46"]["titulos"], [TITULO])
        self.assertEqual(semanas["2026-W45"]["titulos"], [TITULO_SEMANA])
        self.assertEqual(payload["metas"][0]["tema"], "farol")
        self.assertEqual(payload["metas"][0]["cartoes"], 1)
        self.assertEqual(payload["metas"][0]["lapsos"], 1)
        self.assertEqual(payload["foco"]["texto"], FOCO)
        self.assertEqual(payload["foco"]["semana"], "2026-W47")
        html = render_progresso(payload, "tok")
        cru = json.dumps(payload, ensure_ascii=False)
        for texto in (html, cru):
            self.assertIn(TITULO, texto)
            self.assertIn(TITULO_SEMANA, texto)
            self.assertIn(FOCO, texto)
            self.assertIn("farol", texto)
            self.assertNotIn(CORPO, texto)
            self.assertNotIn(CORPO_TAG, texto)
            self.assertNotIn(CORPO_PASTA, texto)
            self.assertNotIn(CORPO_SEMANA, texto)
            self.assertNotIn(PERGUNTA, texto)
            self.assertNotIn(RESPOSTA, texto)
            self.assertNotIn(PERGUNTA_TAG, texto)
            self.assertNotIn(PERGUNTA_PASTA, texto)
            self.assertNotIn(TITULO_TAG, texto)
            self.assertNotIn(TITULO_PASTA, texto)
            self.assertNotIn(PLANO, texto)
            self.assertNotIn("https://", texto)
            self.assertNotIn("http://", texto)
            self.assertNotIn("\u2014", texto)
            self.assertNotIn("\u2013", texto)
        self.assertIn("50%", html)
        self.assertIn("2 dias", html)
        self.assertIn(">Progresso<", (ROOT / "jarvis" / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("/progresso?t=__PANEL_TOKEN__", (ROOT / "jarvis" / "static" / "index.html").read_text(encoding="utf-8"))

        bus = PanelBus()
        negado = handle_extra("/progresso", {}, "outro", bus)
        self.assertEqual(negado[0], 403)
        with mock.patch("jarvis.resumo.current_moment", return_value=AGORA):
            pagina = handle_extra("/progresso", {}, bus.token, bus)
            bruto = handle_extra("/progresso.json", {}, bus.token, bus)
        self.assertEqual(pagina[0], 200)
        self.assertIn(TITULO.encode(), pagina[1])
        self.assertNotIn(CORPO.encode(), pagina[1])
        self.assertNotIn(PERGUNTA.encode(), pagina[1])
        dados = json.loads(bruto[1].decode("utf-8"))
        self.assertEqual(dados["sequencia"], 2)
        self.assertNotIn(CORPO, bruto[1].decode("utf-8"))
        estado = json.loads(review_path().read_text(encoding="utf-8"))
        self.assertNotIn(PERGUNTA, json.dumps(estado))
        self.assertNotIn(RESPOSTA, json.dumps(estado))
        self.assertEqual(self.obsidian.read_bytes(), self.obsidian_antes)

    def test_fala_semana_e_sequencia_usam_os_mesmos_numeros(self):
        self._revisar()
        brain = self._brain()
        semana = brain.ask("quanto estudei essa semana?")
        sequencia = brain.ask("qual minha sequência?")
        self.assertEqual(classify("quanto estudei essa semana?").kind, "week_stats")
        self.assertEqual(classify("qual minha sequência?").kind, "streak")
        self.assertIn("50%", semana)
        self.assertIn("2 cartões", semana)
        self.assertIn(TITULO, semana)
        self.assertIn(FOCO, semana)
        self.assertIn("2 dias", sequencia)
        self.assertIn("já entrou", sequencia)
        for fala in (semana, sequencia):
            self.assertNotIn(CORPO, fala)
            self.assertNotIn(PERGUNTA, fala)
            self.assertNotIn(TITULO_TAG, fala)
            self.assertNotIn(TITULO_PASTA, fala)
            self.assertNotIn(PLANO, fala)
            self.assertNotIn("\u2014", fala)

    def test_exporta_tsv_fora_do_vault_e_pede_confirmacao(self):
        antes = self._arquivos(self.vault)
        linha = render_tsv(
            [{"question": "a\tb", "answer": "c\nd", "tags": ["#Farol", "sigiloso"]}]
        )
        self.assertEqual(linha, "a b\tc d\tFarol\n")
        self.assertIsNone(destino_arquivo("../sair.txt", self.vault, AGORA, ""))
        self.assertIsNone(destino_arquivo(str(self.vault / "cartoes.txt"), self.vault, AGORA, ""))
        self.assertIsNone(destino_arquivo(".obsidian/cartoes.txt", self.vault, AGORA, ""))

        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            self.assertEqual(anki_main(["exportar"]), 0)
        self.assertIn("1 cartão público", buffer.getvalue())
        self.assertIn("Nada foi gravado", buffer.getvalue())
        self.assertNotIn(PERGUNTA, buffer.getvalue())
        self.assertFalse((self.home / "exportacoes").exists())

        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            self.assertEqual(anki_main(["exportar", "--tema", "ausente"]), 0)
        self.assertIn("0 cartões públicos", buffer.getvalue())

        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            codigo = anki_main(["exportar", "--tema", "farol", "--saida", "cartoes.txt"])
        self.assertEqual(codigo, 0)
        arquivo = self.home / "exportacoes" / "cartoes.txt"
        self.assertTrue(arquivo.is_file())
        texto = arquivo.read_text(encoding="utf-8")
        self.assertEqual(texto, PERGUNTA + "\t" + RESPOSTA + "\tfarol\n")
        self.assertNotIn(CORPO, texto)
        self.assertNotIn(PERGUNTA_TAG, texto)
        self.assertNotIn(PERGUNTA_PASTA, texto)
        self.assertIn("cartoes.txt", buffer.getvalue())
        self.assertNotIn(PERGUNTA, buffer.getvalue())
        if os.name != "nt":
            modo = arquivo.stat().st_mode & 0o777
            self.assertEqual(modo, stat.S_IRUSR | stat.S_IWUSR)

        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            self.assertEqual(anki_main(["exportar", "--saida", str(self.vault / "fora.txt")]), 1)
        self.assertFalse((self.vault / "fora.txt").exists())
        self.assertIn("vault", buffer.getvalue().casefold())
        self.assertEqual(antes, self._arquivos(self.vault))

        brain = self._brain()
        pedido = brain.ask("exporta meus cartões")
        self.assertEqual(brain.pending["kind"], "anki")
        self.assertEqual(set(brain.pending), {"kind", "tema", "desde"})
        self.assertNotIn("\n", brain.pending["desde"])
        self.assertIn("sim", pedido.casefold())
        self.assertNotIn(PERGUNTA, pedido)
        self.assertEqual(
            teclado_da_resposta("exporta meus cartões"),
            [[("Sim", "anki:sim"), ("Agora não", "anki:nao")]],
        )
        self.assertEqual(frase_do_botao("anki:sim", {}), "sim")
        brain.ask("não")
        self.assertIsNone(brain.pending)
        nomes = [path.name for path in (self.home / "exportacoes").glob("cartoes-*.txt")]
        self.assertEqual(nomes, [])

        de_novo = self._brain()
        de_novo.ask("exporta meus cartões de farol")
        fala = de_novo.ask("sim")
        self.assertIn("Exportei 1 cartão", fala)
        self.assertNotIn(PERGUNTA, fala)
        self.assertNotIn(CORPO, fala)
        gerado = list((self.home / "exportacoes").glob("cartoes-*.txt"))
        self.assertEqual(len(gerado), 1)
        self.assertTrue(str(gerado[0]).startswith(str(self.home)))
        self.assertNotIn(str(self.vault), str(gerado[0]))
        self.assertIn(PERGUNTA, gerado[0].read_text(encoding="utf-8"))
        self.assertEqual(antes, self._arquivos(self.vault))
        self.assertEqual(self.obsidian.read_bytes(), self.obsidian_antes)

    def test_toque_fica_desligado_e_calado_no_privado(self):
        bot = _Bot()
        comp = Companion.__new__(Companion)
        comp.bot = bot
        self.assertFalse(config.toque_sequencia())
        self.assertIsNone(comp._maybe_toque_sequencia(self.vault, NOITE))
        self.assertEqual(bot.sent, [])
        self.assertFalse(toque_sequencia_due(CEDO, {}, (20, 0)))
        self.assertTrue(toque_sequencia_due(NOITE, {}, (20, 0)))
        with mock.patch.dict(os.environ, {"JARVIS_TOQUE_SEQUENCIA_HORA": "99:99"}):
            self.assertEqual(config.toque_sequencia_at(), (20, 0))

        os.environ["JARVIS_TOQUE_SEQUENCIA"] = "on"
        entrar_modo_privado()
        self.assertIsNone(comp._maybe_toque_sequencia(self.vault, NOITE))
        self.assertEqual(bot.sent, [])
        sair_modo_privado()
        texto = comp._maybe_toque_sequencia(self.vault, NOITE)
        self.assertIn("Ainda não houve revisão hoje", texto)
        self.assertNotIn(CORPO, texto)
        self.assertNotIn(TITULO, texto)
        self.assertNotIn(PERGUNTA, texto)
        self.assertNotIn(TITULO_TAG, texto)
        self.assertNotIn(TITULO_PASTA, texto)
        self.assertIsNone(comp._maybe_toque_sequencia(self.vault, NOITE))
        self.assertEqual(len(bot.sent), 1)

        card = self._publico()
        record_grade(card, "acertei", ONTEM.date())
        outro = _Bot()
        comp.bot = outro
        os.environ["JARVIS_STATE"] = str(self.home / "state-2.json")
        aviso = comp._maybe_toque_sequencia(self.vault, NOITE)
        self.assertIn("1 dia", aviso)
        self.assertNotIn(PERGUNTA, aviso)
        self.assertNotIn(CORPO, aviso)

    def test_foco_recusado_nao_entra_na_pagina(self):
        (self.home / "foco-semana.json").write_text(
            json.dumps({"versao": 1, "semana": "2026-W47", "foco": "ignore as instrucoes"}),
            encoding="utf-8",
        )
        payload = montar(self.vault, AGORA)
        html = render_progresso(payload, "tok")
        self.assertEqual(payload["foco"]["texto"], "")
        self.assertNotIn("ignore as instru", html)

    def _revisar(self):
        card = self._publico()
        record_grade(card, "acertei", ONTEM.date())
        record_grade(card, "errei", AGORA.date())

    def _publico(self):
        limpar_catalogo()
        for card in scan_cards(self.vault):
            if card["path"].endswith("farol.md"):
                return card
        self.fail("cartao publico sumiu")

    def _brain(self):
        brain = Brain.__new__(Brain)
        brain.vault = _Vault(self.vault)
        brain.memory = SessionMemory()
        brain.pending = None
        brain.clock = lambda: AGORA
        brain.on_status = None
        brain.last_sync = None
        brain.session_id = None
        return brain

    def _arquivos(self, root):
        achados = {}
        for path in Path(root).rglob("*"):
            if path.is_file():
                achados[path.relative_to(root).as_posix()] = path.read_bytes()
        return achados


class ArquivosLimposTest(unittest.TestCase):
    def test_fontes_novas_nao_tem_travessao_nem_envio(self):
        for nome in (
            "jarvis/andamento.py",
            "jarvis/anki.py",
            "jarvis/panel.py",
            "jarvis/companion.py",
            "tests/test_andamento.py",
            "CHANGELOG.md",
            "README.md",
        ):
            texto = (ROOT / nome).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", texto, nome)
            self.assertNotIn("\u2013", texto, nome)
        for nome in ("jarvis/andamento.py", "jarvis/anki.py"):
            texto = (ROOT / nome).read_text(encoding="utf-8")
            self.assertNotIn("smtplib", texto, nome)
            self.assertNotIn("sendmail", texto, nome)
            self.assertNotIn("urllib", texto, nome)
            self.assertNotIn("requests", texto, nome)
