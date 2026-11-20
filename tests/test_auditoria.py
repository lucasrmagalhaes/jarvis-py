"""Regressão da auditoria de concorrência, sigilo e encerramento.

Notas e frases deste arquivo são sintéticas. Nada aqui veio de um vault real.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis.brain import Brain, BrainError
from jarvis.cerebro import CerebroError, stream_lines
from jarvis.companion import Companion
from jarvis.encerrar import encerrar
from jarvis.guardas import GuardError, escrever
from jarvis.journal import read_day, record
from jarvis.memory import SessionMemory
from jarvis.panel import parar
from jarvis.pedidos import log_path, record_turn
from jarvis.privacidade import entrar_modo_privado, sair_modo_privado
from jarvis.procutil import encerrar_descendentes, matar, popen_vigiado
from jarvis.remoto import remoto_ligado
from jarvis.routines import mark_task
from jarvis.state import load, update
from jarvis.telegram import TelegramBot
from jarvis.transcribe import transcribe_file
from jarvis.trava import TravaOcupada, fila_escrita, gravar_atomico, trava_arquivo
from jarvis.vault import Vault

_CHAVES = (
    "JARVIS_HOME",
    "JARVIS_STATE",
    "JARVIS_REVISAO",
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_CONTEXTO",
    "JARVIS_CONTEXTO_ARQUIVO",
    "JARVIS_DIGEST",
    "JARVIS_DIGEST_AT",
    "JARVIS_BRIEFING_TELEGRAM",
    "JARVIS_BRIEFING_HORA",
    "JARVIS_OLLAMA_URL",
    "JARVIS_OLLAMA_TIMEOUT",
    "JARVIS_TURN_TIMEOUT",
    "JARVIS_LOG",
)
_FUSO = ZoneInfo("America/Sao_Paulo")


def _mensagem(texto, usuario=7, conversa=7):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "text": texto,
            "from": {"id": usuario},
            "chat": {"id": conversa, "type": "private"},
        },
    }


class _Api:
    def __init__(self):
        self.calls = []

    def call(self, method, payload, timeout=30):
        self.calls.append(method)
        return {}


class _Ocupada:
    def __enter__(self):
        raise TravaOcupada("vault ocupado")

    def __exit__(self, exc_type, exc, tb):
        return False


def _trava_ocupada(*args, **kwargs):
    return _Ocupada()


class AuditoriaTest(unittest.TestCase):
    def setUp(self):
        sair_modo_privado()
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-auditoria-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._env = {chave: os.environ.get(chave) for chave in _CHAVES}
        for chave in _CHAVES:
            os.environ.pop(chave, None)
        os.environ["JARVIS_HOME"] = str(self.home)
        os.environ["JARVIS_VAULT_SYNC"] = "off"
        self.addCleanup(self._limpar)

    def _limpar(self):
        sair_modo_privado()
        for chave, valor in self._env.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_estado_concorrente_nao_perde_incremento(self):
        erros = []

        def soma():
            try:
                for _ in range(20):
                    def aumentar(data):
                        data["n"] = int(data.get("n") or 0) + 1

                    update(aumentar)
            except Exception as error:
                erros.append(error)

        threads = [threading.Thread(target=soma) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(erros, [])
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(load().get("n"), 80)

    def test_contexto_concorrente_permanece_json(self):
        memoria = SessionMemory(limit=12, persist=True)
        erros = []

        def grava(indice):
            try:
                for passo in range(8):
                    memoria.remember(f"pedido {indice} {passo}", f"resposta {indice} {passo}")
            except Exception as error:
                erros.append(error)

        threads = [threading.Thread(target=grava, args=(indice,)) for indice in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(erros, [])
        bruto = (self.home / "contexto.json").read_text(encoding="utf-8")
        dados = json.loads(bruto)
        self.assertIsInstance(dados.get("turnos"), list)
        self.assertGreaterEqual(len(dados["turnos"]), 1)
        self.assertEqual(list(self.home.glob(".contexto.json.*.tmp")), [])

    def test_gravacao_atomica_nao_mostra_json_pela_metade(self):
        alvo = self.tmp / "estado.json"
        parar_leitura = threading.Event()
        erros = []

        def leitor():
            while not parar_leitura.is_set():
                try:
                    bruto = alvo.read_bytes()
                except OSError:
                    continue
                if not bruto:
                    continue
                try:
                    json.loads(bruto.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    erros.append(bruto[:40])

        thread = threading.Thread(target=leitor)
        thread.start()
        try:
            for numero in range(30):
                gravar_atomico(alvo, json.dumps({"n": numero, "texto": "x" * 2000}))
        finally:
            parar_leitura.set()
            thread.join(2)
        self.assertEqual(erros, [])
        self.assertEqual(list(self.tmp.glob(".estado.json.*.tmp")), [])
        self.assertEqual(json.loads(alvo.read_text(encoding="utf-8"))["n"], 29)

    def test_trava_de_processo_vivo_nao_e_roubada(self):
        path = self.tmp / "estado.lock"
        path.write_text(str(os.getpid()), encoding="ascii")
        antigo = time.time() - 3600
        os.utime(path, (antigo, antigo))
        inicio = time.monotonic()
        with self.assertRaises(TravaOcupada):
            with trava_arquivo(path, espera=0.15):
                pass
        self.assertLess(time.monotonic() - inicio, 1.5)
        self.assertEqual(path.read_text(encoding="ascii").strip(), str(os.getpid()))

    def test_trava_de_processo_morto_e_liberada(self):
        path = self.tmp / "morto.lock"
        path.write_text(str(2**30), encoding="ascii")
        with trava_arquivo(path, espera=0.5):
            self.assertEqual(path.read_text(encoding="ascii").strip(), str(os.getpid()))
        self.assertFalse(path.exists())

    def test_fila_nao_deixa_duas_escritas_juntas(self):
        ativo = {"n": 0, "max": 0}
        trava = threading.Lock()

        def trabalho():
            with fila_escrita():
                with trava:
                    ativo["n"] += 1
                    ativo["max"] = max(ativo["max"], ativo["n"])
                time.sleep(0.05)
                with trava:
                    ativo["n"] -= 1

        threads = [threading.Thread(target=trabalho) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(ativo["max"], 1)
        self.assertEqual(ativo["n"], 0)

    def test_nota_espera_o_git(self):
        ordem = []
        liberar = threading.Event()
        entrou = threading.Event()
        root = self.tmp / "vault"
        root.mkdir()

        def git():
            with fila_escrita():
                ordem.append("git")
                entrou.set()
                liberar.wait(2)
                ordem.append("git-fim")

        def nota():
            if not entrou.wait(1):
                return
            escrever(root / "nota.md", "Texto sintetico da auditoria.\n", raiz=root)
            ordem.append("nota")

        primeira = threading.Thread(target=git)
        segunda = threading.Thread(target=nota)
        primeira.start()
        segunda.start()
        try:
            self.assertTrue(entrou.wait(1))
            time.sleep(0.05)
            self.assertEqual(ordem, ["git"])
        finally:
            liberar.set()
            primeira.join(3)
            segunda.join(3)
        self.assertEqual(ordem, ["git", "git-fim", "nota"])
        self.assertEqual((root / "nota.md").read_text(encoding="utf-8"), "Texto sintetico da auditoria.\n")

    def test_git_ocupado_nao_altera_o_vault(self):
        vault = Vault(self.tmp / "vault", sync=True)
        with mock.patch("jarvis.vault.fila_escrita", _Ocupada):
            preparado = vault.prepare()
            publicado = vault.publish("nota sintetica")
        self.assertEqual(preparado.action, "busy")
        self.assertTrue(preparado.read_only)
        self.assertFalse(preparado.committed)
        self.assertEqual(publicado.action, "busy")
        self.assertFalse(publicado.pushed)
        self.assertIn("Não alterei nada", preparado.detail)

    def test_marcar_tarefa_nao_sai_do_vault(self):
        root = self.tmp / "vault"
        root.mkdir()
        fora = self.tmp / "fora.md"
        fora.write_text("- [ ] regar a planta sintetica\n", encoding="utf-8")
        self.assertFalse(mark_task(root, "../fora.md", "regar a planta sintetica"))
        self.assertEqual(fora.read_text(encoding="utf-8"), "- [ ] regar a planta sintetica\n")
        nota = root / "tarefas.md"
        nota.write_text("- [ ] regar a planta sintetica\n", encoding="utf-8")
        self.assertTrue(mark_task(root, "tarefas.md", "regar a planta sintetica"))
        self.assertIn("[x]", nota.read_text(encoding="utf-8"))

    def test_escrita_nao_segue_atalho_para_fora(self):
        root = self.tmp / "vault"
        root.mkdir()
        fora = self.tmp / "fora.md"
        fora.write_text("original\n", encoding="utf-8")
        link = root / "nota.md"
        try:
            link.symlink_to(fora)
        except OSError:
            self.skipTest("sem symlink")
        with self.assertRaises(GuardError):
            escrever(link, "invadido\n", raiz=root)
        self.assertEqual(fora.read_text(encoding="utf-8"), "original\n")

    def test_modo_privado_nao_grava_diario_nem_pedido(self):
        momento = datetime(2026, 11, 11, 12, 0)
        entrar_modo_privado()
        try:
            record("pedido sintetico de auditoria", momento)
            record_turn("study", 0.2, True, momento)
            self.assertEqual(read_day(momento.date()), [])
            self.assertFalse(log_path().exists())
        finally:
            sair_modo_privado()
        record("pedido sintetico de auditoria", momento)
        record_turn("study", 0.2, True, momento)
        self.assertEqual(read_day(momento.date()), ["pedido sintetico de auditoria"])
        self.assertTrue(log_path().is_file())

    def test_journal_e_pedido_nao_estouram_com_trava_ocupada(self):
        momento = datetime(2026, 11, 11, 12, 0)
        with mock.patch("jarvis.trava.trava_arquivo", _trava_ocupada):
            record("pedido sintetico", momento)
            record_turn("study", 0.2, True, momento)
        self.assertEqual(read_day(momento.date()), [])
        self.assertFalse(log_path().exists())

    def test_telegram_no_modo_privado_so_aceita_sair(self):
        vistos = []
        bot = TelegramBot(_Api(), 7, vistos.append, lambda path: "")
        entrar_modo_privado()
        try:
            estranho = bot.handle(_mensagem("sai do modo privado", usuario=99, conversa=99))
            self.assertEqual(estranho["action"], "ignore")
            nota = bot.handle(_mensagem("anota coisa"))
            self.assertEqual(nota["action"], "text")
            self.assertEqual(vistos, [])
            saida = bot.handle(_mensagem("sai do modo privado"))
            self.assertEqual(saida["action"], "text")
            self.assertEqual(vistos, ["sai do modo privado"])
        finally:
            sair_modo_privado()

    def test_telegram_fecha_se_o_remoto_falha(self):
        vistos = []
        bot = TelegramBot(_Api(), 7, vistos.append, lambda path: "")
        with mock.patch("jarvis.remoto.remoto_ligado", side_effect=RuntimeError("estado")):
            decisao = bot.handle(_mensagem("anota coisa"))
        self.assertEqual(decisao["action"], "text")
        self.assertEqual(vistos, [])

    def test_remoto_fecha_se_o_estado_falha(self):
        with mock.patch("jarvis.state.load", side_effect=OSError("disco")):
            self.assertFalse(remoto_ligado())

    def test_envio_privado_nao_chama_o_telegram(self):
        api = _Api()
        bot = TelegramBot(api, 7, lambda text: "", lambda path: "")
        entrar_modo_privado()
        try:
            self.assertIs(bot.send_text("mensagem sintetica"), False)
        finally:
            sair_modo_privado()
        self.assertEqual(api.calls, [])

    def test_resumo_e_briefing_nao_marcam_envio_recusado(self):
        os.environ["JARVIS_DIGEST"] = "on"
        os.environ["JARVIS_BRIEFING_TELEGRAM"] = "on"
        domingo = datetime(2026, 11, 1, 19, 0, tzinfo=_FUSO)
        manha = datetime(2026, 11, 11, 8, 0, tzinfo=_FUSO)

        class Recusa:
            def send_text(self, text):
                return False

        brain = type("B", (), {"vault": None, "pending": None})()
        companion = Companion(brain, lock=threading.RLock())
        companion.bot = Recusa()
        with mock.patch("jarvis.companion.digest_text", return_value="Resumo sintetico da semana."):
            self.assertIsNone(companion._maybe_digest(self.home, domingo))
        with mock.patch("jarvis.routines.briefing_speech", return_value="Bom dia sintetico."):
            self.assertIsNone(companion._maybe_briefing(self.home, manha))
        estado = load()
        self.assertNotIn("digest", estado)
        self.assertNotIn("briefing_telegram", estado)

    def test_encerrar_mata_processo_vigiado(self):
        processo = popen_vigiado(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            encerrar(None)
            processo.wait(timeout=3)
        finally:
            if processo.poll() is None:
                matar(processo)
        self.assertIsNotNone(processo.poll())

    def test_descendentes_so_mata_ffmpeg_e_claude(self):
        mortos = []

        def listar(pid):
            return [(11, "ffmpeg"), (12, "python"), (13, "claude.exe"), (pid, "ffmpeg")]

        encerrar_descendentes(listar=listar, matar_pid=mortos.append, pid=99)
        self.assertEqual(mortos, [11, 13])

    def test_fluxo_do_claude_tem_prazo(self):
        class Falso:
            def _cwd(self):
                return str(self_tmp)

        self_tmp = self.tmp
        linhas = None
        try:
            linhas = Brain._popen_events(
                Falso(),
                [sys.executable, "-c", "import time; time.sleep(20)"],
                "oi",
                timeout=0.3,
            )
            with self.assertRaises(BrainError) as ctx:
                list(linhas)
        finally:
            if linhas is not None:
                linhas.close()
        self.assertIn("demorou", str(ctx.exception))

    def test_fluxo_do_ollama_tem_prazo_total(self):
        class Lento:
            def __iter__(self):
                return self

            def __next__(self):
                time.sleep(0.4)
                return b'{"message":{"content":"oi"}}\n'

            def close(self):
                return None

        def urlopen(request, timeout=None):
            return Lento()

        with mock.patch("jarvis.cerebro.urllib.request.urlopen", urlopen):
            with mock.patch("jarvis.cerebro.ollama_base", return_value="http://127.0.0.1:9"):
                with mock.patch("jarvis.cerebro.config.ollama_timeout", return_value=0.2):
                    with self.assertRaises(CerebroError) as ctx:
                        list(stream_lines("sistema", "usuario sintetico"))
        self.assertIn("demorou", str(ctx.exception))

    def test_transcricao_tem_prazo(self):
        class Modelo:
            def transcribe(self, *args, **kwargs):
                time.sleep(1.2)
                return [], None

        chamados = []
        with mock.patch("jarvis.transcribe._load", return_value=Modelo()):
            with mock.patch(
                "jarvis.procutil.encerrar_descendentes",
                side_effect=lambda *args, **kwargs: chamados.append(1),
            ):
                with self.assertRaises(TimeoutError) as ctx:
                    transcribe_file(self.tmp / "audio.wav", timeout=0.15)
        self.assertIn("demorou", str(ctx.exception))
        self.assertEqual(chamados, [1])

    def test_parar_painel_fecha_o_servidor(self):
        import jarvis.panel as panel

        class Servidor:
            def __init__(self):
                self.parou = False
                self.fechou = False

            def shutdown(self):
                self.parou = True

            def server_close(self):
                self.fechou = True

        servidor = Servidor()
        anterior = panel._SERVIDOR
        panel._SERVIDOR = servidor
        try:
            parar()
            self.assertTrue(servidor.parou)
            self.assertTrue(servidor.fechou)
            self.assertIsNone(panel._SERVIDOR)
        finally:
            panel._SERVIDOR = anterior


if __name__ == "__main__":
    unittest.main()
