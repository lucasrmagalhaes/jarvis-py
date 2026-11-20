"""O registro de comandos e o catálogo de configuração ficam alinhados."""

import os
import re
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

from jarvis.ajustes import (  # noqa: E402
    CATALOGO,
    bandeja_ligada,
    nomes,
    panel_bind,
    reminder_interval,
    render_env_exemplo,
    render_tabela,
    whisper_model,
)
from jarvis.comandos import (  # noqa: E402
    COMANDOS,
    casamentos,
    render_comandos,
    resolver,
    texto_ajuda,
)
from jarvis.routines import classify  # noqa: E402

ENV_CALL = re.compile(
    r"""(?:environ(?:\.get)?|source\.get|_flag|_bounded_int)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
)
SKIP_ENV = {"PATH", "APPDATA", "USERNAME", "HF_HUB_OFFLINE"}

CONFLITOS = {
    "bom dia": "briefing",
    "o que tenho para hoje": "briefing",
    "o que tenho hoje": "agenda",
    "o que aprendi": "learned",
    "o que aprendi esta semana": "learned",
    "me testa": "study",
    "me testa sobre a fita": "study",
    "modo privado": "private_on",
    "sai do modo privado": "private_off",
    "nova conversa": "new_chat",
    "anota isso": "save_last",
}


class RegistroTest(unittest.TestCase):
    def test_cada_intencao_tem_ajuda_e_um_exemplo(self):
        ajuda = texto_ajuda(True)
        vistos = [comando.nome for comando in COMANDOS]
        self.assertEqual(len(vistos), len(set(vistos)))
        self.assertNotIn("setup", ajuda)
        self.assertNotIn("\u2014", ajuda)
        self.assertNotIn("\u2013", ajuda)
        for comando in COMANDOS:
            self.assertTrue(comando.descricao.strip())
            self.assertTrue(comando.exemplos)
            self.assertIn(comando.fala, ajuda)
            self.assertTrue(callable(resolver(comando)))
            for exemplo in comando.exemplos:
                self.assertEqual(classify(exemplo).kind, comando.nome, exemplo)
                self.assertEqual(casamentos(exemplo), [comando.nome], exemplo)

    def test_frases_sobrepostas_caem_num_so_comando(self):
        for frase, kind in CONFLITOS.items():
            self.assertEqual(casamentos(frase), [kind], frase)
            self.assertEqual(classify(frase).kind, kind, frase)

    def test_catalogo_bate_com_o_exemplo_e_o_readme(self):
        exemplo = (ROOT / ".env.exemplo").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(exemplo, render_env_exemplo())
        self.assertIn(render_tabela(), readme)
        self.assertIn(render_comandos(), readme)
        self.assertNotIn("\u2014", exemplo)
        self.assertNotIn("\u2013", exemplo)
        self.assertNotIn("\u2014", readme)
        self.assertNotIn("\u2013", readme)
        for item in CATALOGO:
            self.assertIn(item.nome, exemplo)
            self.assertIn(item.nome, readme)
        found = set()
        for path in (ROOT / "jarvis").glob("*.py"):
            found.update(ENV_CALL.findall(path.read_text(encoding="utf-8")))
        fora = sorted(name for name in found - SKIP_ENV if name not in nomes())
        self.assertEqual(fora, [])

    def test_validacao_rejeita_valor_ruim(self):
        with mock.patch.dict(os.environ, {"JARVIS_BANDEJA": "não"}):
            self.assertFalse(bandeja_ligada())
        with mock.patch.dict(os.environ, {"JARVIS_REMINDER_SECONDS": "1"}):
            self.assertEqual(reminder_interval(), 5)
        with mock.patch.dict(os.environ, {"JARVIS_PANEL_BIND": "0.0.0.0"}):
            self.assertEqual(panel_bind(), "127.0.0.1")
        with mock.patch.dict(os.environ, {"JARVIS_WHISPER_MODEL": "../fora"}):
            self.assertEqual(whisper_model(), "small")
