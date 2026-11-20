import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.catalogo import limpar_catalogo
from jarvis.routines import (
    append_capture,
    classify,
    daily_note_path,
    day_plan,
    limpar_caixas,
    load_places,
    run_routine,
)

TZ = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 11, 13, 12, 22, tzinfo=TZ)
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_LOG",
    "JARVIS_GH_BIN",
    "JARVIS_PASTAS_IGNORADAS",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
)


def _nota(path, texto):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8", newline="\n")


class AgendaEAnotacaoTest(unittest.TestCase):
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
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        limpar_catalogo()
        limpar_caixas()
        self.addCleanup(self._limpar)

    def _limpar(self):
        limpar_catalogo()
        limpar_caixas()
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_anotacao_na_nota_diaria_nao_vira_compromisso(self):
        _nota(self.vault / "AGENTS.md", "nota diária: `Diario/AAAA-MM-DD.md`\n")
        places = load_places(self.vault)
        caminho = append_capture(self.vault, places, "comprar cafe sintetico", AGORA)
        self.assertEqual(caminho, self.vault / "Diario" / "2026-11-13.md")
        self.assertIn("- 12:22 comprar cafe sintetico", caminho.read_text(encoding="utf-8"))
        self.assertEqual(day_plan(self.vault, places, AGORA.date()), [])
        fala = run_routine(self.vault, classify("o que tenho hoje"), AGORA)
        self.assertIn("Não há compromisso hoje", fala)
        self.assertNotIn("comprar cafe", fala)
        bom_dia = run_routine(self.vault, classify("bom dia"), AGORA)
        self.assertNotIn("Às 12:22", bom_dia)
        self.assertNotIn("Agenda de hoje: Às", bom_dia)

    def test_nota_diaria_ainda_entrega_lembrete_e_linha_com_data(self):
        _nota(self.vault / "AGENTS.md", "nota diária: `Diario/AAAA-MM-DD.md`\n")
        _nota(
            self.vault / "Diario" / "2026-11-13.md",
            "# 2026-11-13\n\n"
            "- 12:22 anotacao solta\n"
            "- 09h30 outra anotacao\n"
            "- [ ] ligar para o cliente sintetico @ 2026-11-13 15:00\n"
            "- 2026-11-13 16:00 visita tecnica\n"
            "- [x] feito @ 2026-11-13 08:00\n",
        )
        places = load_places(self.vault)
        hoje = [(item.text, item.when.strftime("%H:%M")) for item in day_plan(self.vault, places, AGORA.date())]
        self.assertEqual(hoje, [("ligar para o cliente sintetico", "15:00"), ("visita tecnica", "16:00")])
        self.assertEqual(day_plan(self.vault, places, AGORA.date() + timedelta(days=1)), [])
        fala = run_routine(self.vault, classify("o que tenho hoje"), AGORA)
        self.assertIn("ligar para o cliente sintetico", fala)
        self.assertIn("visita tecnica", fala)
        self.assertNotIn("anotacao", fala)

    def test_hora_solta_continua_valendo_na_agenda(self):
        _nota(self.vault / "AGENTS.md", "nota diária: `Diario/AAAA-MM-DD.md`\n")
        _nota(self.vault / "Agenda Profissional" / "2026-11-13.md", "# Sexta\n\n- 09:00 Daily do time\n- 14h30 Reuniao com o cliente\n")
        _nota(self.vault / "Diario" / "2026-11-13.md", "- 12:22 comprar cafe sintetico\n")
        places = load_places(self.vault)
        textos = [item.text for item in day_plan(self.vault, places, AGORA.date())]
        self.assertEqual(textos, ["Daily do time", "Reuniao com o cliente"])

    def test_nota_diaria_que_mora_na_agenda_segue_como_agenda(self):
        _nota(
            self.vault / "AGENTS.md",
            "agenda profissional: `Compromissos`\nnota diária: `Compromissos/AAAA-MM-DD.md`\n",
        )
        (self.vault / "Compromissos").mkdir()
        places = load_places(self.vault)
        self.assertEqual(places.agenda, "Compromissos")
        self.assertEqual(
            daily_note_path(self.vault, places, AGORA.date()),
            self.vault / "Compromissos" / "2026-11-13.md",
        )
        _nota(self.vault / "Compromissos" / "2026-11-13.md", "- 09:00 Daily do time\n")
        textos = [item.text for item in day_plan(self.vault, places, AGORA.date())]
        self.assertEqual(textos, ["Daily do time"])

    def test_amanha_do_resumo_do_dia_nao_lista_anotacao(self):
        _nota(self.vault / "AGENTS.md", "nota diária: `Diario/AAAA-MM-DD.md`\n")
        _nota(self.vault / "Diario" / "2026-11-13.md", "# Hoje\n\n- 10:00 anotacao de hoje\n")
        _nota(
            self.vault / "Diario" / "2026-11-14.md",
            "- 08:00 anotacao adiantada\n- [ ] buscar o carro sintetico @ 2026-11-14 15:00\n",
        )
        fala = run_routine(self.vault, classify("como foi meu dia?"), AGORA, session={})
        self.assertIn("buscar o carro sintetico", fala)
        self.assertNotIn("anotacao adiantada", fala)


if __name__ == "__main__":
    unittest.main()
