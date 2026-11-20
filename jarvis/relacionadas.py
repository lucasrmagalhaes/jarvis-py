"""Notas parecidas pelo índice de embeddings já existente.

A resposta leva só título e caminho. O texto da nota não sai daqui.
"""

from pathlib import Path

from .busca import dense_cosine
from .consult import get_library
from .routines import fold


def related_notes(root, query, embedder=None, limit=5):
    from .semantica import embedder_da_busca, ligada, notas_parecidas

    if ligada():
        modelo = embedder if embedder is not None else embedder_da_busca()
        if modelo is None:
            return []
        achadas = notas_parecidas(root, query, modelo, limit=limit)
        return achadas or []
    library = get_library(root)
    chunks = library.chunks()
    if not chunks:
        return []
    anchor = _anchor(chunks, query)
    if embedder is not None:
        paired = library.model_vectors(embedder)
        if paired:
            notes = _from_vectors(paired, query, anchor, embedder, limit)
            if notes:
                return notes
    return _from_sparse(library, query, anchor, limit)


def related_speech(root, query, embedder=None):
    from .semantica import embedder_da_busca, ligada, mensagem_dependencia, mensagem_falha

    theme = " ".join((query or "").split())
    if not theme:
        return "Sobre qual nota ou tema, senhor?"
    if ligada():
        modelo = embedder if embedder is not None else embedder_da_busca()
        if modelo is None:
            return mensagem_dependencia()
        try:
            from .semantica import notas_parecidas

            notes = notas_parecidas(root, theme, modelo, limit=5)
        except Exception:
            return "Não encontrei nota relacionada, senhor."
        if notes is None:
            return mensagem_falha(modelo)
        if not notes:
            return "Não encontrei nota relacionada, senhor."
        bits = [f"{item['titulo']}, caminho {item['caminho']}" for item in notes]
        return "Notas relacionadas, senhor. " + ". ".join(bits) + "."
    try:
        notes = related_notes(root, theme, embedder=embedder, limit=5)
    except Exception:
        notes = []
    if not notes:
        return "Não encontrei nota relacionada, senhor."
    bits = [f"{item['titulo']}, caminho {item['caminho']}" for item in notes]
    return "Notas relacionadas, senhor. " + ". ".join(bits) + "."


def _from_vectors(paired, query, anchor, embedder, limit):
    grouped = {}
    for chunk, vector in paired:
        bucket = grouped.setdefault(chunk.relative, {"titulo": chunk.title, "vetores": []})
        if chunk.title:
            bucket["titulo"] = chunk.title
        bucket["vetores"].append(vector)
    centroids = {}
    for relative, bucket in grouped.items():
        center = _centroid(bucket["vetores"])
        if center is not None:
            centroids[relative] = (center, bucket["titulo"] or Path(relative).stem)
    if not centroids:
        return []
    if anchor and anchor in centroids:
        query_vector = centroids[anchor][0]
    else:
        try:
            rows = embedder.embed([query])
        except Exception:
            return []
        if not rows:
            return []
        query_vector = [float(value) for value in list(rows[0])]
    ranked = []
    for relative, (vector, title) in centroids.items():
        if relative == anchor:
            continue
        score = dense_cosine(query_vector, vector)
        if score <= 0:
            continue
        ranked.append((score, title, relative))
    ranked.sort(key=lambda item: (-item[0], item[2]))
    return [_public(title, relative) for _score, title, relative in ranked[:limit]]


def _from_sparse(library, query, anchor, limit):
    try:
        scored = library.rank_vector(query)
    except Exception:
        return []
    best = {}
    for score, chunk in scored:
        if chunk.relative == anchor or score <= 0:
            continue
        current = best.get(chunk.relative)
        title = chunk.title or Path(chunk.relative).stem
        if current is None or score > current[0]:
            best[chunk.relative] = (score, title, chunk.relative)
    ranked = sorted(best.values(), key=lambda item: (-item[0], item[2]))
    return [_public(title, relative) for _score, title, relative in ranked[:limit]]


def _public(title, relative):
    return {
        "titulo": " ".join(str(title or Path(relative).stem).split())[:160],
        "caminho": str(relative).replace("\\", "/"),
    }


def _anchor(chunks, query):
    folded = fold(query or "")
    if not folded:
        return ""
    for chunk in chunks:
        relative = chunk.relative
        stem = relative[:-3] if relative.lower().endswith(".md") else relative
        names = {
            fold(chunk.title or ""),
            fold(stem),
            fold(Path(stem).name),
            fold(relative),
        }
        if folded in names:
            return relative
    return ""


def _centroid(vectors):
    if not vectors:
        return None
    width = len(vectors[0])
    if width == 0:
        return None
    total = [0.0] * width
    for vector in vectors:
        if len(vector) != width:
            return None
        for index, value in enumerate(vector):
            total[index] += value
    count = float(len(vectors))
    return [value / count for value in total]
