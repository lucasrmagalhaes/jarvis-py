"""Mede índice, busca, cartões e revisão num vault sintético.

python -m jarvis.benchmark

Não lê o vault real e não imprime texto de nota.
"""

import argparse
import hashlib
import os
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from .sintetico import gerar_vault


class HashEmbedder:
    def embed(self, texts):
        rows = []
        for text in texts:
            digest = hashlib.sha256((text or "").encode("utf-8", errors="replace")).digest()
            rows.append([byte / 255.0 for byte in digest[:8]])
        return rows


def medir(root, repeticoes=5):
    """Devolve só números. O texto das notas não entra no resultado."""

    from .catalogo import limpar_catalogo
    from .indice_vetor import NoteIndex
    from .review import _save, load_state, scan_cards
    from .routines import hybrid_notes

    raiz = Path(root)
    home = Path(os.environ.get("JARVIS_HOME") or tempfile.mkdtemp(prefix="jarvis-bench-"))
    home.mkdir(parents=True, exist_ok=True)
    store = home / "benchmark-indice.json"
    revisao = Path(os.environ.get("JARVIS_REVISAO") or (home / "revisao.json"))
    os.environ["JARVIS_REVISAO"] = str(revisao)
    embedder = HashEmbedder()
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    limpar_catalogo()
    try:
        def frio():
            return NoteIndex(raiz, embedder, store).sync()

        feitos, frio_s = _relogio(frio)
        _nada, morno_s = _relogio(frio)
        _tocar_uma(raiz)
        um, um_s = _relogio(frio)

        buscas = []
        for _ in range(max(1, int(repeticoes))):
            _hits, segundos = _relogio(
                lambda: hybrid_notes(raiz, "quartzo sintetico", embedder=None, limit=5)
            )
            buscas.append(segundos)
        busca_fria = buscas[0]
        busca = statistics.median(buscas[1:] or buscas)

        from .semantica import IndiceSemantico, buscar_trechos, hits_da_busca

        store_sem = home / "benchmark-semantica.json"

        def _sync_sem():
            return IndiceSemantico(raiz, embedder, store_sem).sincronizar() or []

        refeitas_sem, sem_frio_s = _relogio(_sync_sem)
        _nada, sem_morno_s = _relogio(_sync_sem)
        _tocar_uma(raiz)
        refeitas_sem_um, sem_um_s = _relogio(_sync_sem)
        _nada, sem_busca_s = _relogio(
            lambda: buscar_trechos(
                raiz, "quartzo sintetico", embedder, limite=5, store=store_sem
            )
        )
        _nada, hibrida_s = _relogio(
            lambda: hits_da_busca(
                raiz,
                "quartzo sintetico",
                "hibrida",
                embedder=embedder,
                limite=5,
                store=store_sem,
            )
        )

        cards, cartoes_s = _relogio(lambda: scan_cards(raiz))
        estado = _estado(cards)
        _nada, gravar_s = _relogio(lambda: _save(revisao, estado))
        carregado, ler_s = _relogio(load_state)
        _atual, pico = tracemalloc.get_traced_memory()
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        limpar_catalogo()
    return {
        "notas": len(feitos) if feitos else _contar_md(raiz),
        "indice_frio_s": frio_s,
        "refeitas_frio": len(feitos),
        "indice_morno_s": morno_s,
        "reindice_s": um_s,
        "refeitas_um": len(um),
        "busca_fria_s": busca_fria,
        "busca_s": busca,
        "semantica_fria_s": sem_frio_s,
        "semantica_refeitas_frio": len(refeitas_sem),
        "semantica_morna_s": sem_morno_s,
        "semantica_reindex_s": sem_um_s,
        "semantica_refeitas_um": len(refeitas_sem_um),
        "busca_semantica_s": sem_busca_s,
        "busca_hibrida_s": hibrida_s,
        "cartoes_s": cartoes_s,
        "cartoes": len(cards),
        "revisao_gravar_s": gravar_s,
        "revisao_ler_s": ler_s,
        "revisao_cards": len((carregado or {}).get("cards") or {}),
        "memoria_mb": pico / (1024 * 1024),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m jarvis.benchmark",
        description="Mede um vault sintético. Não usa as suas notas.",
    )
    parser.add_argument("--pasta", default="", help="pasta já gerada; o padrão cria uma temporária")
    parser.add_argument("--notas", type=int, default=2100)
    parser.add_argument("--livros", type=int, default=340)
    parser.add_argument("--videos", type=int, default=80)
    parser.add_argument("--cursos", type=int, default=40)
    parser.add_argument("--cartoes", type=int, default=7300)
    parser.add_argument("--manter", action="store_true")
    args = parser.parse_args(argv)
    base = None
    if args.pasta:
        raiz = Path(args.pasta).expanduser()
        if not raiz.is_dir():
            print("A pasta do benchmark não existe.")
            return 1
    else:
        base = Path(tempfile.mkdtemp(prefix="jarvis-sintetico-"))
        raiz = base / "vault"
        resumo = gerar_vault(
            raiz,
            notas=args.notas,
            livros=args.livros,
            videos=args.videos,
            cursos=args.cursos,
            cartoes=args.cartoes,
        )
        print(
            "Vault sintético: "
            + str(resumo["notas"])
            + " notas, "
            + str(resumo["cartoes"])
            + " cartões."
        )
    home = Path(tempfile.mkdtemp(prefix="jarvis-bench-home-"))
    os.environ["JARVIS_HOME"] = str(home)
    os.environ["JARVIS_VAULT_SYNC"] = "off"
    os.environ["JARVIS_REVISAO"] = str(home / "revisao.json")
    try:
        resultado = medir(raiz)
    finally:
        if base is not None and not args.manter:
            shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
    _imprimir(resultado)
    return 0


