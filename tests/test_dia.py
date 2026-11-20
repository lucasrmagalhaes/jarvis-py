"""Um dia sintético: bom dia, vídeo, pergunta, teste, fim do dia e sync.

Brain, voz, ouvido e rede são falsos. O vault é temporário e não tem nota real.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

URL = "https://www.youtube.com/watch?v=Abcdefghijk"
TRANSCRICAO = (
    "O farol de teste aponta para leste no mapa de exemplo. MAPA-BRUTO."
)
RESUMO = (
    "Resumo:\n"
    "O farol de teste aponta para leste.\n\n"
    "Pontos:\n"
    "- aponta para leste\n\n"
    "Cartões:\n"
    "- Qual o nome do farol de teste? ::: leste\n"
)
AGORA = datetime(2026, 11, 11, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_VAULT_REMOTE",
    "JARVIS_VAULT_SYNC",
    "JARVIS_VAULT_BRANCH",
    "JARVIS_WORKSPACE",
    "JARVIS_PROMPT_FILE",
    "JARVIS_LOG",
    "JARVIS_STATE",
    "JARVIS_REVISAO",
    "JARVIS_CEREBRO",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "READWISE_TOKEN",
    "TELEGRAM_BOT_TOKEN",
)


class VozFalsa:
    def __init__(self):
        self.frases = []

    def falar(self, texto):
        self.frases.append(texto)


class OuvidoFalso:
    def __init__(self, frases):
        self.frases = list(frases)

    def ouvir(self):
        if not self.frases:
            return ""
        return self.frases.pop(0)


def run_git(path, *args):
    command = ["git"]
    if path is not None:
        command += ["-C", str(path)]
    command += list(args)
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError((process.stderr or process.stdout or "git falhou").strip())
    return process.stdout


def config_repo(path):
    run_git(path, "config", "user.email", "jarvis-test@example.com")
    run_git(path, "config", "user.name", "Jarvis Test")
    run_git(path, "config", "commit.gpgsign", "false")


def make_pair(tmp):
    bare = tmp / "remote.git"
    run_git(None, "init", "--bare", "-b", "main", str(bare))
    local = tmp / "local"
    run_git(None, "init", "-b", "main", str(local))
    config_repo(local)
    (local / "AGENTS.md").write_text("Use as pastas existentes.\n", encoding="utf-8")
    (local / "CLAUDE.md").write_text("# Vault de teste\n", encoding="utf-8")
    livros = local / "Tecnologia" / "Livros"
    livros.mkdir(parents=True)
    (livros / "fita-de-teste.md").write_text(
        "# Fita de teste\n\nQual a cor da fita de teste? ::: azul\n",
        encoding="utf-8",
    )
    hidden = local / ".obsidian"
    hidden.mkdir()
    marker = hidden / "app.json"
    marker.write_text('{"marker":"nao-mexer"}\n', encoding="utf-8")
    run_git(local, "add", "AGENTS.md", "CLAUDE.md", "Tecnologia")
    run_git(local, "commit", "-m", "base")
    run_git(local, "remote", "add", "origin", str(bare))
    run_git(local, "push", "-u", "origin", "HEAD:main")
    return bare, local, marker


class DiaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        self.bare, self.local, self.marker = make_pair(self.tmp)
        self.antes = self.marker.read_bytes()
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        os.environ["JARVIS_REVISAO"] = str(self.tmp / "home" / "revisao.json")
        os.environ["JARVIS_LOG"] = str(self.tmp / "home" / "jarvis.log")
        os.environ["JARVIS_VAULT"] = str(self.local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(self.bare)
        os.environ["JARVIS_CEREBRO"] = "claude"

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_um_dia_com_captura_pergunta_teste_e_sync(self):
        from jarvis.brain import Brain
        from jarvis.review import scan_cards, scan_drafts

        def rede(*_args, **_kwargs):
            raise AssertionError("rede")

        material = {
            "title": "Farol de teste",
            "channel": "Canal de teste",
            "url": URL,
            "texto": TRANSCRICAO,
            "origem": "transcricao",
        }
        prompts = []

        def resumir(pedido):
            prompts.append(pedido)
            return RESUMO

        def responder(message, composed, read_only, local_composed=None):
            self.assertNotIn("MAPA-BRUTO", message)
            return "O farol de teste é um exemplo local, senhor."

        with mock.patch("urllib.request.urlopen", rede), mock.patch(
            "jarvis.midia.abrir_url", rede
        ), mock.patch("jarvis.external.github_auth_state", return_value="missing"), mock.patch(
            "jarvis.external.jira_issues", return_value=None
        ), mock.patch("jarvis.midia.buscar_video", return_value=material):
            brain = Brain()
            brain.clock = lambda: AGORA
            brain.resumir_midia = resumir
            brain._answer_consult = responder
            ouvido = OuvidoFalso(
                [
                    "bom dia",
                    "salva esse vídeo " + URL,
                    "explica o farol de teste",
                    "me testa sobre a fita",
                    "azul",
                    "como foi meu dia",
                    "sim",
                ]
            )
            voz = VozFalsa()
            while True:
                frase = ouvido.ouvir()
                if not frase:
                    break
                voz.falar(brain.ask(frase))

        self.assertEqual(ouvido.frases, [])
        self.assertEqual(len(voz.frases), 7)
        self.assertIn("Bom dia", voz.frases[0])
        self.assertIn("Guardei o vídeo", voz.frases[1])
        self.assertIn("rascunho", voz.frases[1])
        self.assertIn("exemplo local", voz.frases[2])
        self.assertIn("fita de teste", voz.frases[3])
        self.assertNotIn("farol", voz.frases[3].casefold())
        self.assertIn("Certo", voz.frases[4])
        self.assertIn("fechando o dia", voz.frases[5])
        self.assertIn("Gravei o resumo do dia", voz.frases[6])
        for frase in voz.frases:
            self.assertNotIn("MAPA-BRUTO", frase)
            self.assertNotIn("\u2014", frase)
            self.assertNotIn("\u2013", frase)
        self.assertTrue(prompts)
        self.assertIn("MAPA-BRUTO", prompts[0].split("Pedido do senhor:")[0])
        self.assertNotIn("MAPA-BRUTO", prompts[0].split("Pedido do senhor:")[1])
        nota = next((self.local / "Tecnologia" / "Vídeos").glob("*.md"))
        corpo = nota.read_text(encoding="utf-8")
        self.assertIn("[rascunho] Qual o nome do farol de teste? ::: leste", corpo)
        self.assertNotIn("MAPA-BRUTO", corpo)
        self.assertEqual(len(scan_drafts(self.local)), 1)
        self.assertTrue(all(card["answer"] != "leste" for card in scan_cards(self.local)))
        self.assertEqual(self.marker.read_bytes(), self.antes)
        log = run_git(self.local, "log", "--format=%s")
        self.assertIn("Jarvis:", log)
        self.assertNotIn("--force", log)
        remoto = run_git(
            self.bare, "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "HEAD"
        )
        self.assertIn(nota.relative_to(self.local).as_posix(), remoto)
        self.assertNotIn(".obsidian", remoto)
        self.assertNotIn(".obsidian", run_git(self.local, "ls-files"))
