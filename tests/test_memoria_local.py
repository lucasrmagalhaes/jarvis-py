"""Memória local, espera, destino ambíguo, validação, log, prefixo e semana."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis.brain import ESPERA, Brain, BrainError, stable_prefix
from jarvis.chat import HELP
from jarvis.guardas import avaliar_ferramenta, registrar_recusa, validar_saida
from jarvis.persona import PERSONA
from jarvis.brain import UNTRUSTED, VAULT_RULES
from jarvis.routines import apply_capture_choice, classify, help_speech, run_routine

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 28, 11, 0, tzinfo=TZ)
ENV_KEYS = (
    "JARVIS_VAULT",
    "JARVIS_VAULT_REMOTE",
    "JARVIS_VAULT_SYNC",
    "JARVIS_VAULT_BRANCH",
    "JARVIS_PROMPT_FILE",
    "JARVIS_WORKSPACE",
    "JARVIS_HOME",
    "JARVIS_STATE",
    "JARVIS_REVISAO",
    "JARVIS_LOG",
)


def _git(path, *args, env=None):
    full = os.environ.copy()
    full["GIT_AUTHOR_NAME"] = "Jarvis Test"
    full["GIT_AUTHOR_EMAIL"] = "jarvis-test@example.com"
    full["GIT_COMMITTER_NAME"] = "Jarvis Test"
    full["GIT_COMMITTER_EMAIL"] = "jarvis-test@example.com"
    if env:
        full.update(env)
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        env=full,
    )


class RodadaTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _brain(self):
        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        return brain

    def test_lista_fatos_e_so_esquece_depois_da_confirmacao(self):
        from jarvis.memoria import about_speech, add_fact, memory_path

        self.assertFalse(add_fact("senha: abcdefghijklmnop", "2026-10-28"))
        add_fact("gosta de cha gelado", "2026-10-28")
        add_fact("gosta de cafe curto", "2026-10-27")
        root = self.tmp / "vault"
        (root / "Jarvis").mkdir(parents=True)
        (root / "Jarvis" / "Perfil.md").write_text(
            "# Perfil\n\n"
            "- 2026-10-01: prefere a janela\n"
            "- 2026-10-02: senha: abcdefghijklmnop\n",
            encoding="utf-8",
        )
        state = {
            "alerts": {
                "paused_until": "2026-11-01",
                "zone": "America/Sao_Paulo",
                "last": ["mail:segredo-de-teste"],
                "always": [],
                "today": {},
            }
        }
        home = Path(os.environ["JARVIS_HOME"])
        home.mkdir(parents=True, exist_ok=True)
        (home / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (home / "revisao.json").write_text(
            json.dumps(
                {
                    "cards": {
                        "0123456789abcdef": {
                            "interval": 3,
                            "reps": 1,
                            "ease": 2.5,
                            "question": "pergunta secreta de teste",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        speech = about_speech(root)
        self.assertIn("gosta de cha gelado", speech)
        self.assertIn("prefere a janela", speech)
        self.assertIn("2026-11-01", speech)
        self.assertIn("cartão", speech)
        self.assertNotIn("abcdefghijklmnop", speech)
        self.assertNotIn("segredo-de-teste", speech)
        self.assertNotIn("pergunta secreta de teste", speech)
        stored = memory_path().read_text(encoding="utf-8")
        self.assertNotIn("abcdefghijklmnop", stored)
        self.assertIn("prefere a janela", stored)

        brain = self._brain()
        listed = brain.ask("o que você sabe sobre mim?")
        self.assertIn("gosta de cha gelado", listed)
        self.assertNotIn("abcdefghijklmnop", listed)
        asked = brain.ask("esquece cha")
        self.assertIn("Esqueço", asked)
        self.assertIn("gosta de cha gelado", about_speech(None))
        kept = brain.ask("não")
        self.assertIn("Continua guardado", kept)
        self.assertIn("gosta de cha gelado", about_speech(None))
        brain.ask("esquece gosta")
        self.assertEqual(len(brain.pending["options"]), 2)
        removed = brain.ask("2")
        self.assertIn("Esqueci", removed)
        after = about_speech(None)
        self.assertNotIn("gosta de cafe curto", after)
        self.assertIn("gosta de cha gelado", after)
        self.assertIn("Não encontrei", brain.ask("esquece violino"))
        self.assertIn("O que devo esquecer", brain.ask("esquece"))

        from jarvis.memoria import apply_forget, prepare_forget

        _reply, pending = prepare_forget("janela")
        self.assertIn("prefere a janela", (root / "Jarvis" / "Perfil.md").read_text(encoding="utf-8"))
        done = apply_forget(root, pending, "yes", profile=True)
        self.assertIn("Esqueci", done)
        profile = (root / "Jarvis" / "Perfil.md").read_text(encoding="utf-8")
        self.assertNotIn("prefere a janela", profile)
        self.assertNotIn("prefere a janela", about_speech(None))

    def test_ajuda_e_classificacao_dos_pedidos_novos(self):
        self.assertEqual(classify("o que você sabe sobre mim?").kind, "about")
        self.assertEqual(classify("o que você sabe").kind, "help")
        forgotten = classify("Esquece que eu gosto de café")
        self.assertEqual(forgotten.kind, "forget")
        self.assertIn("café", forgotten.text)
        self.assertEqual(classify("o que aprendi esta semana?").kind, "learned")
        self.assertEqual(classify("como foi minha semana?").kind, "week")
        capture = classify("Anota na pasta IA que a revisao ficou para sexta")
        self.assertEqual(capture.kind, "capture")
        self.assertEqual(capture.text, "a revisao ficou para sexta")
        self.assertEqual(capture.place, "pasta")
        self.assertEqual(capture.query, "IA")
        speech = help_speech(True)
        self.assertIn("o que você sabe sobre mim", speech)
        self.assertIn("esquece", speech)
        self.assertIn("o que aprendi esta semana", speech)
        self.assertNotIn("\u2014", speech)
        self.assertIn("o que você sabe sobre mim", HELP)
        self.assertNotIn("\u2014", HELP)
        brain = self._brain()
        reply = brain.ask("ajuda")
        self.assertIn("o que aprendi esta semana", reply)

    def test_destino_ambiguo_pergunta_e_nao_grava(self):
        root = self.tmp / "notas"
        cursos = root / "Cursos"
        cursos.mkdir(parents=True)
        (cursos / "alfa.md").write_text("# Alfa\n\ntexto antigo\n", encoding="utf-8")
        (cursos / "beta.md").write_text("# Beta\n\ntexto antigo\n", encoding="utf-8")
        (root / ".obsidian").mkdir()
        (root / ".obsidian" / "alfa.md").write_text("# Alfa\n\nsegredo obsidian\n", encoding="utf-8")
        session = {}
        reply = run_routine(
            root,
            classify("anota na pasta Cursos que li o capitulo um"),
            NOW,
            session=session,
        )
        self.assertIn("número", reply.casefold())
        self.assertIn("alfa.md", reply)
        self.assertIn("beta.md", reply)
        self.assertNotIn("li o capitulo um", (cursos / "alfa.md").read_text(encoding="utf-8"))
        self.assertNotIn("li o capitulo um", (cursos / "beta.md").read_text(encoding="utf-8"))
        self.assertNotIn(".obsidian", reply)
        self.assertEqual(session["pending"]["kind"], "capture")
        chosen = apply_capture_choice(root, session["pending"], 0, NOW)
        self.assertIn("Anotei", chosen)
        alfa = (cursos / "alfa.md").read_text(encoding="utf-8")
        beta = (cursos / "beta.md").read_text(encoding="utf-8")
        written = alfa + beta
        self.assertEqual(written.count("li o capitulo um"), 1)
        self.assertNotIn("li o capitulo um", (root / ".obsidian" / "alfa.md").read_text(encoding="utf-8"))

        solo = self.tmp / "solo"
        (solo / "Receitas").mkdir(parents=True)
        cha = solo / "Receitas" / "cha.md"
        cha.write_text("# Cha\n\n", encoding="utf-8")
        direct = run_routine(solo, classify("anota na nota Cha que ferver a agua"), NOW)
        self.assertIn("Anotei", direct)
        self.assertIn("ferver a agua", cha.read_text(encoding="utf-8"))

        partial = self.tmp / "parcial"
        (partial / "Receitas").mkdir(parents=True)
        verde = partial / "Receitas" / "cha-verde.md"
        verde.write_text("# Cha verde\n\n", encoding="utf-8")
        session = {}
        asked = run_routine(
            partial,
            classify("anota na nota Cha que ferver a agua"),
            NOW,
            session=session,
        )
        self.assertIn("Anoto em", asked)
        self.assertNotIn("ferver a agua", verde.read_text(encoding="utf-8"))
        confirmed = apply_capture_choice(partial, session["pending"], "yes", NOW)
        self.assertIn("Anotei", confirmed)
        self.assertIn("ferver a agua", verde.read_text(encoding="utf-8"))

        vazio = self.tmp / "vazio"
        (vazio / "Vazio").mkdir(parents=True)
        session = {}
        created = run_routine(
            vazio,
            classify("anota na pasta Vazio que comprar pao"),
            NOW,
            session=session,
        )
        self.assertIn("Crio", created)
        self.assertFalse((vazio / "Vazio" / "nota.md").exists())
        apply_capture_choice(vazio, session["pending"], "yes", NOW)
        note = (vazio / "Vazio" / "nota.md").read_text(encoding="utf-8")
        self.assertIn("comprar pao", note)
        self.assertNotIn("senhor", note)

        missing = self.tmp / "sumiu"
        missing.mkdir()
        session = {}
        daily = run_routine(
            missing,
            classify("anota na nota Inexistente que comprar pao"),
            NOW,
            session=session,
        )
        self.assertIn("nota de hoje", daily)
        self.assertEqual(list(missing.glob("*.md")), [])
        apply_capture_choice(missing, session["pending"], "no", NOW)
        self.assertEqual(list(missing.glob("*.md")), [])

        hidden = self.tmp / "so-oculto"
        (hidden / ".obsidian").mkdir(parents=True)
        (hidden / ".obsidian" / "Cha.md").write_text("# Cha\n\n", encoding="utf-8")
        session = {}
        refused = run_routine(
            hidden,
            classify("anota na nota Cha que ferver a agua"),
            NOW,
            session=session,
        )
        self.assertIn("nota de hoje", refused)
        self.assertNotIn("ferver a agua", (hidden / ".obsidian" / "Cha.md").read_text(encoding="utf-8"))

    def test_confirma_o_destino_pelo_cerebro_sem_chutar(self):
        root = self.tmp / "confirma"
        root.mkdir()
        brain = self._brain()
        brain.clock = lambda: NOW

        class Prep:
            read_only = False

        class Vault:
            def __init__(self, path):
                self.path = path

            def resync_snapshot(self):
                self.ready = True

        brain.vault = Vault(root)
        brain._tracked = lambda _message, work: work(Prep())
        brain.pending = {
            "kind": "capture",
            "body": "ligar amanha",
            "options": [{"relative": "", "label": "nota de hoje", "mode": "daily"}],
        }
        reply = brain.ask("sim")
        self.assertIn("Anotei na nota de hoje", reply)
        self.assertIn("ligar amanha", (root / "2026-10-28.md").read_text(encoding="utf-8"))

    def test_espera_uma_vez_e_nao_bloqueia_a_resposta(self):
        brain = Brain()
        brain._command = lambda _session, read_only=False: ["claude", "-p"]
        brain.wait_seconds = 0.05
        gate = threading.Event()
        seen = []

        def on_wait(text):
            seen.append((text, threading.get_ident()))
            gate.wait(2)

        brain.on_wait = on_wait

        class Proc:
            returncode = 0
            stdout = json.dumps({"result": "Pronto, senhor.", "session_id": "s"})
            stderr = ""

        def slow_run(*_args, **_kwargs):
            time.sleep(0.35)
            return Proc()

        started = time.monotonic()
        try:
            with mock.patch("jarvis.brain.subprocess.run", slow_run):
                with mock.patch("builtins.print") as printed:
                    reply = brain._ask("pedido", None, False)
            elapsed = time.monotonic() - started
            self.assertEqual(reply, "Pronto, senhor.")
            self.assertLess(elapsed, 1.2)
            self.assertEqual([item[0] for item in seen], [ESPERA])
            self.assertNotEqual(seen[0][1], threading.get_ident())
            printed.assert_any_call(ESPERA, flush=True)
        finally:
            gate.set()

        brain.wait_seconds = 5
        seen.clear()

        def fast_run(*_args, **_kwargs):
            return Proc()

        with mock.patch("jarvis.brain.subprocess.run", fast_run):
            with mock.patch("builtins.print") as printed:
                reply = brain._ask("pedido", None, False)
        time.sleep(0.15)
        self.assertEqual(reply, "Pronto, senhor.")
        self.assertEqual(seen, [])
        for call in printed.call_args_list:
            self.assertNotIn(ESPERA, call.args)

    def test_prefixo_estavel_sem_horario(self):
        first = stable_prefix(PERSONA, "Convenções fixas.", VAULT_RULES, UNTRUSTED)
        second = stable_prefix(PERSONA, "Convenções fixas.", VAULT_RULES, UNTRUSTED)
        expected = (
            PERSONA.strip()
            + "\n\n"
            + "Convenções fixas."
            + "\n\n"
            + VAULT_RULES.strip()
            + "\n\n"
            + UNTRUSTED.strip()
            + "\n"
        )
        self.assertEqual(first, second)
        self.assertEqual(first, expected)
        self.assertLess(first.index("Tony Stark"), first.index("Convenções fixas."))
        self.assertLess(first.index("Convenções fixas."), first.index("linguagem direta"))
        self.assertLess(first.index("linguagem direta"), first.index("dado-nao-confiavel"))
        self.assertNotRegex(first, r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")
        with mock.patch("jarvis.brain.datetime") as clock:
            clock.now.side_effect = AssertionError("relogio")
            again = stable_prefix(PERSONA, "Convenções fixas.", VAULT_RULES, UNTRUSTED)
        self.assertEqual(again, first)

        class Fake:
            def __init__(self, path):
                self.path = path

            def agents_for_prompt(self):
                return "Convenções fixas."

        brain = self._brain()
        brain.vault = Fake(self.tmp / "vault")
        brain._write_prompt()
        written = Path(os.environ["JARVIS_PROMPT_FILE"]).read_text(encoding="utf-8")
        brain._write_prompt()
        repeated = Path(os.environ["JARVIS_PROMPT_FILE"]).read_text(encoding="utf-8")
        self.assertEqual(written, repeated)
        self.assertEqual(written, first)

    def test_log_do_pedido_nao_leva_texto_e_gira(self):
        import jarvis.pedidos as pedidos
        from jarvis.pedidos import record_turn

        brain = self._brain()
        brain.ask("ajuda")
        path = pedidos.log_path()
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(set(lines[-1]), {"em", "intencao", "duracao", "sucesso"})
        self.assertEqual(lines[-1]["intencao"], "help")
        self.assertTrue(lines[-1]["sucesso"])
        self.assertGreaterEqual(lines[-1]["duracao"], 0)
        self.assertNotIn("ajuda", path.read_text(encoding="utf-8"))

        def boom(*_args, **_kwargs):
            raise BrainError("falhou")

        brain._ask = boom
        with self.assertLogs("jarvis", level="ERROR"):
            with self.assertRaises(BrainError):
                brain.ask("token-azul-991 o que significa")
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("token-azul-991", raw)
        self.assertNotIn("significa", raw)
        last = json.loads(raw.splitlines()[-1])
        self.assertEqual(last["intencao"], "chat")
        self.assertFalse(last["sucesso"])

        original = pedidos.LIMITE_BYTES
        try:
            pedidos.LIMITE_BYTES = 180
            moment = datetime(2026, 10, 28, 12, 0, tzinfo=TZ)
            for _index in range(6):
                record_turn("help", 0.01, True, moment)
            record_turn("focus", 0.02, True, moment)
        finally:
            pedidos.LIMITE_BYTES = original
        backup = Path(str(path) + ".1")
        self.assertTrue(backup.is_file())
        self.assertTrue(path.is_file())
        blob = path.read_text(encoding="utf-8") + backup.read_text(encoding="utf-8")
        self.assertNotIn("token-azul-991", blob)
        self.assertIn('"intencao":"focus"', path.read_text(encoding="utf-8"))
        for line in path.read_text(encoding="utf-8").splitlines():
            self.assertEqual(set(json.loads(line)), {"em", "intencao", "duracao", "sucesso"})

    def test_recusa_saida_do_modelo_e_registra_so_o_motivo(self):
        vault = self.tmp / "vault"
        vault.mkdir()
        os.environ["JARVIS_VAULT"] = str(vault)
        secret = "senha: abcdefghijklmnop"
        with self.assertLogs("jarvis", level="INFO") as captured:
            fora = avaliar_ferramenta(
                {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(self.tmp / "fora" / "nota.md"),
                        "content": "Nota sintetica.\n",
                    },
                }
            )
            vazio = avaliar_ferramenta(
                {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(vault / "nota.md"),
                        "content": "   ",
                    },
                }
            )
            segredo = avaliar_ferramenta(
                {
                    "tool_name": "Edit",
                    "tool_input": {
                        "file_path": str(vault / "nota.md"),
                        "old_string": "cafe",
                        "new_string": secret,
                    },
                }
            )
            oculto = avaliar_ferramenta(
                {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": str(vault / ".obsidian" / "app.json"),
                        "content": "{}\n",
                    },
                }
            )
            livre = validar_saida(vault / "Diario" / "nota.md", "Comprar cafe.\n", raiz=vault)
        joined = "\n".join(captured.output)
        self.assertIn("fora", fora)
        self.assertIn("vazio", vazio)
        self.assertIn("segredo", segredo)
        self.assertIn("bloqueada", oculto)
        self.assertIsNone(livre)
        self.assertIn("escrita recusada: fora", joined)
        self.assertIn("escrita recusada: vazio", joined)
        self.assertIn("escrita recusada: segredo", joined)
        self.assertIn("escrita recusada: obsidian", joined)
        self.assertNotIn(secret, joined)
        self.assertNotIn("Nota sintetica", joined)
        self.assertNotIn(secret, segredo)
        with self.assertLogs("jarvis", level="INFO") as captured:
            registrar_recusa(secret)
        self.assertIn("escrita recusada: bloqueada", "\n".join(captured.output))
        self.assertNotIn(secret, "\n".join(captured.output))

    def test_publicacao_descarta_arquivo_recusado_sem_gravar_o_texto(self):
        from jarvis.vault import Vault
        from tests.test_vault import make_pair

        repos = self.tmp / "repos"
        repos.mkdir()
        bare, _work, local = make_pair(repos)
        vault = Vault(local, remote=str(bare), sync=True, timeout=30)
        vault.prepare()
        secret = "senha: abcdefghijklmnop"
        (local / "Agenda Profissional" / "Hoje.md").write_text(secret + "\n", encoding="utf-8")
        (local / "Farol.md").write_text("# Farol\n\nNota sintetica.\n", encoding="utf-8")
        (local / "vazio.md").write_text("   \n", encoding="utf-8")
        hidden = local / ".obsidian"
        hidden.mkdir()
        (hidden / "app.json").write_text("{}\n", encoding="utf-8")
        outside = self.tmp / "fora.md"
        outside.write_text("conteudo de fora que nao entra\n", encoding="utf-8")
        (local / "atalho.md").symlink_to(outside)
        with self.assertLogs("jarvis", level="INFO") as captured:
            vault.publish("pedido sem segredo")
        joined = "\n".join(captured.output)
        self.assertIn("escrita recusada: segredo", joined)
        self.assertIn("escrita recusada: vazio", joined)
        self.assertIn("escrita recusada: obsidian", joined)
        self.assertIn("escrita recusada: fora", joined)
        self.assertNotIn(secret, joined)
        self.assertNotIn("conteudo de fora", joined)
        self.assertNotIn("Nota sintetica", joined)
        self.assertTrue((hidden / "app.json").is_file())
        self.assertFalse((local / "vazio.md").exists())
        self.assertFalse((local / "atalho.md").exists())
        self.assertTrue(outside.is_file())
        hoje = (local / "Agenda Profissional" / "Hoje.md").read_text(encoding="utf-8")
        self.assertNotIn(secret, hoje)
        self.assertIn("v1", hoje)
        history = subprocess.run(
            ["git", "-C", str(local), "log", "-p", "--all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("Nota sintetica", history)
        self.assertNotIn(secret, history)
        self.assertNotIn("conteudo de fora", history)

    def test_o_que_aprendi_usa_titulo_e_subtitulo(self):
        from jarvis.aprendizado import learned_speech

        root = self.tmp / "estudo"
        root.mkdir()
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.email", "jarvis-test@example.com")
        _git(root, "config", "user.name", "Jarvis Test")
        antigo = root / "antigo.md"
        antigo.write_text(
            "# Antigo de teste\n\n## Velho\n\ncorpo-oculto-8841\n",
            encoding="utf-8",
        )
        old = {
            "GIT_AUTHOR_DATE": "2020-01-01T12:00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T12:00:00",
        }
        _git(root, "add", "antigo.md", env=old)
        _git(root, "commit", "-m", "antigo", env=old)
        os.utime(antigo, (1_577_836_800, 1_577_836_800))
        farol = root / "farol.md"
        farol.write_text(
            "# Farol de teste\n\n## Preparo\n\ncorpo-oculto-8841\n",
            encoding="utf-8",
        )
        hidden = root / ".obsidian"
        hidden.mkdir()
        (hidden / "nota.md").write_text(
            "# Oculto obsidian\n\ncorpo-oculto-8841\n",
            encoding="utf-8",
        )
        _git(root, "add", "farol.md", ".obsidian/nota.md")
        _git(root, "commit", "-m", "farol")
        os.utime(farol, (1_577_836_800, 1_577_836_800))
        horta = root / "horta.md"
        horta.write_text("# Horta de teste\n\ncorpo-oculto-8841\n", encoding="utf-8")
        moment = datetime.now(TZ)
        speech = learned_speech(root, moment)
        self.assertIn("Farol de teste", speech)
        self.assertIn("Preparo", speech)
        self.assertIn("Horta de teste", speech)
        self.assertNotIn("Antigo de teste", speech)
        self.assertNotIn("Oculto", speech)
        self.assertNotIn("corpo-oculto-8841", speech)
        self.assertNotIn(".obsidian", speech)
        self.assertNotIn("\u2014", speech)

        quiet = self.tmp / "sem-nota"
        quiet.mkdir()
        self.assertIn("Não há nota", learned_speech(quiet, moment))

        many = self.tmp / "muitas"
        many.mkdir()
        for name in ("aa", "bb", "cc", "dd", "ee", "ff"):
            (many / f"{name}.md").write_text(
                f"# Nota {name}\n\ncorpo-oculto-8841\n",
                encoding="utf-8",
            )
        summary = learned_speech(many, moment)
        self.assertIn("Nota aa", summary)
        self.assertIn("E mais 1", summary)
        self.assertNotIn("Nota ff", summary)
        self.assertNotIn("corpo-oculto-8841", summary)
        routed = run_routine(many, classify("o que aprendi esta semana?"), moment)
        self.assertIn("Nota aa", routed)
        self.assertNotIn("corpo-oculto-8841", routed)

    def test_fontes_novas_nao_tem_traco_longo(self):
        root = Path(__file__).resolve().parents[1]
        for name in (
            "jarvis/memoria.py",
            "jarvis/pedidos.py",
            "jarvis/aprendizado.py",
            "jarvis/brain.py",
            "jarvis/routines.py",
            "jarvis/guardas.py",
            "jarvis/vault.py",
            "jarvis/chat.py",
            "jarvis/main.py",
            "tests/test_memoria_local.py",
        ):
            text = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)


if __name__ == "__main__":
    unittest.main()
