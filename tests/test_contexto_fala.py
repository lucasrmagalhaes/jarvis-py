"""Contexto, interrupção da fala, transcrição, índice e fluxo.

As notas daqui são sintéticas. Nada veio de um vault real.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis import doctor
from jarvis.chat import HELP
from jarvis.frases import split_ready
from jarvis.fluxo import consume_events, consume_ollama, stream_command
from jarvis.indice_vetor import NoteIndex, medir_arranque, vectors_for
from jarvis.memory import SessionMemory
from jarvis.routines import classify, help_speech, run_routine
from jarvis.stt import choose_stt, doctor_status, open_transcriber

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 11, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_WORKSPACE",
    "JARVIS_CEREBRO",
    "JARVIS_STT",
    "JARVIS_WHISPER_MODEL",
    "JARVIS_CONTEXTO",
    "JARVIS_CONTEXTO_ARQUIVO",
    "JARVIS_STREAM",
    "JARVIS_PROMPT_FILE",
)


class Rodada18Test(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV}
        for key in ENV:
            os.environ.pop(key, None)
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")
        os.environ["JARVIS_WORKSPACE"] = str(self.tmp / "ws")
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        doctor.results.clear()

    def tearDown(self):
        from jarvis import main as jarvis_main

        jarvis_main.audio.ears = None
        jarvis_main.audio.wake = None
        doctor.results.clear()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_contexto_segue_a_resposta_e_nova_conversa_apaga(self):
        from jarvis.brain import Brain

        memory = SessionMemory(limit=2, persist=False)
        memory.remember("primeira", "um")
        memory.remember("segunda", "dois")
        memory.remember("terceira", "tres")
        self.assertNotIn("primeira", memory.as_prompt())
        self.assertIn("terceira", memory.as_prompt())

        brain = Brain()
        brain.memory.remember("explica o exemplo", "O prazo ficticio ficou para sexta.")
        text = brain._compose("e sobre isso?", None)
        self.assertIn("O prazo ficticio ficou para sexta.", text)
        self.assertIn("última resposta", text)
        self.assertIn("Pedido do senhor: e sobre isso?", text)
        self.assertEqual(classify("e sobre isso?").kind, "chat")
        self.assertEqual(classify("nova conversa").kind, "new_chat")
        self.assertEqual(classify("salva isso").kind, "save_last")
        self.assertEqual(classify("anota que o prazo ficou").kind, "capture")
        reply = brain.ask("nova conversa")
        self.assertIn("Conversa nova", reply)
        self.assertEqual(brain.memory.turns, [])
        self.assertNotIn("prazo ficticio", brain._compose("e agora?", None))
        self.assertIn("Nova conversa", help_speech(True))
        self.assertIn("Salva isso", help_speech(True))
        self.assertIn("Nova conversa", HELP)
        self.assertNotIn("\u2014", help_speech(True))
        self.assertNotIn("\u2014", HELP)

    def test_disco_nao_guarda_trecho_de_nota(self):
        os.environ["JARVIS_CONTEXTO_ARQUIVO"] = str(self.tmp / "contexto.json")
        memory = SessionMemory(limit=4, persist=True)
        memory.remember("o que foi dito", "Continuo no assunto ficticio.")
        memory.remember(
            "mostra o caminho",
            "Na nota Alfa, caminho Notas/sintetico.md: TRECHO-SINTETICO-9918.",
        )
        self.assertIn("TRECHO-SINTETICO-9918", memory.as_prompt())
        raw = (self.tmp / "contexto.json").read_text(encoding="utf-8")
        self.assertIn("o que foi dito", raw)
        self.assertIn("Continuo no assunto ficticio.", raw)
        self.assertNotIn("TRECHO-SINTETICO-9918", raw)
        self.assertNotIn("sintetico.md", raw)
        reloaded = SessionMemory(limit=4, persist=True)
        self.assertIn("Continuo no assunto ficticio.", reloaded.as_prompt())
        self.assertNotIn("TRECHO-SINTETICO-9918", reloaded.as_prompt())
        reloaded.clear()
        cleared = json.loads((self.tmp / "contexto.json").read_text(encoding="utf-8"))
        self.assertEqual(cleared["turnos"], [])

    def test_salva_isso_grava_a_resposta_anterior(self):
        from jarvis.brain import Brain
        from jarvis.routines import Intent

        root = self.tmp / "vault"
        root.mkdir()
        intent = Intent("save_last", text="O prazo ficticio ficou para sexta.")
        reply = run_routine(root, intent, NOW)
        self.assertIn("Salvei a resposta anterior", reply)
        note = (root / "2026-11-11.md").read_text(encoding="utf-8")
        self.assertIn("O prazo ficticio ficou para sexta.", note)
        self.assertNotIn("senhor", note)

        brain = Brain()
        brain.memory.remember("qual o prazo", "O prazo ficticio ficou para sexta.")
        seen = []

        def fake_routine(message, intent):
            seen.append(intent.text)
            return "Salvei a resposta anterior na nota de hoje, senhor."

        class Vault:
            def __init__(self, path):
                self.path = path

        brain.vault = Vault(root)
        brain._routine = fake_routine
        spoken = brain.ask("salva isso")
        self.assertEqual(seen, ["O prazo ficticio ficou para sexta."])
        self.assertIn("Salvei", spoken)
        empty = Brain()
        empty.memory.clear()
        self.assertIn("Não há resposta anterior", empty.ask("salva isso"))

    def test_tecla_ou_wake_param_a_fala_e_volta_a_ouvir(self):
        from jarvis import main as jarvis_main

        class Wake:
            def __init__(self):
                self.model = self

            def predict(self, frame):
                score = 0.95 if frame == "hot" else 0.0
                return {"hey_jarvis": score}

            def reset(self):
                return None

        class Frames:
            def __init__(self, values):
                self.values = list(values)

            def read(self):
                if not self.values:
                    time.sleep(0.01)
                    return "quiet"
                return self.values.pop(0)

            def close(self):
                return None

        class Keys:
            def __init__(self, pressed):
                self._pressed = pressed

            def pressed(self):
                return self._pressed

        def player(text, stop_event=None):
            deadline = time.time() + 2
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    return
                time.sleep(0.01)
            raise AssertionError("a fala nao parou")

        jarvis_main.audio.wake = Wake()
        jarvis_main.audio.ears = None
        heard = jarvis_main.speak_out(
            "resposta longa",
            frames=Frames(["quiet", "hot"]),
            keys=Keys(False),
            player=player,
        )
        self.assertEqual(heard, "listen")
        heard = jarvis_main.speak_out(
            "resposta longa",
            frames=Frames(["quiet", "quiet"]),
            keys=Keys(True),
            player=player,
        )
        self.assertEqual(heard, "listen")

        class Bus:
            def state(self, name):
                return name

            def transcript(self, role, text):
                return None

        brain = SimpleNamespace(
            ask=lambda message, on_sentence=None: "Resposta completa.",
            memory=None,
            last_sync=None,
        )
        with mock.patch("jarvis.main.speak_out", return_value="listen"):
            self.assertEqual(jarvis_main.respond(brain, "oi", Bus()), "listen")

    def test_stt_prefere_faster_whisper_e_cai_no_whisper(self):
        self.assertEqual(choose_stt("faster-whisper", True, True), "faster-whisper")
        self.assertEqual(choose_stt("faster-whisper", False, True), "whisper")
        self.assertEqual(choose_stt("auto", True, False), "faster-whisper")
        self.assertEqual(choose_stt("whisper", True, False), "faster-whisper")
        self.assertEqual(choose_stt("whisper", False, False), "")
        status, detail, _fix = doctor_status("faster-whisper", "base", True, True)
        self.assertEqual(status, "ok")
        self.assertIn("faster-whisper", detail)
        self.assertIn("base", detail)
        status, detail, _fix = doctor_status("faster-whisper", "tiny", False, True)
        self.assertIn("Whisper clássico", detail)
        self.assertIn("tiny", detail)

        seen = {}

        def faster(model):
            seen["faster"] = model
            raise OSError("sem modelo rapido")

        def classic(model):
            seen["classic"] = model
            return "classico"

        os.environ["JARVIS_STT"] = "faster-whisper"
        os.environ["JARVIS_WHISPER_MODEL"] = "base"
        opened = open_transcriber({"faster-whisper": faster, "whisper": classic})
        self.assertEqual(opened, "classico")
        self.assertEqual(seen["faster"], "base")
        self.assertEqual(seen["classic"], "base")

        with mock.patch("jarvis.stt.faster_importable", return_value=False):
            with mock.patch("jarvis.stt.whisper_importable", return_value=True):
                os.environ["JARVIS_WHISPER_MODEL"] = "tiny"
                buffer = []

                def capture():
                    import io
                    from contextlib import redirect_stdout

                    out = io.StringIO()
                    with redirect_stdout(out):
                        doctor.check_transcription()
                    buffer.append(out.getvalue())

                capture()
        self.assertIn("Whisper clássico", buffer[0])
        self.assertIn("tiny", buffer[0])
        self.assertNotIn("\u2014", buffer[0])

    def test_indice_so_reprocessa_o_que_mudou(self):
        root = self.tmp / "notas"
        root.mkdir()
        (root / ".obsidian").mkdir()
        (root / ".obsidian" / "oculto.md").write_text("nao entra\n", encoding="utf-8")
        (root / "alfa.md").write_text(
            "# Alfa\n\nMarcador alfa sintetico permanece.\n",
            encoding="utf-8",
        )
        (root / "beta.md").write_text(
            "# Beta\n\nMarcador beta sintetico original.\n",
            encoding="utf-8",
        )
        store = self.tmp / "indice.json"

        class Conta:
            def __init__(self):
                self.textos = []

            def embed(self, texts):
                self.textos.extend(texts)
                return [[1.0, 0.0] for _text in texts]

        primeiro = Conta()
        feitos = NoteIndex(root, primeiro, store).sync()
        self.assertEqual(sorted(feitos), ["alfa.md", "beta.md"])
        self.assertEqual(len(primeiro.textos), 2)
        saved = store.read_text(encoding="utf-8")
        self.assertNotIn("Marcador", saved)
        self.assertNotIn("alfa sintetico", saved)
        self.assertNotIn(".obsidian", saved)

        data = json.loads(saved)
        data["notas"]["alfa.md"]["mtime_ns"] = 1
        store.write_text(json.dumps(data), encoding="utf-8")
        segundo = Conta()
        self.assertEqual(NoteIndex(root, segundo, store).sync(), [])
        self.assertEqual(segundo.textos, [])

        (root / "beta.md").write_text(
            "# Beta\n\nMarcador beta sintetico alterado.\n",
            encoding="utf-8",
        )
        terceiro = Conta()
        refeitos = NoteIndex(root, terceiro, store).sync()
        self.assertEqual(refeitos, ["beta.md"])
        self.assertEqual(len(terceiro.textos), 1)
        self.assertIn("alterado", terceiro.textos[0])
        self.assertNotIn("permanece", terceiro.textos[0])
        self.assertNotIn("alterado", store.read_text(encoding="utf-8"))

        class Uma:
            def __init__(self):
                self.lotes = []

            def embed(self, texts):
                self.lotes.append(list(texts))
                return [[1.0, 0.0] for _text in texts]

        cache = self.tmp / "vetores.json"
        base = Uma()
        vectors_for(
            [
                {"relative": "a.md", "mtime_ns": 1, "tamanho": 3, "texto": "aaa"},
                {"relative": "b.md", "mtime_ns": 1, "tamanho": 3, "texto": "bbb"},
            ],
            base,
            cache,
        )
        self.assertEqual(len(base.lotes), 1)
        uma = Uma()
        vectors_for(
            [
                {"relative": "a.md", "mtime_ns": 1, "tamanho": 3, "texto": "aaa"},
                {"relative": "b.md", "mtime_ns": 9, "tamanho": 5, "texto": "novo-b"},
            ],
            uma,
            cache,
        )
        self.assertEqual(uma.lotes, [["novo-b"]])
        self.assertNotIn("novo-b", cache.read_text(encoding="utf-8"))
        self.assertNotIn("aaa", cache.read_text(encoding="utf-8"))

        medida = medir_arranque(self.tmp / "arranque", self.tmp / "arranque.json", notas=20, pausa=0.003)
        self.assertEqual(medida["refeitas_frio"], 20)
        self.assertEqual(medida["refeitas_morno"], [])
        self.assertEqual(medida["lotes_morno"], [])
        self.assertEqual(medida["refeitas_um"], ["nota-0.md"])
        self.assertEqual(medida["lotes_um"], [1])
        self.assertLess(medida["morno_s"], medida["frio_s"] / 2)
        self.assertLess(medida["um_s"], medida["frio_s"] / 2)
        self.assertNotIn(
            "Texto sintetico",
            (self.tmp / "arranque.json").read_text(encoding="utf-8"),
        )

    def test_fluxo_fala_a_primeira_frase_antes_do_fim(self):
        ready, rest = split_ready("Primeira frase pronta. Segunda ainda")
        self.assertEqual(ready, ["Primeira frase pronta."])
        self.assertIn("Segunda", rest)
        command = stream_command(["claude", "-p", "--output-format", "json"])
        self.assertIn("stream-json", command)
        self.assertIn("--include-partial-messages", command)

        class Fonte:
            def __init__(self, lines):
                self.lines = lines
                self.n = 0

            def __iter__(self):
                return self

            def __next__(self):
                if self.n >= len(self.lines):
                    raise StopIteration
                line = self.lines[self.n]
                self.n += 1
                return line

        primeira = json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Primeira frase pronta. "},
                },
            }
        )
        segunda = json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Segunda frase continua."},
                },
            }
        )
        fim = json.dumps(
            {
                "type": "result",
                "result": "Primeira frase pronta. Segunda frase continua.",
                "session_id": "sessao-1",
            }
        )
        fonte = Fonte([primeira, segunda, fim])
        fases = []

        def on_sentence(text):
            fases.append((text, fonte.n))
            return True

        text, session, stopped = consume_events(fonte, on_sentence)
        self.assertFalse(stopped)
        self.assertEqual(session, "sessao-1")
        self.assertEqual(fases[0], ("Primeira frase pronta.", 1))
        self.assertIn("Segunda frase continua.", text)

        fonte = Fonte([primeira, segunda])

        def parar(text):
            return False

        _text, _session, stopped = consume_events(fonte, parar)
        self.assertTrue(stopped)
        self.assertEqual(fonte.n, 1)

        linhas = Fonte(
            [
                '{"message":{"content":"O prazo ficticio e sexta. "},"done":false}',
                '{"message":{"content":"Depois vemos o resto."},"done":true}',
            ]
        )
        ouvidas = []

        def no_ollama(text):
            ouvidas.append((text, linhas.n))
            return True

        saida = consume_ollama(linhas, no_ollama)
        self.assertEqual(ouvidas[0][0], "O prazo ficticio e sexta.")
        self.assertEqual(ouvidas[0][1], 1)
        self.assertIn("Depois vemos", saida)

        from jarvis.brain import Brain

        brain = Brain()
        brain.wait_seconds = 30
        ordem = []

        def claude(message):
            ordem.append("abre")
            yield primeira
            ordem.append("meio")
            yield segunda
            ordem.append("fim")
            yield fim

        def fala(sentence):
            ordem.append("fala:" + sentence)
            return True

        brain.claude_stream = claude
        brain._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("json"))
        reply = brain.ask("qual o prazo ficticio?", on_sentence=fala)
        self.assertIn("Primeira frase pronta.", reply)
        self.assertLess(ordem.index("fala:Primeira frase pronta."), ordem.index("meio"))
        self.assertTrue(brain.streamed)

        os.environ["JARVIS_CEREBRO"] = "ollama"
        local = Brain()
        local.wait_seconds = 30
        local_ordem = []

        def ollama(system, user):
            local_ordem.append("l1")
            yield '{"message":{"content":"O prazo ficticio e sexta. "},"done":false}'
            local_ordem.append("l2")
            yield '{"message":{"content":"Depois vemos o resto."},"done":true}'

        def fala_local(sentence):
            local_ordem.append("fala:" + sentence)
            return True

        local.ollama_stream = ollama
        local._ask = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("claude"))
        local_reply = local.ask("qual o prazo?", on_sentence=fala_local)
        self.assertIn("sexta", local_reply)
        self.assertLess(local_ordem.index("fala:O prazo ficticio e sexta."), local_ordem.index("l2"))

        os.environ.pop("JARVIS_CEREBRO", None)
        queda = Brain()
        queda.wait_seconds = 30
        queda.claude_stream = lambda message: (_ for _ in ()).throw(OSError("sem fluxo"))
        queda._ask = lambda *_args, **_kwargs: "Resposta completa do teste."
        self.assertEqual(
            queda.ask("conta um prazo ficticio", on_sentence=lambda sentence: True),
            "Resposta completa do teste.",
        )

    def test_fontes_novas_sem_traco_longo(self):
        for name in (
            "frases.py",
            "fluxo.py",
            "stt.py",
            "indice_vetor.py",
            "memory.py",
            "barge.py",
            "main.py",
            "brain.py",
            "doctor.py",
            "chat.py",
            "ears.py",
            "transcribe.py",
            "cerebro.py",
            "routines.py",
        ):
            text = (ROOT / "jarvis" / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)
        self.assertNotIn("shell=True", (ROOT / "jarvis" / "barge.py").read_text(encoding="utf-8"))
        self.assertFalse((ROOT / "jarvis" / "stt.py").read_text(encoding="utf-8").startswith("import faster_whisper"))


class MedidaIndiceTest(unittest.TestCase):
    def test_relato_do_arranque(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        medida = medir_arranque(tmp / "notas", tmp / "indice.json", notas=24, pausa=0.004)
        ganho = medida["frio_s"] / medida["morno_s"] if medida["morno_s"] else 0
        self.assertEqual(medida["refeitas_morno"], [])
        self.assertGreater(medida["frio_s"], medida["morno_s"])
        self.assertGreater(ganho, 2)
        print(
            "INDICE_ARRANQUE notas={notas} frio_s={frio:.3f} morno_s={morno:.3f} "
            "um_s={um:.3f} ganho={ganho:.1f}x".format(
                notas=medida["notas"],
                frio=medida["frio_s"],
                morno=medida["morno_s"],
                um=medida["um_s"],
                ganho=ganho,
            )
        )
