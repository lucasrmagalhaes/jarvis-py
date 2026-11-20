import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis.busca import (
    bm25_ranking,
    fuse_rrf,
    in_scope,
    line_bonus,
    parse_scope,
)
from jarvis.consult import answer, reset_libraries
from jarvis.routines import classify, hybrid_notes, run_routine, search_notes, search_speech

NOW = datetime(2026, 10, 28, 11, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
TEM_NUMPY = importlib.util.find_spec("numpy") is not None


def _note(root, relative, body):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class BuscaPuraTest(unittest.TestCase):
    def test_rrf_prefere_quem_esta_nas_duas_listas(self):
        fused = fuse_rrf([["alfa", "beta"], ["beta", "gama"]], key=lambda item: item)
        self.assertEqual(fused[0][1], "beta")

    def test_bm25_sobe_o_termo_repetido(self):
        scores = bm25_ranking(
            ["o gato dorme no sofá curto", "o gato gato gato come peixe raro"],
            ["gato"],
        )
        self.assertGreater(scores[1], scores[0])

    def test_gramas_compactas_repetem_o_cosseno(self):
        from jarvis.busca import (
            Gramas,
            _cosseno_gramas,
            _grams,
            _sparse_cosine,
        )

        texto = "O quartzo sintetico fica na estante da oficina ficticia."
        cheio = _grams(texto)
        compacto = Gramas.da_contagem(cheio)
        consulta = _grams("quartzo estante")
        self.assertAlmostEqual(
            _sparse_cosine(consulta, cheio),
            _sparse_cosine(consulta, compacto),
            places=6,
        )
        pronto = Gramas.da_contagem(consulta)
        self.assertAlmostEqual(
            _sparse_cosine(consulta, cheio),
            _cosseno_gramas(pronto, compacto),
            places=6,
        )
        self.assertGreater(_sparse_cosine(consulta, compacto), 0)

    @unittest.skipUnless(TEM_NUMPY, "numpy ausente")
    def test_cosseno_com_numpy_repete_o_cosseno_puro(self):
        from jarvis.busca import (
            Gramas,
            _consulta_numpy,
            _cosseno_gramas,
            _cosseno_numpy,
            _grams,
        )

        compacto = Gramas.da_contagem(_grams("O quartzo sintetico fica na estante ficticia."))
        pronto = Gramas.da_contagem(_grams("quartzo estante"))
        q, norma = _consulta_numpy(pronto)
        self.assertAlmostEqual(
            _cosseno_gramas(pronto, compacto),
            _cosseno_numpy(q, norma, compacto),
            places=6,
        )

    def test_grafia_sem_numpy_da_a_mesma_ordem(self):
        from jarvis.busca import Gramas, spelling_ranking
        from jarvis.catalogo import _preparar

        textos = [
            "O quartzo sintetico fica na estante da oficina ficticia.",
            "A hortela de teste cresce no vaso da varanda ficticia.",
            "Quartzos sinteticos e estantes aparecem de novo nesta nota.",
        ]
        prontos = [_preparar("nota", texto) for texto in textos]
        self.assertTrue(all(isinstance(item.gramas, Gramas) for item in prontos))
        palavras = ["quartzos", "estantes"]
        with mock.patch.dict(sys.modules, {"numpy": None}):
            puro = spelling_ranking(textos, palavras, caches=prontos)
        self.assertTrue(puro)
        self.assertEqual({indice for _nota, indice in puro}, {0, 2})
        if TEM_NUMPY:
            rapido = spelling_ranking(textos, palavras, caches=prontos)
            self.assertEqual(
                [indice for _nota, indice in puro],
                [indice for _nota, indice in rapido],
            )
            for (nota_pura, _i), (nota_rapida, _j) in zip(puro, rapido):
                self.assertAlmostEqual(nota_pura, nota_rapida, places=6)

    def test_linha_junta_vale_mais_que_termos_separados(self):
        junto = "A revisao ficou para sexta no mesmo paragrafo."
        separado = "A revisao ficou em aberto.\n\nOutro dia, sexta."
        self.assertGreater(line_bonus(junto, ["revisao", "sexta"]), line_bonus(separado, ["revisao", "sexta"]))

    def test_pastas_nomeadas(self):
        livros, pasta = parse_scope("python nos livros")
        self.assertEqual(livros, "python")
        self.assertEqual(pasta, "Tecnologia/Livros")
        videos, pasta = parse_scope("farol nos vídeos")
        self.assertEqual(videos, "farol")
        self.assertEqual(pasta, "Tecnologia/Vídeos")
        cursos, pasta = parse_scope("oficina nos cursos")
        self.assertEqual(cursos, "oficina")
        self.assertEqual(pasta, "Tecnologia/Cursos")
        self.assertTrue(in_scope("Tecnologia/Livros/hortela.md", "Tecnologia/Livros"))
        self.assertFalse(in_scope("Tecnologia/Cursos/hortela.md", "Tecnologia/Livros"))
        self.assertFalse(in_scope(".obsidian/plugin.md", ""))


class BuscaNoVaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "vault"
        self.root.mkdir()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        reset_libraries()
        self.addCleanup(reset_libraries)
        _note(
            self.root,
            "Tecnologia/Livros/hortela.md",
            "# Hortela de teste\n\n"
            "A hortela de teste cresce no livro ficticio de prateleira, sem pessoa real.\n",
        )
        _note(
            self.root,
            "Tecnologia/Vídeos/farol.md",
            "# Farol ficticio\n\n"
            "O farol ficticio deste video de teste acende luz amarela num porto inventado.\n",
        )
        _note(
            self.root,
            "Tecnologia/Cursos/oficina.md",
            "# Oficina de teste\n\n"
            "A oficina de teste deste curso ficticio monta um vaso de papel em tres passos.\n",
        )
        _note(
            self.root,
            "Diario/solta.md",
            "# Solta\n\nA hortela de teste tambem aparece nesta nota solta do diario ficticio.\n",
        )
        hidden = self.root / ".obsidian"
        hidden.mkdir()
        (hidden / "escondido.md").write_text(
            "# Escondido\n\nA hortela de teste no obsidian nao pode entrar na resposta.\n",
            encoding="utf-8",
        )

    def test_busca_do_vault_responde_sem_numpy(self):
        with mock.patch.dict(sys.modules, {"numpy": None}):
            hits = hybrid_notes(self.root, "hortelas dos livros")
            fala = search_speech(self.root, "hortela nos livros")
        self.assertTrue(hits)
        self.assertIn("caminho Tecnologia/Livros/hortela.md", fala)

    def test_filtro_de_pasta_e_citacao(self):
        hits = hybrid_notes(self.root, "hortela nos livros")
        self.assertEqual([hit.relative for hit in hits], ["Tecnologia/Livros/hortela.md"])
        speech = search_speech(self.root, "hortela nos livros")
        self.assertIn("caminho Tecnologia/Livros/hortela.md", speech)
        self.assertIn("hortela", speech.casefold())
        self.assertNotIn(".obsidian", speech)
        self.assertNotIn("\u2014", speech)
        videos = run_routine(self.root, classify("o que anotei sobre farol nos vídeos"), NOW)
        self.assertIn("Tecnologia/Vídeos/farol.md", videos)
        self.assertNotIn("hortela.md", videos)
        cursos = run_routine(self.root, classify("o que anotei sobre oficina nos cursos"), NOW)
        self.assertIn("Tecnologia/Cursos/oficina.md", cursos)

    def test_obsidian_fica_de_fora_e_a_nota_junta_vem_na_frente(self):
        loose = self.root / "Notas"
        loose.mkdir()
        (loose / "solta2.md").write_text(
            "# Solta\n\nA revisao ficou em aberto.\n\nOutro dia, sexta.\n",
            encoding="utf-8",
        )
        tight = self.root / "Diario" / "Play.md"
        tight.write_text(
            "# Play\n\nA revisao ficou para sexta no mesmo paragrafo ficticio.\n",
            encoding="utf-8",
        )
        hits = search_notes(self.root, "revisao sexta")
        self.assertEqual(hits[0].relative, "Diario/Play.md")
        self.assertTrue(all(".obsidian" not in hit.relative for hit in hits))
        spoken = search_speech(self.root, "revisao sexta")
        self.assertIn("caminho Diario/Play.md", spoken)

    def test_consulta_cita_a_pasta_e_recusa_sem_evidencia(self):
        found = answer(self.root, "hortela nos livros", embedder=None)
        self.assertTrue(found["evidence"])
        self.assertEqual(found["sources"][0]["path"], "Tecnologia/Livros/hortela.md")
        self.assertIn("caminho", found["answer"])
        self.assertNotIn(".obsidian", found["answer"])
        missing = answer(self.root, "receita de bolo de chocolate belga", embedder=None)
        self.assertFalse(missing["evidence"])
        self.assertIn("Não há evidência", missing["answer"])

    def test_sem_embeddings_cai_para_palavra_e_com_stub_usa_o_modelo(self):
        _note(
            self.root,
            "Diario/aroma.md",
            "# Aroma\n\nO cultivo de folhas aromaticas fica na caixa azul do laboratorio ficticio.\n",
        )

        class Stub:
            def embed(self, texts):
                rows = []
                for text in texts:
                    folded = text.casefold()
                    if "aromatic" in folded or "varanda" in folded:
                        rows.append([1.0, 0.0])
                    else:
                        rows.append([0.0, 1.0])
                return rows

        plain = hybrid_notes(self.root, "ervas na varanda do predio", embedder=None)
        self.assertFalse(any(hit.relative == "Diario/aroma.md" for hit in plain))
        ranked = hybrid_notes(self.root, "ervas na varanda do predio", embedder=Stub())
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].relative, "Diario/aroma.md")


class CompatibilidadeTest(unittest.TestCase):
    def test_modulos_novos_nao_importam_sounddevice_nem_traco_longo(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("jarvis/busca.py", "jarvis/guardas.py", "jarvis/avaliar.py"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("sounddevice", text)
            self.assertNotIn("\u2014", text)
            self.assertNotIn("\u2013", text)
