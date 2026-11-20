import importlib.util
import os
import random
import shutil
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from jarvis import busca, catalogo
from jarvis.busca import (
    Gramas,
    exact_do_texto,
    exact_from_words,
    fold,
    fuzzy_do_texto,
    fuzzy_from_tokens,
    tem_palavra,
)
from jarvis.catalogo import _preparar, _tags, limpar_catalogo, obter
from jarvis.leitura import ler_nota, ler_nota_marcada
from jarvis.review import scan_cards
from jarvis.routines import fold as fold_das_rotinas
from jarvis.routines import hybrid_notes

TEM_NUMPY = importlib.util.find_spec("numpy") is not None
ENV = ("JARVIS_HOME", "JARVIS_VAULT", "JARVIS_VAULT_SYNC", "JARVIS_LOG", "JARVIS_PASTAS_IGNORADAS")


def fold_antigo(text):
    normalized = unicodedata.normalize("NFKD", text or "")
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return plain.casefold()


def _nota(path, texto):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8", newline="\n")


class DobraTest(unittest.TestCase):
    def test_todo_caractere_dobra_como_antes(self):
        for codigo in range(sys.maxunicode + 1):
            if 0xD800 <= codigo <= 0xDFFF:
                continue
            amostra = "a" + chr(codigo) + "́Z"
            if fold(amostra) != fold_antigo(amostra):
                self.fail("caractere U+%04X dobra diferente" % codigo)

    def test_sequencias_com_marca_combinante_dobram_como_antes(self):
        sorteio = random.Random(771)
        pontos = [
            0x41, 0x61, 0x20, 0x0A, 0xE9, 0xC7, 0x301, 0x327, 0x323, 0x1E9B, 0xFB01, 0x212A,
            0x17F, 0x130, 0x3A3, 0x4E2D, 0x1F600, 0xAC00, 0x93C, 0x5D0, 0x5B4, 0x2126, 0xDF,
        ]
        for _ in range(20000):
            amostra = "".join(chr(sorteio.choice(pontos)) for _ in range(sorteio.randint(0, 14)))
            self.assertEqual(fold(amostra), fold_antigo(amostra), repr(amostra))

    def test_frases_e_vazio(self):
        for amostra in ("", None, "Revisão ÀS 14h, Ação e Coração", "ＡＢＣ ﬁ ½ Ω", "texto so ascii"):
            self.assertEqual(fold(amostra), fold_antigo(amostra))
            self.assertEqual(fold_das_rotinas(amostra), fold_antigo(amostra))


class FiltroPeloTextoTest(unittest.TestCase):
    def test_exato_e_grafia_pelo_texto_repetem_o_filtro_por_palavras(self):
        sorteio = random.Random(1594)
        silabas = ["ca", "che", "ku", "ber", "ne", "tes", "au", "ten", "ti", "ca", "cao", "id", "em", "po", "x9", "re", "vi", "sao"]

        def palavra():
            return "".join(sorteio.choice(silabas) for _ in range(sorteio.randint(1, 5)))

        vocabulario = [palavra() for _ in range(400)]
        for _ in range(1500):
            partes = [sorteio.choice(vocabulario) for _ in range(sorteio.randint(0, 60))]
            separadores = [" ", "\n", ", ", " - ", ".", "/", "_", "  "]
            texto = "".join(parte + sorteio.choice(separadores) for parte in partes)
            dobrado = fold(texto)
            palavras = tuple(busca._WORD_RE.findall(dobrado))
            consulta = [sorteio.choice(vocabulario) for _ in range(sorteio.randint(0, 3))]
            consulta.append(sorteio.choice(vocabulario)[:-1] + "z")
            consulta.append(sorteio.choice(vocabulario) + sorteio.choice(vocabulario)[:2])
            consulta.append(sorteio.choice(["ab", "multi-tenancy", "kuber-netes", "x", "id", "a.b.c.d.e"]))
            self.assertEqual(exact_do_texto(consulta, dobrado), exact_from_words(consulta, palavras), (consulta, texto))
            self.assertEqual(fuzzy_do_texto(consulta, dobrado), fuzzy_from_tokens(consulta, palavras), (consulta, texto))

    def test_palavra_inteira_nao_casa_pedaco(self):
        dobrado = fold("O Kubernetes roda no cluster.\nAutenticação por token.")
        self.assertTrue(tem_palavra(dobrado, "kubernetes"))
        self.assertTrue(tem_palavra(dobrado, "autenticacao"))
        self.assertFalse(tem_palavra(dobrado, "kubernete"))
        self.assertFalse(tem_palavra(dobrado, "bernetes"))
        self.assertFalse(tem_palavra(dobrado, "no"))
        self.assertFalse(tem_palavra(dobrado, "token."))
        self.assertEqual(fuzzy_do_texto(["kubernets"], dobrado), 1)
        self.assertEqual(fuzzy_do_texto(["kuber"], dobrado), 0)
        self.assertEqual(fuzzy_do_texto([], dobrado), 0)
        self.assertEqual(exact_do_texto([], dobrado), 0)


