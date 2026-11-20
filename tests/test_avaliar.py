import os
import tempfile
import unittest
from pathlib import Path

from jarvis.avaliar import EXAMPLE_VAULT, EXAMPLE_YAML, load_cases, main, medir, pessoal_path

ROOT = Path(__file__).resolve().parents[1]


class AvaliarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self._env = {
            key: os.environ.get(key)
            for key in ("JARVIS_HOME", "JARVIS_VAULT", "JARVIS_VAULT_REMOTE")
        }
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ.pop("JARVIS_VAULT", None)
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_repo_so_tem_o_exemplo_inventado(self):
        yamls = []
        for path in ROOT.rglob("*.yaml"):
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith(".") or "/.venv/" in relative or relative.startswith(".venv/"):
                continue
            yamls.append(relative)
        self.assertEqual(yamls, ["avaliacao/exemplo.yaml"])
        text = EXAMPLE_YAML.read_text(encoding="utf-8")
        self.assertNotIn("@", text)
        self.assertNotIn("lucas", text.casefold())
        self.assertNotIn("\u2014", text)
        for path in EXAMPLE_VAULT.rglob("*.md"):
            body = path.read_text(encoding="utf-8")
            self.assertNotIn("@", body)
            self.assertNotIn("lucas", body.casefold())
            self.assertFalse(any(part == ".obsidian" for part in path.parts))

    def test_arvore_publica_nao_traz_identidade(self):
        marcadores = (
            "lucas" + "rmagalhaes",
            "lucas" + "darosa",
            "fiergs" + ".org.br",
            "vault-" + "pessoal",
            "lucas" + "@gmail.com",
            "play" + "tune",
            "agil" + "inm",
        )
        ignorar = {".git", ".venv", "__pycache__"}
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignorar for part in path.parts):
                continue
            if path.suffix.lower() in {".png", ".pyc"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            for marker in marcadores:
                self.assertNotIn(marker, text, path.relative_to(ROOT).as_posix())

    def test_perguntas_reais_ficam_fora_do_git(self):
        path = pessoal_path()
        self.assertEqual(path.name, "avaliacao.yaml")
        self.assertNotEqual(path, EXAMPLE_YAML)
        self.assertFalse(str(path).startswith(str(ROOT)))
        self.assertFalse(path.exists())

    def test_exemplo_mede_acerto_e_recusa(self):
        casos = load_cases(EXAMPLE_YAML.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(casos), 4)
        report = medir(EXAMPLE_VAULT, casos, embedder=None)
        self.assertEqual(report["acertos"], report["positivos"])
        self.assertGreater(report["positivos"], 0)
        self.assertEqual(report["recusas"], report["negativos"])
        self.assertGreater(report["negativos"], 0)
        self.assertTrue(report["ok"])
        self.assertEqual(main(["--exemplo"]), 0)

    def test_arquivo_local_ausente_nao_quebra_e_vazio_falha_sem_ler_nota_real(self):
        self.assertEqual(main(["--exemplo"]), 0)
        pessoal = pessoal_path()
        pessoal.parent.mkdir(parents=True, exist_ok=True)
        pessoal.write_text("casos:\n  - pergunta: \"nada\"\n    evidencia: false\n", encoding="utf-8")
        os.environ["JARVIS_VAULT"] = str(self.tmp / "ausente")
        self.assertEqual(main([]), 1)
        pessoal.write_text(
            "casos:\n  - pergunta: \"receita de bolo de chocolate belga\"\n    evidencia: false\n",
            encoding="utf-8",
        )
        os.environ["JARVIS_VAULT"] = str(EXAMPLE_VAULT)
        code = main([])
        self.assertEqual(code, 0)
