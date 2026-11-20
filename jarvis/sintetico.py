"""Vault sintético para medir escala. Não copia nota real."""

import random
from pathlib import Path

PALAVRAS = (
    "farol",
    "hortela",
    "nuvem",
    "fita",
    "papel",
    "sintetico",
    "cacto",
    "elastico",
    "oficina",
    "modulo",
    "trilha",
    "bruma",
    "quartzo",
    "vela",
    "mapa",
    "bussola",
    "ancora",
    "duna",
    "litoral",
    "orvalho",
    "lampejo",
    "grade",
    "ninho",
    "ponta",
    "rumo",
    "seixo",
    "tela",
    "viga",
    "zelo",
)

TRILHAS = (
    "Diário/Março/Manhã",
    "Referências/Ciência/Áudio",
    "Projetos/Lições/Módulo",
    "Estudos/Revisão/Síntese",
    "Notas/Ideias/Rascunho",
    "Arquivo/Pessoal/Viagem",
)

PASTA_LIVROS = "Tecnologia/Livros"
PASTA_VIDEOS = "Tecnologia/Vídeos"
PASTA_CURSOS = "Tecnologia/Cursos"


def gerar_vault(
    destino,
    notas=2100,
    livros=340,
    videos=80,
    cursos=40,
    cartoes=7300,
    seed=20261111,
    longas=24,
):
    """Cria notas aleatórias. Devolve a contagem, sem o texto."""

    root = Path(destino)
    root.mkdir(parents=True, exist_ok=True)
    total = max(1, int(notas))
    n_livros = min(max(0, int(livros)), total)
    n_videos = min(max(0, int(videos)), total - n_livros)
    n_cursos = min(max(0, int(cursos)), total - n_livros - n_videos)
    n_outras = total - n_livros - n_videos - n_cursos
    plano = _plano_cartoes(total, n_livros, n_videos, n_cursos, max(0, int(cartoes)))
    rng = random.Random(seed)
    grupos = (
        (PASTA_LIVROS, "livro", n_livros),
        (PASTA_VIDEOS, "video", n_videos),
        (PASTA_CURSOS, "curso", n_cursos),
    )
    indice = 0
    escritos = 0
    for pasta, tipo, quantidade in grupos:
        for numero in range(quantidade):
            relativa = f"{pasta}/{tipo}-{numero:04d}.md"
            _gravar(root, relativa, tipo, numero, plano[indice], rng, longa=False)
            indice += 1
            escritos += 1
    for numero in range(n_outras):
        trilha = TRILHAS[numero % len(TRILHAS)]
        relativa = f"{trilha}/nota-{numero:04d}.md"
        _gravar(
            root,
            relativa,
            "nota",
            numero,
            plano[indice],
            rng,
            longa=numero < max(0, int(longas)),
        )
        indice += 1
        escritos += 1
    return {
        "notas": escritos,
        "livros": n_livros,
        "videos": n_videos,
        "cursos": n_cursos,
        "cartoes": sum(plano),
        "pastas": {
            "livros": PASTA_LIVROS if n_livros else "",
            "videos": PASTA_VIDEOS if n_videos else "",
            "cursos": PASTA_CURSOS if n_cursos else "",
        },
    }


def _plano_cartoes(total, livros, videos, cursos, cartoes):
    pesos = []
    for indice in range(total):
        if indice < livros:
            pesos.append(8)
        elif indice < livros + videos:
            pesos.append(2)
        elif indice < livros + videos + cursos:
            pesos.append(3)
        else:
            pesos.append(1)
    soma = sum(pesos) or 1
    contagem = [int(cartoes * peso / soma) for peso in pesos]
    falta = cartoes - sum(contagem)
    cursor = 0
    while falta > 0:
        contagem[cursor % total] += 1
        falta -= 1
        cursor += 1
    return contagem


def _gravar(root, relativa, tipo, numero, cartoes, rng, longa):
    path = root / relativa
    path.parent.mkdir(parents=True, exist_ok=True)
    titulo = f"{tipo} sintetico {numero:04d}"
    linhas = [
        "---",
        f"tipo: {tipo}",
        "tags: [sintetico, escala]",
        "---",
        "",
        f"# {titulo}",
        "",
        _frase(rng, 18),
        "",
    ]
    if longa:
        for _ in range(80):
            linhas.append(_frase(rng, 24))
        linhas.append("")
    for ordem in range(cartoes):
        pergunta = f"Qual a marca {tipo} {numero:04d} item {ordem}?"
        resposta = rng.choice(PALAVRAS) + " " + str((numero + ordem) % 97)
        linhas.append(f"{pergunta} ::: {resposta}")
    linhas.append("")
    path.write_text("\n".join(linhas), encoding="utf-8", newline="\n")


def _frase(rng, tamanho):
    return " ".join(rng.choice(PALAVRAS) for _ in range(tamanho)) + "."
