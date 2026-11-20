"""Escala, primeiro uso e notas tortas. Só texto sintético."""

import io
import logging
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis.benchmark import medir
from jarvis.leitura import limpar_avisos
from jarvis.review import parse_card_line, scan_cards
from jarvis.routines import classify
from jarvis.sintetico import gerar_vault

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=TZ)
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_ENV_FILE",
    "JARVIS_REVISAO",
    "JARVIS_REVISAO_LIMITE",
    "JARVIS_REVISAO_NOVOS",
    "JARVIS_REVISAO_PRIORIDADE",
    "JARVIS_VAULT_SYNC",
    "JARVIS_LIVROS_PASTA",
    "JARVIS_VIDEOS_PASTA",
    "JARVIS_CURSOS_PASTA",
    "JARVIS_WORKSPACE",
    "JARVIS_PROMPT_FILE",
)


def _restaurar(chave, valor):
    if valor is None:
        os.environ.pop(chave, None)
    else:
        os.environ[chave] = valor


class EscalaTest(unittest.TestCase):
    def test_gerador_bate_a_conta_e_nao_usa_traco_longo(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(pasta, ignore_errors=True))
        resumo = gerar_vault(pasta / "vault", notas=30, livros=4, videos=2, cursos=2, cartoes=40, longas=1)
        self.assertEqual(resumo["notas"], 30)
        self.assertEqual(resumo["livros"], 4)
        self.assertEqual(resumo["videos"], 2)
        self.assertEqual(resumo["cartoes"], 40)
        nomes = [path.as_posix() for path in (pasta / "vault").rglob("*.md")]
        self.assertTrue(any("Diário" in nome or "Referências" in nome for nome in nomes))
        amostra = (pasta / "vault" / "Tecnologia" / "Livros" / "livro-0000.md").read_text(encoding="utf-8")
        self.assertIn(":::", amostra)
        self.assertNotIn("\u2014", amostra)
        self.assertNotIn("\u2013", amostra)

    def test_medicao_curta_fica_dentro_do_limite(self):
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(pasta, ignore_errors=True))
        self._env(pasta)
        gerar_vault(
            pasta / "vault",
            notas=80,
            livros=12,
            videos=4,
            cursos=4,
            cartoes=160,
            longas=2,
        )
        resultado = medir(pasta / "vault", repeticoes=3)
        self.assertGreater(resultado["refeitas_frio"], 0)
        self.assertEqual(resultado["refeitas_um"], 1)
        self.assertLess(resultado["indice_morno_s"], resultado["indice_frio_s"])
        self.assertLess(resultado["indice_frio_s"], 20)
        self.assertLess(resultado["indice_morno_s"], 5)
        self.assertLess(resultado["reindice_s"], 5)
        self.assertLess(resultado["busca_s"], 5)
        self.assertLess(resultado["cartoes_s"], 5)
        self.assertLess(resultado["revisao_gravar_s"], 5)
        self.assertLess(resultado["revisao_ler_s"], 5)
        self.assertGreater(resultado["cartoes"], 0)
        self.assertEqual(resultado["revisao_cards"], resultado["cartoes"])
        texto = str(resultado)
        self.assertNotIn("quartzo", texto)
        self.assertNotIn("\u2014", texto)

    def _env(self, pasta):
        self._saved = {chave: os.environ.get(chave) for chave in ENV}
        for chave in ENV:
            os.environ.pop(chave, None)
        os.environ["JARVIS_HOME"] = str(pasta / "home")
        os.environ["JARVIS_REVISAO"] = str(pasta / "home" / "revisao.json")
        os.environ["JARVIS_WORKSPACE"] = str(pasta / "ws")
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        self.addCleanup(self._restore)

    def _restore(self):
        for chave, valor in self._saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor


class ResilienciaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        limpar_avisos()
        self.log = io.StringIO()
        self.handler = logging.StreamHandler(self.log)
        logging.getLogger("jarvis").addHandler(self.handler)
        self.addCleanup(self._limpar)

    def _limpar(self):
        logging.getLogger("jarvis").removeHandler(self.handler)
        shutil.rmtree(self.tmp, ignore_errors=True)
        limpar_avisos()

    def test_arquivo_torto_nao_derruba_busca_nem_cartao(self):
        from jarvis.leitura import MAX_BYTES
        from jarvis.routines import hybrid_notes

        sentinela = "SENTINELA-TORTO-99"
        (self.vault / "boa.md").write_text(
            "# Boa\n\nO quartzo sintetico desta nota fica na estante.\n"
            "Qual o mineral sintetico? ::: quartzo\n",
            encoding="utf-8",
        )
        (self.vault / "frente.md").write_text(
            "---\n"
            "titulo sem dois pontos\n"
            "[\n"
            "# " + sentinela + "\n"
            "Qual a peca estavel? ::: engrenagem\n",
            encoding="utf-8",
        )
        (self.vault / "binario.md").write_bytes(b"# bin\n\0" + sentinela.encode("utf-8"))
        (self.vault / "latin1.md").write_bytes("café sintetico ::: nao".encode("latin-1"))
        (self.vault / "enorme.md").write_bytes(b"a" * (MAX_BYTES + 32))
        (self.vault / "longa.md").write_text(
            "x" * 20000 + "\nQual a linha curta? ::: curta\n",
            encoding="utf-8",
        )
        (self.vault / "varios.md").write_text(
            f"pergunta {sentinela} ::: resposta ::: sobra\n",
            encoding="utf-8",
        )
        (self.vault / "link.md").write_text(
            "# Link\n\nVeja [[nota que nao fecha\nQual o elo? ::: firme\n",
            encoding="utf-8",
        )
        (self.vault / "um.md").write_text("# Igual\n\nNota um do par sintetico.\n", encoding="utf-8")
        (self.vault / "dois.md").write_text("# Igual\n\nNota dois do par sintetico.\n", encoding="utf-8")
        cards = scan_cards(self.vault)
        respostas = {card["answer"] for card in cards}
        self.assertIn("quartzo", respostas)
        self.assertIn("engrenagem", respostas)
        self.assertIn("curta", respostas)
        self.assertIn("firme", respostas)
        self.assertNotIn("sobra", respostas)
        self.assertNotIn(sentinela, respostas)
        hits = hybrid_notes(self.vault, "quartzo sintetico")
        self.assertTrue(hits)
        self.assertTrue(all(sentinela not in (hit.snippet or "") for hit in hits))
        aviso = self.log.getvalue()
        self.assertIn("motivo=binario", aviso)
        self.assertIn("motivo=codificacao", aviso)
        self.assertIn("motivo=enorme", aviso)
        self.assertIn("motivo=linha-longa", aviso)
        self.assertIn("motivo=frontmatter", aviso)
        self.assertIn("motivo=cartao", aviso)
        self.assertIn("motivo=link", aviso)
        self.assertIn("motivo=titulo", aviso)
        self.assertNotIn(sentinela, aviso)
        self.assertNotIn("engrenagem", aviso)
        self.assertIsNone(parse_card_line(f"pergunta {sentinela} ::: uma ::: duas"))


class RevisaoEscalaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {chave: os.environ.get(chave) for chave in ENV}
        for chave in ENV:
            os.environ.pop(chave, None)
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_REVISAO"] = str(self.tmp / "home" / "revisao.json")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        os.environ["JARVIS_REVISAO_LIMITE"] = "10"
        os.environ["JARVIS_REVISAO_NOVOS"] = "2"
        self.vault = self.tmp / "vault"
        livros = self.vault / "Tecnologia" / "Livros"
        livros.mkdir(parents=True)
        (livros / "volume.md").write_text(
            "---\ntags: [urgente]\n---\n# Volume\nQual o livro urgente? ::: alfa\n",
            encoding="utf-8",
        )
        diario = self.vault / "Diario"
        diario.mkdir()
        linhas = ["# Diario sintetico", ""]
        for numero in range(12):
            linhas.append(f"Pergunta solta {numero}? ::: solta{numero}")
        (diario / "solto.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        self.addCleanup(self._limpar)

    def _limpar(self):
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _brain(self):
        from jarvis.brain import Brain

        brain = Brain()

        class Vault:
            def __init__(self, path):
                self.path = path
                self.sync = False
                self.blocked = False

            def prepare(self):
                raise AssertionError("a revisão não prepara o git")

            def publish(self, _text):
                raise AssertionError("a revisão não publica")

        brain.vault = Vault(self.vault)
        brain.clock = lambda: NOW
        brain._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("claude"))
        return brain

    def test_limite_de_novos_e_prioridade_por_pasta_e_tag(self):
        os.environ["JARVIS_REVISAO_PRIORIDADE"] = "Tecnologia/Livros, #urgente"
        brain = self._brain()
        abertura = brain.ask("revisão do dia")
        self.assertIn("São 2 cartões nesta revisão", abertura)
        self.assertIn("Qual o livro urgente?", abertura)
        self.assertNotIn("solta0", abertura)
        self.assertNotIn("\u2014", abertura)
        brain.ask("talvez")
        brain.ask("acertei")
        brain.ask("talvez")
        fim = brain.ask("acertei")
        self.assertIn("Revisão encerrada", fim)
        de_novo = brain.ask("revisão do dia")
        self.assertIn("limite de cartões novos", de_novo)
        estado = __import__("json").loads(
            Path(os.environ["JARVIS_REVISAO"]).read_text(encoding="utf-8")
        )
        self.assertEqual(estado["daily"]["novos"], 2)
        bruto = __import__("json").dumps(estado)
        self.assertNotIn("urgente", bruto)
        self.assertNotIn("Qual o livro urgente", bruto)
        self.assertNotIn("alfa", bruto)

    def test_revisao_vencida_entra_antes_de_estourar_o_novo(self):
        from jarvis.review import card_id, update_state

        os.environ["JARVIS_REVISAO_NOVOS"] = "1"
        os.environ["JARVIS_REVISAO_LIMITE"] = "3"
        alvo = "Diario/solto.md"

        def semear(data):
            ident = card_id(alvo, "Pergunta solta 0?")
            data.setdefault("cards", {})[ident] = {
                "interval": 1,
                "ease": 2.5,
                "reps": 2,
                "lapses": 0,
                "due": "2026-11-10",
                "path": alvo,
            }

        update_state(semear)
        brain = self._brain()
        abertura = brain.ask("revisão do dia")
        self.assertIn("Pergunta solta 0?", abertura)
        self.assertIn("cartões nesta revisão", abertura)


class PrimeiroUsoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {chave: os.environ.get(chave) for chave in ENV}
        for chave in ENV:
            os.environ.pop(chave, None)
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_ENV_FILE"] = str(self.tmp / "home" / ".env")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        self.addCleanup(self._limpar)

    def _limpar(self):
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args):
        subprocess.run(["git", *args], check=True, capture_output=True, text=True)

    def _repo(self):
        repo = self.tmp / "vault"
        (repo / "Tecnologia" / "Livros").mkdir(parents=True)
        (repo / "Tecnologia" / "Vídeos").mkdir(parents=True)
        (repo / "Cursos").mkdir()
        (repo / "Tecnologia" / "Livros" / "hortela.md").write_text(
            "# Hortela de teste\n\nTexto sintetico de prateleira.\n",
            encoding="utf-8",
        )
        (repo / "Tecnologia" / "Vídeos" / "farol.md").write_text(
            "# Farol ficticio\n\nTexto sintetico de video.\n",
            encoding="utf-8",
        )
        (repo / "Cursos" / "oficina.md").write_text(
            "# Oficina de teste\n\nTexto sintetico de curso.\n",
            encoding="utf-8",
        )
        oculto = repo / ".obsidian"
        oculto.mkdir()
        (oculto / "secreto.md").write_text("nao copiar " + "Z" * 20 + "\n", encoding="utf-8")
        self._git("init", "-b", "main", str(repo))
        return repo

    def test_assistente_preenche_pastas_e_monta_o_indice(self):
        from jarvis.envfile import read_env
        from jarvis.primeiro_uso import Console, main

        repo = self._repo()
        antes = (repo / ".obsidian" / "secreto.md").read_bytes()
        respostas = iter([str(repo), ""])
        saida = []

        def ler(_prompt):
            return next(respostas)

        codigo = main(console=Console(input_fn=ler, output_fn=saida.append))
        self.assertEqual(codigo, 0)
        texto = "\n".join(saida)
        self.assertIn("Tecnologia/Livros", texto)
        self.assertIn("Tecnologia/Vídeos", texto)
        self.assertIn("Cursos", texto)
        self.assertIn("Índice pronto", texto)
        self.assertIn("bom dia", texto)
        self.assertIn("o que tenho hoje", texto)
        self.assertIn("revisão do dia", texto)
        self.assertIn("o que aprendi esta semana", texto)
        self.assertIn("me testa sobre um tema", texto)
        self.assertNotIn("\u2014", texto)
        self.assertNotIn("nao copiar", texto)
        valores = read_env(Path(os.environ["JARVIS_ENV_FILE"]))
        self.assertEqual(valores["JARVIS_VAULT"], str(repo))
        self.assertEqual(valores["JARVIS_LIVROS_PASTA"], "Tecnologia/Livros")
        self.assertEqual(valores["JARVIS_VIDEOS_PASTA"], "Tecnologia/Vídeos")
        self.assertEqual(valores["JARVIS_CURSOS_PASTA"], "Cursos")
        self.assertIn("Tecnologia/Livros", valores["JARVIS_REVISAO_PRIORIDADE"])
        self.assertEqual((repo / ".obsidian" / "secreto.md").read_bytes(), antes)
        self.assertTrue(any(linha.startswith("\rIndice [") and "ETA" in linha for linha in saida))

    def test_pasta_sem_git_nao_grava(self):
        from jarvis.primeiro_uso import Console, main

        solta = self.tmp / "solta"
        solta.mkdir()
        (solta / "nota.md").write_text("# Solta\n\nTexto sintetico.\n", encoding="utf-8")
        saida = []
        codigo = main(
            console=Console(input_fn=lambda _prompt: str(solta), output_fn=saida.append)
        )
        self.assertEqual(codigo, 1)
        self.assertIn("não é um repositório git", "\n".join(saida))
        self.assertFalse(Path(os.environ["JARVIS_ENV_FILE"]).exists())

    def test_sem_configuracao_o_atalho_avisa_fora_do_terminal(self):
        from jarvis.__main__ import main

        with mock.patch("sys.stdin.isatty", return_value=False):
            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                codigo = main([])
        self.assertEqual(codigo, 1)
        self.assertIn("primeiro-uso", buffer.getvalue())
        self.assertEqual(classify("primeiro uso").kind, "primeiro_uso")

    def test_modulos_novos_nao_tem_traco_longo(self):
        for nome in (
            "jarvis/benchmark.py",
            "jarvis/catalogo.py",
            "jarvis/leitura.py",
            "jarvis/primeiro_uso.py",
            "jarvis/progresso.py",
            "jarvis/sintetico.py",
            "tests/test_escala.py",
        ):
            texto = (ROOT / nome).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", texto, nome)
            self.assertNotIn("\u2013", texto, nome)


class ComandoPrimeiroUsoTest(unittest.TestCase):
    def test_voz_explica_sem_abrir_o_vault(self):
        from jarvis.brain import Brain

        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(pasta, ignore_errors=True))
        anterior = os.environ.get("JARVIS_VAULT")
        workspace = os.environ.get("JARVIS_WORKSPACE")
        os.environ.pop("JARVIS_VAULT", None)
        os.environ["JARVIS_WORKSPACE"] = str(pasta / "ws")
        self.addCleanup(lambda: _restaurar("JARVIS_VAULT", anterior))
        self.addCleanup(lambda: _restaurar("JARVIS_WORKSPACE", workspace))
        brain = Brain()
        brain.vault = None
        brain._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("claude"))
        resposta = brain.ask("primeiro uso")
        self.assertIn("python -m jarvis primeiro-uso", resposta)
        self.assertIn("revisão do dia", resposta)
        self.assertNotIn("\u2014", resposta)
        self.assertEqual(classify("Hey Jarvis, primeiro uso").kind, "primeiro_uso")