class GramasTest(unittest.TestCase):
    @unittest.skipUnless(TEM_NUMPY, "numpy ausente")
    def test_vetor_com_numpy_e_identico_ao_puro(self):
        sorteio = random.Random(36)
        alfabeto = "abcdefghijklmnopqrstuvwxyz0123456789"
        vocabulario = [
            "".join(sorteio.choice(alfabeto) for _ in range(sorteio.randint(2, 12))) for _ in range(700)
        ]
        for tamanho in (0, 1, 5, 63, 64, 65, 400, 2500):
            for _ in range(6):
                palavras = tuple(sorteio.choice(vocabulario) for _ in range(tamanho))
                rapido = Gramas.das_palavras(palavras)
                with mock.patch.dict(sys.modules, {"numpy": None}):
                    puro = Gramas.das_palavras(palavras)
                self.assertEqual(rapido.chaves.tobytes(), puro.chaves.tobytes())
                self.assertEqual(rapido.valores.tobytes(), puro.valores.tobytes())
                self.assertEqual(rapido.chaves.typecode, puro.chaves.typecode)
                self.assertEqual(rapido.norma, puro.norma)

    @unittest.skipUnless(TEM_NUMPY, "numpy ausente")
    def test_teto_da_contagem_e_palavra_fora_do_alfabeto(self):
        repetida = ("z" * 9,) * 70000
        rapido = Gramas.das_palavras(repetida)
        with mock.patch.dict(sys.modules, {"numpy": None}):
            puro = Gramas.das_palavras(repetida)
        self.assertEqual(max(rapido.valores), 65535)
        self.assertEqual(rapido.valores.tobytes(), puro.valores.tobytes())
        self.assertEqual(rapido.norma, puro.norma)
        estranhas = tuple(["acao", "coração", "a-b-c", "água"] * 40)
        com = Gramas.das_palavras(estranhas)
        with mock.patch.dict(sys.modules, {"numpy": None}):
            sem = Gramas.das_palavras(estranhas)
        self.assertEqual(com.chaves.tobytes(), sem.chaves.tobytes())
        self.assertEqual(com.valores.tobytes(), sem.valores.tobytes())

    def test_palavra_repetida_soma_como_antes(self):
        def antigo(palavras):
            counts = {}
            for word in palavras:
                if len(word) < 3:
                    continue
                padded = "<" + word + ">"
                for index in range(len(padded) - 2):
                    codigo = busca._codigo_trio(padded[index], padded[index + 1], padded[index + 2])
                    if codigo is None:
                        continue
                    counts[codigo] = counts.get(codigo, 0) + 1
            return sorted(counts.items())

        palavras = ("banana", "banana", "ana", "ab", "bananada", "aaa", "aaaa")
        with mock.patch.dict(sys.modules, {"numpy": None}):
            novo = Gramas.das_palavras(palavras)
        self.assertEqual(list(zip(novo.chaves, novo.valores)), antigo(palavras))


