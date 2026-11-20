import io
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis import ajustes, doctor, privacidade
from jarvis.catalogo import limpar_catalogo, obter
from jarvis.leitura import iter_markdown, pastas_ignoradas
from jarvis.privacidade import notas_sigilosas, regras_de_leitura
from jarvis.review import scan_cards
from jarvis.routines import (
    _open_tasks,
    day_plan,
    hybrid_notes,
    limpar_caixas,
    list_due,
    load_places,
)

TZ = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)
ENV = (
    "JARVIS_HOME",
    "JARVIS_VAULT",
    "JARVIS_VAULT_SYNC",
    "JARVIS_LOG",
    "JARVIS_PASTAS_IGNORADAS",
    "JARVIS_PASTAS_PRIVADAS",
)
SEGREDO = "SEGREDO-IGNORADO-771"


def _nota(path, texto):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8", newline="\n")


def _relativos(raiz, **kwargs):
    base = Path(raiz).resolve()
    return sorted(path.relative_to(base).as_posix() for path in iter_markdown(raiz, **kwargs))


class PastasIgnoradasTest(unittest.TestCase):
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
        limpar_catalogo()
        limpar_caixas()
        privacidade._SIGILO.clear()
        self.addCleanup(self._limpar)
        _nota(self.vault / "Estudos" / "quartzo.md", "# Quartzo\n\nO quartzo sintetico fica na estante.\nQual a cor do quartzo? ::: rosa\n")
        _nota(
            self.vault / "Agentes" / "memoria.md",
            "# Memoria de agente\n\nO quartzo sintetico aparece na memoria.\nPergunta de agente? ::: resposta\n"
            "- [ ] tarefa do agente\n- [ ] lembrete do agente @ 2026-11-13 09:00\n",
        )
        _nota(
            self.vault / "Projeto" / "controle" / "historico" / "copia.md",
            "# Copia antiga\n\nO quartzo sintetico na copia.\n- [ ] lembrete da copia @ 2026-11-13 08:00\n",
        )
        _nota(self.vault / "Projeto" / "atual.md", "# Atual\n\n- [ ] tarefa atual\n- [ ] lembrete atual @ 2026-11-13 10:00\n")
        _nota(self.vault / "Agentes" / "reservada.md", "# Reservada\n\n#sigiloso\n" + SEGREDO + "\n")

    def _limpar(self):
        limpar_catalogo()
        limpar_caixas()
        privacidade._SIGILO.clear()
        for chave, valor in self.saved.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sem_ajuste_nada_muda(self):
        self.assertEqual(pastas_ignoradas(), ())
        self.assertEqual(len(_relativos(self.vault)), 5)
        self.assertEqual(ajustes.pastas_ignoradas_raw(), "")

    def test_lista_aceita_virgula_e_recusa_nome_curto_oculto_e_fora_do_vault(self):
        os.environ["JARVIS_PASTAS_IGNORADAS"] = " Agentes ,historico; ab, .obsidian, ../fora, /abs, Agentes\nProjeto/controle "
        self.assertEqual(pastas_ignoradas(), ("Agentes", "historico", "Projeto/controle"))

    def test_pasta_da_raiz_e_nome_em_qualquer_nivel_saem_da_varredura(self):
        os.environ["JARVIS_PASTAS_IGNORADAS"] = "agentes, historico"
        self.assertEqual(_relativos(self.vault), ["Estudos/quartzo.md", "Projeto/atual.md"])
        self.assertEqual(len(_relativos(self.vault, ignorar=False)), 5)
        self.assertEqual(_relativos(self.vault / "Projeto"), ["atual.md"])
        self.assertEqual(_relativos(self.vault / "Agentes"), [])
        self.assertEqual(_relativos(self.vault / "Projeto" / "controle" / "historico"), [])
        self.assertEqual(len(_relativos(self.vault / "Agentes", ignorar=False)), 2)

    def test_busca_cartoes_tarefas_e_lembretes_pulam_as_pastas(self):
        self.assertEqual(len(hybrid_notes(self.vault, "quartzo sintetico", embedder=None, limit=9)), 3)
        self.assertEqual(len(scan_cards(self.vault)), 2)
        self.assertEqual(len(list_due(self.vault, AGORA)), 3)
        os.environ["JARVIS_PASTAS_IGNORADAS"] = "Agentes,historico"
        achados = hybrid_notes(self.vault, "quartzo sintetico", embedder=None, limit=9)
        self.assertEqual([hit.relative for hit in achados], ["Estudos/quartzo.md"])
        self.assertEqual([card["question"] for card in scan_cards(self.vault)], ["Qual a cor do quartzo?"])
        self.assertEqual([item.text for item in list_due(self.vault, AGORA)], ["lembrete atual"])
        self.assertEqual([item["text"] for item in _open_tasks(self.vault, "tarefa")], ["tarefa atual"])
        self.assertEqual(sorted(obter(self.vault).notas), ["Estudos/quartzo.md", "Projeto/atual.md"])
        places = load_places(self.vault)
        self.assertEqual([item.text for item in day_plan(self.vault, places, AGORA.date())], ["lembrete atual"])

    def test_sigilo_continua_valendo_dentro_de_pasta_ignorada(self):
        os.environ["JARVIS_PASTAS_IGNORADAS"] = "Agentes"
        self.assertEqual(notas_sigilosas(self.vault), ["Agentes/reservada.md"])
        regras = regras_de_leitura(self.vault)
        self.assertIn("Read(./Agentes/reservada.md)", regras)
        self.assertNotIn(SEGREDO, " ".join(regras))

    def test_agenda_dentro_de_pasta_ignorada_fica_vazia(self):
        _nota(self.vault / "AGENTS.md", "agenda profissional: `Arquivo/Agenda`\n")
        _nota(self.vault / "Arquivo" / "Agenda" / "2026-11-13.md", "- 09:00 reuniao sintetica\n")
        places = load_places(self.vault)
        self.assertIn("reuniao sintetica", [item.text for item in day_plan(self.vault, places, AGORA.date())])
        os.environ["JARVIS_PASTAS_IGNORADAS"] = "Arquivo"
        limpar_caixas()
        textos = [item.text for item in day_plan(self.vault, places, AGORA.date())]
        self.assertNotIn("reuniao sintetica", textos)

    def test_diagnostico_diz_quantas_ficaram_de_fora(self):
        doctor.results.clear()
        saida = io.StringIO()
        with mock.patch("sys.stdout", saida):
            doctor.check_notas(self.vault)
        self.assertIn("5 notas ao alcance da busca", saida.getvalue())
        self.assertNotIn("JARVIS_PASTAS_IGNORADAS", saida.getvalue())
        os.environ["JARVIS_PASTAS_IGNORADAS"] = "Agentes,historico"
        saida = io.StringIO()
        with mock.patch("sys.stdout", saida):
            doctor.check_notas(self.vault)
        self.assertIn("2 notas ao alcance da busca. 3 fora por JARVIS_PASTAS_IGNORADAS", saida.getvalue())
        doctor.results.clear()

    def test_ajuste_esta_no_catalogo_e_avisa_que_nao_e_sigilo(self):
        entrada = next(item for item in ajustes.CATALOGO if item.nome == "JARVIS_PASTAS_IGNORADAS")
        self.assertEqual(entrada.padrao, "")
        self.assertIn("Não é sigilo", entrada.descricao)
        raiz = Path(__file__).resolve().parents[1]
        self.assertIn("JARVIS_PASTAS_IGNORADAS=", (raiz / ".env.exemplo").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
