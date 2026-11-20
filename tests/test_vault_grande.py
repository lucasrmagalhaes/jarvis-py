import io
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from jarvis import doctor, routines
from jarvis.catalogo import Catalogo, limpar_catalogo
from jarvis.leitura import limpar_avisos
from jarvis.routines import (
    _open_reminders,
    _open_tasks,
    limpar_caixas,
    linhas_de_caixa,
    list_due,
    mark_reminded,
)

TZ = ZoneInfo("America/Sao_Paulo")
AGORA = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)
ANTIGO = 1_700_000_000


def _nota(path, texto, antigo=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(texto, encoding="utf-8", newline="\n")
    if antigo:
        os.utime(path, (ANTIGO, ANTIGO))


class VaultGrandeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        limpar_caixas()
        limpar_catalogo()
        limpar_avisos()
        self.addCleanup(self._limpar)

    def _limpar(self):
        limpar_caixas()
        limpar_catalogo()
        limpar_avisos()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_teto_cobre_um_vault_de_milhares_de_notas(self):
        self.assertGreaterEqual(routines.MAX_WALK, 50000)

    def test_catalogo_avisa_uma_vez_quando_o_teto_corta(self):
        for indice in range(6):
            _nota(self.vault / "Pasta" / f"nota-{indice}.md", f"# Nota {indice}\n\nTexto sintetico.\n")
        avisos = []
        with mock.patch.object(routines, "MAX_WALK", 4), mock.patch(
            "jarvis.catalogo.avisar", side_effect=lambda *args: avisos.append(args)
        ):
            catalogo = Catalogo()
            catalogo.sincronizar(self.vault)
        self.assertEqual(len(catalogo.notas), 4)
        self.assertIn(("vault", "teto-de-notas"), avisos)
        avisos.clear()
        with mock.patch("jarvis.catalogo.avisar", side_effect=lambda *args: avisos.append(args)):
            inteiro = Catalogo()
            inteiro.sincronizar(self.vault)
        self.assertEqual(len(inteiro.notas), 6)
        self.assertNotIn(("vault", "teto-de-notas"), avisos)

    def test_diagnostico_conta_as_notas_e_avisa_acima_do_teto(self):
        _nota(self.vault / "a.md", "# A\n")
        _nota(self.vault / ".obsidian" / "oculta.md", "# Oculta\n")
        doctor.results.clear()
        saida = io.StringIO()
        with mock.patch("sys.stdout", saida):
            doctor.check_notas(self.vault)
        self.assertIn("1 notas ao alcance da busca", saida.getvalue())
        self.assertIn((doctor.OK, "Notas do vault"), doctor.results)
        doctor.results.clear()
        saida = io.StringIO()
        with mock.patch("sys.stdout", saida):
            doctor.check_notas(self.vault, contar=lambda _pasta: routines.MAX_WALK + 1)
        self.assertIn("acima do teto", saida.getvalue())
        self.assertIn((doctor.WARN, "Notas do vault"), doctor.results)
        doctor.results.clear()

    def test_lembrete_vencido_aparece_sem_reler_a_nota_que_nao_mudou(self):
        _nota(self.vault / "Lembretes.md", "- [ ] pagar o boleto sintetico @ 2026-11-13 09:00\n")
        for indice in range(30):
            _nota(self.vault / "Estudos" / f"nota-{indice}.md", f"# Nota {indice}\n\nSem tarefa aqui.\n")
        primeira = list_due(self.vault, AGORA)
        self.assertEqual([item.text for item in primeira], ["pagar o boleto sintetico"])
        self.assertEqual(primeira[0].line_index, 0)
        with mock.patch.object(routines, "_read", side_effect=AssertionError("releu")):
            segunda = list_due(self.vault, AGORA)
            abertos = _open_reminders(self.vault)
            tarefas = _open_tasks(self.vault, "boleto")
        self.assertEqual([item.text for item in segunda], ["pagar o boleto sintetico"])
        self.assertEqual([item["text"] for item in abertos], ["pagar o boleto sintetico"])
        self.assertEqual(len(tarefas), 1)

    def test_nota_alterada_e_relida_e_lembrete_avisado_some(self):
        nota = self.vault / "Lembretes.md"
        _nota(nota, "# Lembretes\n\n- [ ] ligar para o cliente sintetico @ 2026-11-13 08:00\n")
        vencidos = list_due(self.vault, AGORA)
        self.assertEqual(len(vencidos), 1)
        self.assertEqual(vencidos[0].line_index, 2)
        marcados = mark_reminded(vencidos, AGORA, self.vault)
        self.assertEqual(len(marcados), 1)
        self.assertIn("@avisado", nota.read_text(encoding="utf-8"))
        self.assertEqual(list_due(self.vault, AGORA), [])
        _nota(
            nota,
            "# Lembretes\n\n- [ ] ligar para o cliente sintetico @ 2026-11-13 08:00 @avisado\n"
            "- [ ] novo lembrete sintetico @ 2026-11-13 10:00\n",
            antigo=False,
        )
        self.assertEqual([item.text for item in list_due(self.vault, AGORA)], ["novo lembrete sintetico"])
        nota.unlink()
        self.assertEqual(list_due(self.vault, AGORA), [])
        self.assertEqual(linhas_de_caixa(nota), ())

    def test_nota_recem_gravada_nao_fica_no_cache(self):
        nota = self.vault / "Tarefas.md"
        _nota(nota, "- [ ] tarefa sintetica\n", antigo=False)
        self.assertEqual(linhas_de_caixa(nota), ((0, "- [ ] tarefa sintetica"),))
        self.assertNotIn(str(nota), routines._CAIXAS)
        marca = nota.stat()
        nota.write_text("- [x] tarefa sintetica\n", encoding="utf-8", newline="\n")
        os.utime(nota, ns=(marca.st_atime_ns, marca.st_mtime_ns))
        self.assertEqual(nota.stat().st_size, marca.st_size)
        self.assertEqual(linhas_de_caixa(nota), ((0, "- [x] tarefa sintetica"),))

    def test_cache_guarda_so_linha_de_caixa(self):
        nota = self.vault / "Mista.md"
        _nota(
            nota,
            "# Mista\n\nTexto solto sintetico.\n- item sem caixa\n- [ ] tarefa aberta\n  - [x] tarefa feita\n",
        )
        self.assertEqual(
            linhas_de_caixa(nota),
            ((4, "- [ ] tarefa aberta"), (5, "  - [x] tarefa feita")),
        )
        guardado = routines._CAIXAS[str(nota)]
        self.assertNotIn("Texto solto", repr(guardado))


if __name__ == "__main__":
    unittest.main()