def _imprimir(resultado):
    print(f"Indice frio: {resultado['indice_frio_s']:.3f}s ({resultado['refeitas_frio']} notas)")
    print(f"Indice morno: {resultado['indice_morno_s']:.3f}s")
    print(f"Reindice: {resultado['reindice_s']:.3f}s ({resultado['refeitas_um']} notas)")
    print(f"Busca fria: {resultado['busca_fria_s']:.3f}s")
    print(f"Busca: {resultado['busca_s']:.3f}s")
    print(
        "Semantica fria: "
        + format(resultado["semantica_fria_s"], ".3f")
        + "s ("
        + str(resultado["semantica_refeitas_frio"])
        + " notas)"
    )
    print(f"Semantica morna: {resultado['semantica_morna_s']:.3f}s")
    print(
        "Reindice semantico: "
        + format(resultado["semantica_reindex_s"], ".3f")
        + "s ("
        + str(resultado["semantica_refeitas_um"])
        + " notas)"
    )
    print(f"Busca semantica: {resultado['busca_semantica_s']:.3f}s")
    print(f"Busca hibrida: {resultado['busca_hibrida_s']:.3f}s")
    print(f"Cartoes: {resultado['cartoes_s']:.3f}s ({resultado['cartoes']})")
    print(f"Revisao gravar: {resultado['revisao_gravar_s']:.3f}s")
    print(f"Revisao ler: {resultado['revisao_ler_s']:.3f}s ({resultado['revisao_cards']})")
    print(f"Memoria: {resultado['memoria_mb']:.1f} MB")


def _estado(cards):
    dados = {}
    for card in cards:
        dados[card["id"]] = {
            "interval": 1,
            "ease": 2.5,
            "reps": 1,
            "lapses": 0,
            "due": "2026-11-12",
            "path": card["path"],
        }
    return {
        "cards": dados,
        "daily": {"date": "2026-11-11", "count": 0, "novos": 0},
        "paused_on": "",
        "days": ["2026-11-11"],
        "session": None,
    }


def _tocar_uma(raiz):
    for path in Path(raiz).rglob("*.md"):
        if path.name.startswith("."):
            continue
        try:
            texto = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        path.write_text(texto + "\nAjuste sintetico do indice.\n", encoding="utf-8", newline="\n")
        return


def _contar_md(raiz):
    return sum(1 for path in Path(raiz).rglob("*.md") if not path.name.startswith("."))


def _relogio(func):
    inicio = time.perf_counter()
    valor = func()
    return valor, time.perf_counter() - inicio


if __name__ == "__main__":
    sys.exit(main())