class PreparoSobDemandaTest(unittest.TestCase):
    def setUp(self):
        self.saved = {chave: os.environ.get(chave) for chave in ENV}
        for chave in ENV:
            os.environ.pop(chave, None)
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_LOG"] = str(self.tmp / "home" / "jarvis.log")
        os.environ["JARVIS_VAULT"] = str(self.vault)
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        limpar_catalogo()
        self.addCleanup(self._limpar)

    def _limpar(self):
        limpar_catalogo()
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _vault(self):
        _nota(
            self.vault / "Estudos" / "kubernetes.md",
            "---\ntags: [infra, estudo]\n---\n\n# Kubernetes\n\nO cluster de teste escala os pods.\n"
            "Qual objeto escala os pods? ::: o deployment\n",
        )
        _nota(self.vault / "Estudos" / "horta.md", "# Horta\n\nA hortela de teste cresce no vaso.\n")
        _nota(self.vault / "Estudos" / "farol.md", "# Farol\n\nO farol sintetico pisca. #sigiloso\n")
        for indice in range(30):
            _nota(self.vault / "Outras" / f"nota-{indice}.md", f"# Nota {indice}\n\nAssunto solto numero {indice}.\n")
        for nota in self.vault.rglob("*.md"):
            os.utime(nota, (1_700_000_000, 1_700_000_000))

    def test_catalogo_nao_prepara_nada_ate_a_busca(self):
        self._vault()
        notas = obter(self.vault).notas
        self.assertEqual(len(notas), 33)
        self.assertTrue(all(not nota._preparado for nota in notas.values()))
        self.assertTrue(all(nota._tags is None for nota in notas.values()))
        self.assertEqual(notas["Estudos/kubernetes.md"].cartoes, [("Qual objeto escala os pods?", "o deployment")])
        self.assertEqual(notas["Estudos/horta.md"].cartoes, [])
        self.assertTrue(notas["Estudos/farol.md"].sigilosa)
        self.assertFalse(notas["Estudos/horta.md"].sigilosa)
        self.assertEqual(len(scan_cards(self.vault)), 1)
        self.assertTrue(all(not nota._preparado for nota in notas.values()))

    def test_busca_acha_pela_grafia_e_so_calcula_o_necessario(self):
        self._vault()
        achados = hybrid_notes(self.vault, "kubernets", embedder=None, limit=5)
        self.assertEqual([hit.relative for hit in achados], ["Estudos/kubernetes.md"])
        notas = obter(self.vault).notas
        com_gramas = [
            relativo
            for relativo, nota in notas.items()
            if nota._preparo is not None and nota._preparo._gramas is not None
        ]
        self.assertEqual(com_gramas, ["Estudos/kubernetes.md"])
        exato = hybrid_notes(self.vault, "hortela vaso", embedder=None, limit=5)
        self.assertEqual(exato[0].relative, "Estudos/horta.md")
        com_tokens = [
            relativo
            for relativo, nota in notas.items()
            if nota._preparo is not None and nota._preparo._tokens is not None
        ]
        self.assertIn("Estudos/horta.md", com_tokens)
        self.assertLess(len(com_tokens), 5)

    def test_preparo_sob_demanda_entrega_os_mesmos_campos(self):
        pronto = _preparar("Título", "Linha um do TEXTO.\nLinha dois, com ação.")
        self.assertEqual(pronto.dobrado, "titulo\nlinha um do texto.\nlinha dois, com acao.")
        self.assertIsNone(pronto._tokens)
        self.assertEqual(pronto.tokens[:4], ("titulo", "linha", "um", "do"))
        self.assertEqual(pronto.palavras[:3], ("titulo", "linha", "texto"))
        self.assertEqual(pronto.linhas, ("titulo", "linha um do texto.", "linha dois, com acao."))
        self.assertIsInstance(pronto.gramas, Gramas)
        self.assertIs(pronto.gramas, pronto.gramas)
        self.assertIs(pronto.tokens, pronto.tokens)

    def test_tags_saem_sob_demanda_e_falha_no_preparo_nao_derruba(self):
        self._vault()
        nota = obter(self.vault).notas["Estudos/kubernetes.md"]
        self.assertEqual(nota.tags, _tags(nota.texto))
        self.assertIn("infra", nota.tags)
        self.assertIs(nota.tags, nota.tags)
        outra = obter(self.vault).notas["Estudos/horta.md"]
        chamadas = []
        original = catalogo._preparar

        def quebra_uma_vez(titulo, texto):
            chamadas.append(texto)
            if len(chamadas) == 1:
                raise ValueError("falha sintetica")
            return original(titulo, texto)

        with mock.patch.object(catalogo, "_preparar", side_effect=quebra_uma_vez):
            pronto = outra.preparo
        self.assertEqual(chamadas[1], "")
        self.assertEqual(pronto.dobrado, "horta\n")
        self.assertIs(outra.preparo, pronto)

    def test_leitura_marcada_devolve_o_sigilo_e_a_antiga_segue_com_dois_itens(self):
        self._vault()
        texto, digest, sigilosa = ler_nota_marcada(self.vault / "Estudos" / "farol.md", "Estudos/farol.md")
        self.assertTrue(sigilosa)
        self.assertEqual(len(digest), 64)
        self.assertEqual(ler_nota(self.vault / "Estudos" / "farol.md", "Estudos/farol.md"), (texto, digest))
        self.assertEqual(ler_nota_marcada(self.vault / "nao-existe.md"), (None, "", False))
        self.assertFalse(ler_nota_marcada(self.vault / "Estudos" / "horta.md")[2])


if __name__ == "__main__":
    unittest.main()
