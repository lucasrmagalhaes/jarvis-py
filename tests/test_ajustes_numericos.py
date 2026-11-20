import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from jarvis import ajustes, doctor

ROOT = Path(__file__).resolve().parents[1]
NOMES = tuple(ajustes._NUMEROS)


class AjustesNumericosTest(unittest.TestCase):
    def setUp(self):
        self.saved = {nome: os.environ.get(nome) for nome in NOMES}
        for nome in NOMES:
            os.environ.pop(nome, None)
        self.addCleanup(self._restaurar)

    def _restaurar(self):
        for nome, valor in self.saved.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor

    def test_padrao_sem_variavel_e_com_variavel_vazia(self):
        self.assertEqual(ajustes.turn_timeout(), 300)
        self.assertEqual(ajustes.panel_port(), 8765)
        self.assertEqual(ajustes.silence_threshold(), 0.012)
        os.environ["JARVIS_EDGE_TIMEOUT"] = ""
        os.environ["JARVIS_TURN_TIMEOUT"] = "   "
        self.assertEqual(ajustes.edge_timeout(), 30.0)
        self.assertEqual(ajustes.turn_timeout(), 300)
        self.assertEqual(ajustes.numeros_invalidos(), [])

    def test_valor_valido_e_respeitado_e_virgula_decimal_e_aceita(self):
        os.environ["JARVIS_TURN_TIMEOUT"] = "45"
        os.environ["JARVIS_SILENCE_THRESHOLD"] = "0,02"
        os.environ["JARVIS_WAKE_THRESHOLD"] = " 0.7 "
        os.environ["JARVIS_SAPI_RATE"] = "-3"
        self.assertEqual(ajustes.turn_timeout(), 45)
        self.assertIsInstance(ajustes.turn_timeout(), int)
        self.assertAlmostEqual(ajustes.silence_threshold(), 0.02)
        self.assertAlmostEqual(ajustes.wake_threshold(), 0.7)
        self.assertEqual(ajustes.sapi_rate(), -3)
        self.assertEqual(ajustes.numeros_invalidos(), [])

    def test_texto_fora_de_faixa_e_infinito_caem_no_padrao_e_sao_listados(self):
        os.environ["JARVIS_TURN_TIMEOUT"] = "5min"
        os.environ["JARVIS_PANEL_PORT"] = "99999"
        os.environ["JARVIS_SPEECH_RATE"] = "rapido"
        os.environ["JARVIS_EDGE_TIMEOUT"] = "inf"
        os.environ["JARVIS_SILENCE_SECONDS"] = "nan"
        os.environ["JARVIS_WAKE_THRESHOLD"] = "2"
        os.environ["JARVIS_SAPI_RATE"] = "40"
        os.environ["JARVIS_MAX_RECORD_SECONDS"] = "-1"
        self.assertEqual(ajustes.turn_timeout(), 300)
        self.assertEqual(ajustes.panel_port(), 8765)
        self.assertEqual(ajustes.speech_rate(), 190)
        self.assertEqual(ajustes.edge_timeout(), 30.0)
        self.assertEqual(ajustes.silence_seconds(), 1.2)
        self.assertEqual(ajustes.wake_threshold(), 0.5)
        self.assertEqual(ajustes.sapi_rate(), 1)
        self.assertEqual(ajustes.max_record_seconds(), 60.0)
        self.assertEqual(
            sorted(ajustes.numeros_invalidos()),
            sorted(
                [
                    "JARVIS_TURN_TIMEOUT",
                    "JARVIS_PANEL_PORT",
                    "JARVIS_SPEECH_RATE",
                    "JARVIS_EDGE_TIMEOUT",
                    "JARVIS_SILENCE_SECONDS",
                    "JARVIS_WAKE_THRESHOLD",
                    "JARVIS_SAPI_RATE",
                    "JARVIS_MAX_RECORD_SECONDS",
                ]
            ),
        )

    def test_todo_numero_do_catalogo_tem_o_mesmo_padrao_do_exemplo(self):
        padroes = {item.nome: item.padrao for item in ajustes.CATALOGO}
        for nome, (tipo, padrao, _baixo, _alto) in ajustes._NUMEROS.items():
            self.assertIn(nome, padroes)
            self.assertEqual(tipo(padroes[nome]), padrao, nome)

    def test_diagnostico_avisa_o_nome_sem_mostrar_o_valor(self):
        doctor.results.clear()
        saida = io.StringIO()
        with mock.patch("sys.stdout", saida):
            doctor.check_numeros({})
        self.assertEqual(saida.getvalue(), "")
        with mock.patch("sys.stdout", saida):
            doctor.check_numeros({"JARVIS_TURN_TIMEOUT": "valor-torto-771"})
        texto = saida.getvalue()
        self.assertIn("JARVIS_TURN_TIMEOUT", texto)
        self.assertIn("Ajustes numéricos", texto)
        self.assertNotIn("valor-torto-771", texto)
        self.assertIn((doctor.WARN, "Ajustes numéricos"), doctor.results)
        doctor.results.clear()

    def test_importar_a_configuracao_com_numero_torto_nao_quebra(self):
        ambiente = dict(os.environ)
        ambiente["JARVIS_TURN_TIMEOUT"] = "5min"
        ambiente["JARVIS_SILENCE_THRESHOLD"] = "0,012"
        ambiente["JARVIS_PANEL_PORT"] = "oito"
        processo = subprocess.run(
            [
                sys.executable,
                "-c",
                "from jarvis import config; "
                "print(config.TURN_TIMEOUT, config.SILENCE_THRESHOLD, config.PANEL_PORT)",
            ],
            cwd=str(ROOT),
            env=ambiente,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(processo.returncode, 0, processo.stderr)
        self.assertEqual(processo.stdout.split(), ["300", "0.012", "8765"])

    def test_dica_de_voz_fala_do_sistema_certo(self):
        self.assertIn("SAPI", doctor._dica_voz_neural("Windows"))
        self.assertIn("say", doctor._dica_voz_neural("Darwin"))
        self.assertNotIn("Windows", doctor._dica_voz_neural("Darwin"))
        self.assertNotIn("Windows", doctor._dica_voz_neural("Linux"))


if __name__ == "__main__":
    unittest.main()
