import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis import privacidade
from jarvis.catalogo import limpar_catalogo, obter
from jarvis.guardas import NEGAR_TUDO, arquivo_de_hooks, documento_de_hooks
from jarvis.leitura import ler_nota
from jarvis.privacidade import (
    ARQUIVO_SIGILO,
    REGRA_OCULTAS,
    REGRA_OCULTOS,
    REGRA_TUDO,
    avaliar_leitura,
    frases_sigilosas,
    nota_sigilosa,
    notas_sigilosas,
    regras_de_leitura,
)

ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_LOG",
    "JARVIS_PASTAS_PRIVADAS",
    "JARVIS_TAG_SIGILOSA",
)
SEGREDO = "SEGREDO-SINTETICO-4455"
TITULO = "TITULO-RESERVADO-SINTETICO"


def _nota(path, texto, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding=encoding, newline="\n")


class SigiloNoClaudeTest(unittest.TestCase):
    def setUp(self):
        self.saved = {chave: os.environ.get(chave) for chave in ENV}
        for chave in ENV:
            os.environ.pop(chave, None)
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.vault = self.tmp / "vault"
        self.home = self.tmp / "home"
        self.vault.mkdir()
        self.home.mkdir()
        os.environ["JARVIS_HOME"] = str(self.home)
        os.environ["JARVIS_LOG"] = str(self.home / "jarvis.log")
        os.environ["JARVIS_VAULT"] = str(self.vault)
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        privacidade._SIGILO.clear()
        limpar_catalogo()
        self.addCleanup(self._limpar)

    def _limpar(self):
        privacidade._SIGILO.clear()
        limpar_catalogo()
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _vault_basico(self):
        _nota(self.vault / "Publica.md", "# Publica\n\nTexto aberto sintetico.\n")
        _nota(
            self.vault / "Notas" / "marcada.md",
            "# " + TITULO + "\n\n#sigiloso\n" + SEGREDO + "\n",
        )
        _nota(
            self.vault / "Notas" / "frontmatter.md",
            "---\ntags:\n  - sigiloso\n---\n\n# Outra\n\n" + SEGREDO + "\n",
        )

    def _envelhecer(self):
        for nota in self.vault.rglob("*.md"):
            os.utime(nota, (1_700_000_000, 1_700_000_000))

    def test_tag_no_fim_de_nota_longa_conta_como_sigilosa(self):
        longa = self.vault / "Transcricoes" / "longa.md"
        _nota(
            longa,
            "# Transcricao\n\n" + ("linha sintetica de transcricao\n" * 4000) + SEGREDO + "\n\n#sigiloso\n",
        )
        self.assertGreater(longa.stat().st_size, 100_000)
        self.assertTrue(nota_sigilosa(self.vault, longa))
        motivo = avaliar_leitura({"tool_name": "Read", "tool_input": {"file_path": str(longa)}})
        self.assertIn("sigilosa", motivo)
        self.assertNotIn(SEGREDO, motivo)
        self.assertEqual(notas_sigilosas(self.vault), ["Transcricoes/longa.md"])
        texto, _digest = ler_nota(longa, "Transcricoes/longa.md")
        self.assertIn("#sigiloso", texto)
        self.assertNotIn(SEGREDO, texto)
        self.assertTrue(obter(self.vault).notas["Transcricoes/longa.md"].sigilosa)

    def test_nota_utf16_do_bloco_de_notas_conta_como_sigilosa(self):
        nota = self.vault / "Notas" / "bloco.md"
        nota.parent.mkdir(parents=True, exist_ok=True)
        nota.write_bytes(("# Bloco\r\n\r\n#sigiloso\r\n" + SEGREDO + "\r\n").encode("utf-16"))
        self.assertTrue(nota_sigilosa(self.vault, nota))
        self.assertEqual(notas_sigilosas(self.vault), ["Notas/bloco.md"])

    def test_lista_traz_tag_frontmatter_e_pasta_privada_sem_pasta_oculta(self):
        self._vault_basico()
        os.environ["JARVIS_PASTAS_PRIVADAS"] = "cofre"
        _nota(self.vault / "Cofre" / "interno.md", "# Interno\n\n" + SEGREDO + "\n")
        _nota(self.vault / ".trash" / "apagada.md", "# Apagada\n\n#sigiloso\n" + SEGREDO + "\n")
        achadas = notas_sigilosas(self.vault)
        self.assertEqual(
            sorted(achadas),
            ["Cofre/interno.md", "Notas/frontmatter.md", "Notas/marcada.md"],
        )
        regras = regras_de_leitura(self.vault)
        self.assertEqual(regras[:2], [REGRA_OCULTAS, REGRA_OCULTOS])
        self.assertIn("Read(./Cofre/**)", regras)
        self.assertIn("Read(./cofre/**)", regras)
        self.assertIn("Read(./**/cofre/**)", regras)
        self.assertIn("Read(./Notas/marcada.md)", regras)
        self.assertIn("Read(./Notas/frontmatter.md)", regras)
        self.assertNotIn("Read(./Publica.md)", regras)
        self.assertNotIn("Read(./Cofre/interno.md)", regras)
        self.assertEqual(len(regras), len(set(regras)))
        for regra in regras:
            self.assertNotIn(SEGREDO, regra)

    def test_segunda_passagem_nao_rele_e_nota_alterada_muda_de_lado(self):
        self._vault_basico()
        self._envelhecer()
        self.assertEqual(len(notas_sigilosas(self.vault)), 2)
        with mock.patch.object(privacidade, "_ler", side_effect=AssertionError("releu")):
            self.assertEqual(len(notas_sigilosas(self.vault)), 2)
        privacidade._SIGILO.clear()
        with mock.patch.object(privacidade, "_ler", side_effect=AssertionError("releu do disco")):
            self.assertEqual(len(notas_sigilosas(self.vault)), 2)
        _nota(self.vault / "Publica.md", "# Publica\n\nAgora reservada.\n\n#sigiloso\n")
        _nota(self.vault / "Notas" / "marcada.md", "# " + TITULO + "\n\nLiberada de novo.\n")
        self.assertEqual(sorted(notas_sigilosas(self.vault)), ["Notas/frontmatter.md", "Publica.md"])
        (self.vault / "Notas" / "frontmatter.md").unlink()
        self.assertEqual(notas_sigilosas(self.vault), ["Publica.md"])

    def test_arquivo_local_nao_guarda_titulo_caminho_nem_texto(self):
        self._vault_basico()
        notas_sigilosas(self.vault)
        guardado = (self.home / ARQUIVO_SIGILO).read_text(encoding="utf-8")
        self.assertNotIn(SEGREDO, guardado)
        self.assertNotIn(TITULO, guardado)
        self.assertNotIn("marcada", guardado)
        self.assertNotIn("frontmatter", guardado)
        self.assertNotIn(str(self.vault), guardado)
        self.assertEqual(len(json.loads(guardado)["notas"]), 3)
        if os.name != "nt":
            self.assertEqual((self.home / ARQUIVO_SIGILO).stat().st_mode & 0o777, 0o600)

    def test_nome_com_sinal_especial_vira_curinga_na_regra(self):
        _nota(
            self.vault / "Notas" / "Reuniao (cliente) [rascunho] {a}!.md",
            "# Reuniao\n\n#sigiloso\n" + SEGREDO + "\n",
        )
        _nota(self.vault / "Notas" / "fim com espaco .md", "# Fim\n\n#sigiloso\n")
        regras = regras_de_leitura(self.vault)
        self.assertIn("Read(./Notas/Reuniao ?cliente? ?rascunho? ?a??.md)", regras)
        self.assertIn("Read(./Notas/fim com espaco .md)", regras)
        for regra in regras[2:]:
            miolo = regra[len("Read(") : -1]
            for sinal in "()[]{}!*\\'\"":
                self.assertNotIn(sinal, miolo.replace("/**", ""), regra)

    def test_muitas_notas_viram_regra_de_pasta_e_raiz_fecha_tudo(self):
        for indice in range(privacidade._TETO_REGRAS + 5):
            _nota(self.vault / "Diario" / f"dia-{indice:04d}.md", "# Dia\n\n#sigiloso\n")
        regras = regras_de_leitura(self.vault)
        self.assertEqual(regras, [REGRA_OCULTAS, REGRA_OCULTOS, "Read(./Diario/**)"])
        privacidade._SIGILO.clear()
        for indice in range(privacidade._TETO_REGRAS + 5):
            _nota(self.vault / f"solta-{indice:04d}.md", "# Solta\n\n#sigiloso\n")
        self.assertEqual(regras_de_leitura(self.vault), [REGRA_TUDO])

    def test_arquivo_do_claude_leva_as_regras_e_fecha_se_a_lista_falhar(self):
        self._vault_basico()
        documento = json.loads(arquivo_de_hooks().read_text(encoding="utf-8"))
        negadas = documento["permissions"]["deny"]
        self.assertIn(REGRA_OCULTAS, negadas)
        self.assertIn(REGRA_OCULTOS, negadas)
        self.assertIn("Read(./Notas/marcada.md)", negadas)
        self.assertIn("PreToolUse", documento["hooks"])
        self.assertNotIn(SEGREDO, json.dumps(documento))
        with mock.patch.object(privacidade, "regras_de_leitura", side_effect=RuntimeError("falha")):
            fechado = json.loads(arquivo_de_hooks().read_text(encoding="utf-8"))
        self.assertEqual(fechado["permissions"]["deny"], [NEGAR_TUDO])
        self.assertEqual(NEGAR_TUDO, REGRA_TUDO)
        self.assertNotIn("permissions", documento_de_hooks("echo ok"))
        os.environ.pop("JARVIS_VAULT", None)
        sem_vault = json.loads(arquivo_de_hooks().read_text(encoding="utf-8"))
        self.assertNotIn("permissions", sem_vault)

    def test_frases_sigilosas_saem_so_das_notas_reservadas(self):
        self._vault_basico()
        self._envelhecer()
        frases = frases_sigilosas(self.vault)
        self.assertIn(TITULO, frases)
        self.assertNotIn("Publica", frases)
        lidos = []
        original = privacidade._ler

        def contar(path, *args, **kwargs):
            lidos.append(Path(path).name)
            return original(path, *args, **kwargs)

        with mock.patch.object(privacidade, "_ler", side_effect=contar):
            frases_sigilosas(self.vault)
        self.assertNotIn("Publica.md", lidos)


if __name__ == "__main__":
    unittest.main()
