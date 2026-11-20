"""Versão, atualização e relatório. Notas e segredos daqui são sintéticos."""

import io
import os
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

SEGREDO = "segredo-sintetico-jarvis-91af"
NOTA = "nota-sintetica-jarvis-91af"
CHAVES = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_WORKSPACE",
    "JARVIS_LOG",
    "JARVIS_STATE",
    "JARVIS_REVISAO",
    "JARVIS_ENV_FILE",
    "JARVIS_ATUALIZAR",
    "JARVIS_ATUALIZAR_TIMEOUT",
    "JARVIS_CONTEXTO",
    "JARVIS_RELATORIO_PASTA",
    "JARVIS_RELATORIO_LINHAS",
    "GMAIL_APP_PASSWORD",
)


class ManutencaoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile_dir())
        self.saved = {chave: os.environ.get(chave) for chave in CHAVES}
        self.head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        for chave in CHAVES:
            os.environ.pop(chave, None)
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_ENV_FILE"] = str(self.tmp / "nenhum.env")
        os.environ["JARVIS_CONTEXTO"] = "off"
        os.environ["JARVIS_ATUALIZAR"] = "on"
        os.environ["JARVIS_REVISAO"] = str(self.tmp / "home" / "revisao.json")

    def tearDown(self):
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        agora = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.assertEqual(agora, self.head)

    def test_versao_no_comando_no_doctor_e_na_voz(self):
        import jarvis
        from jarvis.__main__ import main
        from jarvis.__version__ import __version__, fala
        from jarvis.brain import Brain
        from jarvis.doctor import cabecalho, check_version
        from jarvis.panel import preparar_html
        from jarvis.resumo import build_resumo, render_resumo
        from jarvis.routines import classify

        self.assertEqual(jarvis.__version__, "0.34.0")
        self.assertEqual(__version__, "0.34.0")
        self.assertIn("0.34.0", fala())
        self.assertEqual(classify("qual sua versão?").kind, "version")
        self.assertEqual(classify("Hey Jarvis, qual a sua versão?").kind, "version")
        buffer = io.StringIO()
        with mock.patch("sys.stdout", buffer):
            self.assertEqual(main(["--versao"]), 0)
        self.assertEqual(buffer.getvalue().strip(), "0.34.0")
        self.assertIn("0.34.0", cabecalho())
        from jarvis import doctor

        doctor.results.clear()
        texto = io.StringIO()
        with mock.patch("sys.stdout", texto):
            check_version()
        self.assertIn("Versão", texto.getvalue())
        self.assertIn("0.34.0", texto.getvalue())
        doctor.results.clear()

        brain = Brain()
        brain.vault = None
        resposta = brain.ask("qual sua versão?")
        self.assertIn("0.34.0", resposta)
        self.assertNotIn("\u2014", resposta)

        html = (ROOT / "jarvis" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("__JARVIS_VERSION__", html)
        pronto = preparar_html(html.encode("utf-8"), "tok", "arq", "0.25.0")
        self.assertIn("Versão 0.25.0".encode("utf-8"), pronto)
        self.assertNotIn(b"__JARVIS_VERSION__", pronto)
        payload = build_resumo(None)
        self.assertEqual(payload["versao"], "0.34.0")
        pagina = render_resumo(payload, "tok")
        self.assertIn("Versão 0.34.0", pagina)
        self.assertNotIn(SEGREDO, pagina)
        self.assertNotIn(NOTA, pagina)

    def test_se_atualiza_pede_confirmacao_e_o_telegram_tem_botoes(self):
        from jarvis.atualizar import Resultado
        from jarvis.brain import Brain
        from jarvis.remoto import frase_do_botao, teclado_da_resposta

        brain = Brain()
        brain.vault = None
        pedido = brain.ask("se atualiza")
        self.assertIn("sim", pedido.casefold())
        self.assertIn("vault", pedido.casefold())
        self.assertEqual(brain.pending["kind"], "atualizar")
        self.assertEqual(
            teclado_da_resposta("se atualiza"),
            [[("Sim", "atu:sim"), ("Agora não", "atu:nao")]],
        )
        self.assertEqual(frase_do_botao("atu:sim", {}), "sim")
        self.assertEqual(frase_do_botao("atu:nao", {}), "nao")
        with mock.patch(
            "jarvis.atualizar.concluir",
            return_value=Resultado(True, "Atualizei o código do Jarvis, senhor.", ""),
        ) as chamado:
            feito = brain.ask("sim")
        chamado.assert_called_once()
        self.assertIn("Atualizei", feito)
        brain.ask("se atualiza")
        with mock.patch("jarvis.atualizar.concluir", side_effect=AssertionError("git")):
            recusa = brain.ask("não")
        self.assertIn("Não atualizei", recusa)
        os.environ["JARVIS_ATUALIZAR"] = "off"
        desligada = brain.ask("se atualiza")
        self.assertIn("desligada", desligada)
        self.assertIsNone(brain.pending)

    def test_git_recusa_forca_sujeira_conflito_e_o_vault(self):
        from jarvis.atualizar import AtualizarErro, concluir, validar

        with self.assertRaises(AtualizarErro) as forca:
            validar(["pull", "--force"])
        self.assertIn("forçada", forca.exception.fala)
        with self.assertRaises(AtualizarErro):
            validar(["push", "origin", "main"])
        with self.assertRaises(AtualizarErro):
            validar(["reset", "--hard"])
        validar(["pull", "--ff-only"])

        mesmo = self.tmp / "igual"
        mesmo.mkdir()

        def proibido(args, cwd):
            del args, cwd
            raise AssertionError("git no vault")

        recusa = concluir(raiz=mesmo, vault=mesmo, runner=proibido)
        self.assertFalse(recusa.ok)
        self.assertIn("mesmo caminho", recusa.fala)

        codigo, vault = self._par_de_repos()
        self._commit(codigo, {"CHANGELOG.md": "# Changelog\n\n## 0.1.0\n\n- Base.\n"})
        (codigo / "sujo.txt").write_text("sujo sintetico\n", encoding="utf-8", newline="\n")
        sujo = concluir(raiz=codigo, vault=vault, runner=None, instalador=self._pip_proibido, fumaca=self._fumaca_ok)
        self.assertFalse(sujo.ok)
        self.assertIn("Não puxei", sujo.fala)
        self.assertIn("sujo.txt", sujo.fala)
        self.assertNotIn(NOTA, sujo.fala)

        limpo, vault_limpo, origem = self._clone_com_avanco()
        (limpo / "local.txt").write_text("lado local\n", encoding="utf-8", newline="\n")
        self._commit(limpo, None)
        (origem / "remoto.txt").write_text("lado remoto\n", encoding="utf-8", newline="\n")
        self._commit(origem, None)
        conflito = concluir(
            raiz=limpo,
            vault=vault_limpo,
            instalador=self._pip_proibido,
            fumaca=self._fumaca_ok,
        )
        self.assertFalse(conflito.ok)
        self.assertIn("Não forcei", conflito.fala)
        self.assertTrue((limpo / "local.txt").is_file())
        self.assertFalse((limpo / "remoto.txt").exists())
        self.assertFalse((limpo / ".git" / "MERGE_HEAD").exists())
        self.assertNotIn(NOTA, conflito.fala + conflito.detalhe)

    def test_pull_ff_only_reinstala_e_le_o_changelog(self):
        from jarvis.atualizar import concluir

        local, vault, _origem = self._clone_com_avanco()
        instalados = []

        def instalador(path):
            instalados.append(Path(path))
            return 0

        antes = self._rev(vault)
        resultado = concluir(
            raiz=local,
            vault=vault,
            instalador=instalador,
            fumaca=self._fumaca_ok,
        )
        self.assertTrue(resultado.ok, resultado.fala)
        self.assertIn("0.26.0", resultado.fala)
        self.assertIn("changelog", resultado.fala.casefold())
        self.assertIn("O vault não foi alterado", resultado.fala)
        self.assertIn("linha nova do changelog", resultado.detalhe)
        self.assertNotIn(SEGREDO, resultado.fala + resultado.detalhe)
        self.assertNotIn(NOTA, resultado.fala + resultado.detalhe)
        self.assertEqual(self._rev(vault), antes)
        self.assertTrue(instalados)
        self.assertEqual(instalados[0].name, "requirements.txt")
        self.assertTrue(str(instalados[0]).startswith(str(local.resolve())))
        self.assertNotIn(str(vault.resolve()), str(instalados[0]))
        recibo = (self.tmp / "home" / "atualizacao.txt").read_text(encoding="utf-8")
        self.assertIn("versao=0.26.0", recibo)
        self.assertNotIn(SEGREDO, recibo)
        self.assertNotIn(NOTA, recibo)

    def test_runner_nao_recebe_o_vault_nem_forca(self):
        from jarvis.atualizar import SaidaGit, concluir

        codigo = self.tmp / "codigo"
        vault = self.tmp / "vault"
        codigo.mkdir()
        vault.mkdir()
        (codigo / "requirements.txt").write_text("packaging>=23\n", encoding="utf-8", newline="\n")
        (codigo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## 0.26.0\n\n- linha nova do changelog\n",
            encoding="utf-8",
            newline="\n",
        )
        (codigo / "jarvis").mkdir()
        (codigo / "jarvis" / "__version__.py").write_text(
            '__version__ = "0.26.0"\n',
            encoding="utf-8",
            newline="\n",
        )
        chamadas = []
        antiga = "a" * 40
        nova = "b" * 40

        def runner(args, cwd):
            chamadas.append(list(args))
            self.assertEqual(Path(cwd).resolve(), codigo.resolve())
            self.assertNotIn("--force", args)
            self.assertNotIn("push", args)
            if args == ["rev-parse", "--show-toplevel"]:
                return SaidaGit(0, str(codigo.resolve()) + "\n", "")
            if args == ["rev-parse", "HEAD"]:
                if not any(item == ["pull", "--ff-only"] for item in chamadas):
                    return SaidaGit(0, antiga + "\n", "")
                return SaidaGit(0, nova + "\n", "")
            if args == ["status", "--porcelain"]:
                return SaidaGit(0, "", "")
            if args == ["pull", "--ff-only"]:
                return SaidaGit(0, "", "")
            if args == ["merge-base", "--is-ancestor", antiga, nova]:
                return SaidaGit(0, "", "")
            if args == ["diff", "--name-only", antiga, nova]:
                return SaidaGit(0, "requirements.txt\nREADME.md\n", "")
            raise AssertionError(args)

        vistos = []
        resultado = concluir(
            raiz=codigo,
            vault=vault,
            runner=runner,
            instalador=lambda path: vistos.append(path) or 0,
            fumaca=self._fumaca_ok,
        )
        self.assertTrue(resultado.ok, resultado.fala)
        self.assertIn(["pull", "--ff-only"], chamadas)
        self.assertEqual(chamadas.count(["pull", "--ff-only"]), 1)
        self.assertTrue(vistos)

    def test_relatorio_nao_leva_segredo_nem_nota(self):
        from jarvis.ajustes import relatorio_linhas, relatorio_pasta
        from jarvis.relatorio import criar, linhas_sem_conteudo, texto_ajustes, texto_benchmark

        vault = self.tmp / "vault"
        nota = vault / "Diario" / "pagina.md"
        nota.parent.mkdir(parents=True)
        nota.write_text(
            "# " + NOTA + "\n\n" + SEGREDO + " nao pode sair.\n",
            encoding="utf-8",
            newline="\n",
        )
        log = self.tmp / "jarvis.log"
        log.write_text(
            "2026-11-11 10:00:00,123 INFO " + SEGREDO + " " + NOTA + "\n"
            "Traceback " + NOTA + "\n"
            "2026-11-11 10:00:02 ERROR outra frase\n",
            encoding="utf-8",
            newline="\n",
        )
        os.environ["JARVIS_VAULT"] = str(vault)
        os.environ["JARVIS_LOG"] = str(log)
        os.environ["GMAIL_APP_PASSWORD"] = SEGREDO
        with mock.patch.dict(os.environ, {"JARVIS_RELATORIO_LINHAS": "9999"}):
            self.assertEqual(relatorio_linhas(), 200)
        with mock.patch.dict(os.environ, {"JARVIS_RELATORIO_PASTA": str(self.tmp / "saida")}):
            self.assertEqual(relatorio_pasta(), self.tmp / "saida")
        ajustes = texto_ajustes(os.environ)
        self.assertIn("GMAIL_APP_PASSWORD: definido", ajustes)
        self.assertNotIn(SEGREDO, ajustes)
        livre = linhas_sem_conteudo(log.read_text(encoding="utf-8"), 40)
        self.assertIn("2026-11-11 10:00:00,123 INFO", livre)
        self.assertNotIn(SEGREDO, livre)
        self.assertNotIn(NOTA, livre)
        self.assertNotIn("outra frase", livre)

        def doctor_vazando():
            return "checklist\nsenha=" + SEGREDO + "\n"

        codigo, mensagem, caminho = criar(
            pasta=self.tmp / "saida",
            doctor_fn=doctor_vazando,
            benchmark_fn=lambda: "notas=1\n",
        )
        self.assertEqual(codigo, 0, mensagem)
        self.assertTrue(caminho.is_file())
        self.assertNotIn(SEGREDO, mensagem)
        with zipfile.ZipFile(caminho) as arquivo:
            nomes = arquivo.namelist()
            self.assertEqual(
                nomes,
                [
                    "versao.txt",
                    "sistema.txt",
                    "ajustes.txt",
                    "doctor.txt",
                    "log.txt",
                    "benchmark.txt",
                ],
            )
            bruto = "\n".join(arquivo.read(nome).decode("utf-8") for nome in nomes)
        self.assertNotIn(SEGREDO, bruto)
        self.assertNotIn(NOTA, bruto)
        self.assertNotIn("nao pode sair", bruto)
        self.assertIn("GMAIL_APP_PASSWORD: definido", bruto)
        self.assertIn("[definido]", bruto)
        self.assertIn("versao=0.34.0", bruto)
        self.assertIn("python=", bruto)
        self.assertIn("notas=1", bruto)
        self.assertNotIn(".md", " ".join(nomes))

        recusado, frase, nada = criar(pasta=vault, doctor_fn=lambda: "ok\n", benchmark_fn=lambda: "ok\n")
        self.assertEqual(recusado, 1)
        self.assertIsNone(nada)
        self.assertIn("vault", frase.casefold())
        self.assertFalse(any(vault.rglob("*.zip")))

        resumo = texto_benchmark()
        self.assertIn("indice_frio_s=", resumo)
        self.assertNotIn(NOTA, resumo)
        self.assertNotIn(SEGREDO, resumo)
        self.assertNotIn("\u2014", resumo)

    def test_atalhos_e_arquivos_de_manutencao(self):
        from jarvis.__main__ import main
        from jarvis.atualizar import Resultado

        with mock.patch(
            "jarvis.atualizar.concluir",
            return_value=Resultado(False, "Há alterações locais no código do Jarvis, senhor.", ""),
        ):
            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                codigo = main(["atualizar"])
        self.assertEqual(codigo, 1)
        self.assertIn("alterações locais", buffer.getvalue())
        with mock.patch(
            "jarvis.relatorio.criar",
            return_value=(0, "Gerei o relatório em /tmp/jarvis-relatorio.zip.", None),
        ):
            buffer = io.StringIO()
            with mock.patch("sys.stdout", buffer):
                self.assertEqual(main(["relatorio"]), 0)
        self.assertIn("relatório", buffer.getvalue())

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for numero in range(2, 26):
            self.assertIn("#" + str(numero), changelog)
        self.assertIn("0.25.0", changelog)
        self.assertIn("0.28.0", changelog)
        self.assertIn("0.29.0", changelog)
        self.assertIn("0.30.0", changelog)
        self.assertIn("0.31.0", changelog)
        self.assertIn("0.32.0", changelog)
        self.assertIn("0.33.0", changelog)
        self.assertIn("0.33.1", changelog)
        self.assertIn("0.33.2", changelog)
        self.assertIn("0.34.0", changelog)
        self.assertNotIn(SEGREDO, changelog)
        self.assertNotIn(NOTA, changelog)
        self.assertNotIn("\u2014", changelog)
        self.assertNotIn("\u2013", changelog)

        script = (ROOT / "scripts" / "testar-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("unittest discover", script)
        self.assertIn("python -m jarvis doctor", script)
        self.assertIn("python -m jarvis.benchmark", script)
        self.assertIn("PASSOU", script)
        self.assertIn("FALHOU", script)
        self.assertNotIn("\u2014", script)
        self.assertNotIn("\u2013", script)
        self.assertNotIn("Invoke-Expression", script)
        self.assertNotIn("--force", script)
        self.assertNotIn("git push", script)

        for nome in (
            "jarvis/__version__.py",
            "jarvis/__init__.py",
            "jarvis/atualizar.py",
            "jarvis/relatorio.py",
            "jarvis/__main__.py",
            "tests/test_manutencao.py",
            "CHANGELOG.md",
            "README.md",
        ):
            texto = (ROOT / nome).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", texto, nome)
            self.assertNotIn("\u2013", texto, nome)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("python -m jarvis --versao", readme)
        self.assertIn("python -m jarvis atualizar", readme)
        self.assertIn("python -m jarvis relatorio", readme)
        self.assertIn("testar-windows.ps1", readme)

    def _par_de_repos(self):
        codigo = self.tmp / "codigo-sujo"
        vault = self.tmp / "vault-sujo"
        self._init(codigo)
        self._init(vault)
        self._commit(vault, {"nota.md": "# " + NOTA + "\n\n" + SEGREDO + "\n"})
        os.environ["JARVIS_VAULT"] = str(vault)
        return codigo, vault

    def _clone_com_avanco(self):
        origem = self.tmp / "origem"
        local = self.tmp / "local"
        vault = self.tmp / "vault-clone"
        self._init(origem)
        self._init(vault)
        self._commit(vault, {"nota.md": "# " + NOTA + "\n\ntexto sintetico\n"})
        versao = ' __version__ = "0.25.0"\n'.lstrip()
        self._commit(
            origem,
            {
                "CHANGELOG.md": "# Changelog\n\n## 0.25.0\n\n- Base de teste.\n",
                "requirements.txt": "packaging>=23\n",
                "jarvis/__version__.py": versao,
            },
        )
        self._run("clone", str(origem), str(local))
        self._identidade(local)
        novo = (
            "# Changelog\n\n## 0.25.0\n\n- Base de teste.\n\n"
            "## 0.26.0\n\n- linha nova do changelog\n"
        )
        self._commit(
            origem,
            {
                "CHANGELOG.md": novo,
                "requirements.txt": "packaging>=24\n",
                "jarvis/__version__.py": '__version__ = "0.26.0"\n',
            },
        )
        os.environ["JARVIS_VAULT"] = str(vault)
        return local, vault, origem

    def _init(self, path):
        path.mkdir(parents=True, exist_ok=True)
        self._run("init", "-b", "main", cwd=path)
        self._identidade(path)

    def _identidade(self, path):
        self._run("config", "user.email", "teste@example.com", cwd=path)
        self._run("config", "user.name", "Teste", cwd=path)
        self._run("config", "commit.gpgsign", "false", cwd=path)
        self._run("config", "core.autocrlf", "false", cwd=path)

    def _commit(self, path, arquivos):
        if arquivos:
            for nome, texto in arquivos.items():
                destino = path / nome
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(texto, encoding="utf-8", newline="\n")
        self._run("add", "-A", cwd=path)
        self._run("commit", "-m", "marco de teste", cwd=path)

    def _run(self, *args, cwd=None):
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )

    def _rev(self, path):
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True
        ).strip()

    @staticmethod
    def _pip_proibido(path):
        raise AssertionError(path)

    @staticmethod
    def _fumaca_ok():
        return 0, ""


def tempfile_dir():
    import tempfile

    return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
