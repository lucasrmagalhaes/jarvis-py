"""Índice de embeddings que só recalcula a nota cujo mtime ou hash mudou.

O arquivo em ~/.jarvis guarda mtime, tamanho, hash e vetor.
O texto da nota não entra nesse arquivo.
"""

import hashlib
import json
import threading
import time
from pathlib import Path

_MEMORY = {}
_LOTE = 32
_LOCK = threading.RLock()


def _embed_em_lotes(embedder, texts):
    vectors = []
    for start in range(0, len(texts), _LOTE):
        chunk = texts[start : start + _LOTE]
        rows = list(embedder.embed(chunk) or [])
        if len(rows) != len(chunk):
            return None
        vectors.extend(_vector(row) for row in rows)
    return vectors


def cache_file(root, embedder):
    from . import config

    kind = type(embedder).__name__
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    return config.jarvis_home() / "indices" / f"{kind}-{digest}.json"


def _hash_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _vector(row):
    return [float(value) for value in list(row)]


def _clean_entry(value):
    if not isinstance(value, dict):
        return None
    if any(key in value for key in ("texto", "text", "body", "conteudo", "plain")):
        return None
    vector = value.get("vetor")
    if not isinstance(vector, list) or not vector:
        return None
    try:
        numbers = _vector(vector)
    except (TypeError, ValueError):
        return None
    return {
        "mtime_ns": value.get("mtime_ns"),
        "tamanho": value.get("tamanho"),
        "sha256": str(value.get("sha256") or ""),
        "vetor": numbers,
    }


def load_store(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    notes = data.get("notas") if isinstance(data, dict) else None
    cleaned = {}
    if isinstance(notes, dict):
        for key, value in notes.items():
            entry = _clean_entry(value)
            if entry is not None:
                cleaned[str(key).replace("\\", "/")] = entry
    return cleaned


def save_store(path, entries):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    safe = {}
    for key, value in entries.items():
        entry = _clean_entry(value)
        if entry is not None:
            safe[str(key).replace("\\", "/")] = entry
    raw = json.dumps({"versao": 1, "notas": safe}, ensure_ascii=True).encode("utf-8")
    from .trava import gravar_atomico, trava_arquivo

    with trava_arquivo(target.with_name(target.name + ".lock"), espera=60):
        gravar_atomico(target, raw, mode=0o600)


class NoteIndex:
    def __init__(self, root, embedder, store):
        self.root = Path(root)
        self.embedder = embedder
        self.store = Path(store)
        self.entries = load_store(self.store)

    def sync(self, progresso=None):
        """Recalcula só o arquivo novo ou alterado. Devolve os caminhos refeitos."""
        from .catalogo import obter
        from .trava import trava_arquivo

        with _LOCK:
            return self._sync(progresso, obter, trava_arquivo)

    def _sync(self, progresso, obter, trava_arquivo):
        with trava_arquivo(self.store.with_name(self.store.name + ".lock"), espera=120):
            self.entries = load_store(self.store)
            return self._recalcular(progresso, obter)

    def _recalcular(self, progresso, obter):
        catalogo = obter(self.root, progresso=progresso)
        seen = set()
        pending = []
        for relative, nota in catalogo.notas.items():
            if not nota.util or nota.texto is None:
                continue
            seen.add(relative)
            previous = self.entries.get(relative)
            if (
                previous
                and previous.get("mtime_ns") == nota.mtime_ns
                and previous.get("tamanho") == nota.tamanho
                and previous.get("sha256") == nota.sha256
                and previous.get("vetor")
            ):
                continue
            if previous and previous.get("sha256") == nota.sha256 and previous.get("vetor"):
                previous["mtime_ns"] = nota.mtime_ns
                previous["tamanho"] = nota.tamanho
                continue
            pending.append(nota)
        if pending:
            try:
                vectors = _embed_em_lotes(self.embedder, [nota.texto for nota in pending])
            except Exception:
                return []
            if not vectors or len(vectors) != len(pending):
                return []
            for nota, vector in zip(pending, vectors):
                self.entries[nota.relative] = {
                    "mtime_ns": nota.mtime_ns,
                    "tamanho": nota.tamanho,
                    "sha256": nota.sha256,
                    "vetor": vector,
                }
        for key in list(self.entries):
            if key not in seen:
                del self.entries[key]
        save_store(self.store, self.entries)
        return [nota.relative for nota in pending]


def vectors_for(records, embedder, store=None):
    """Vetores na ordem dos registros. None se o modelo falhar."""
    if not records:
        return []
    with _LOCK:
        return _vectors_for(records, embedder, store)


def _vectors_for(records, embedder, store=None):
    if store is None:
        bucket = _MEMORY.setdefault(id(embedder), {})
    else:
        bucket = load_store(store)
    pending = []
    for record in records:
        relative = str(record.get("relative") or "").replace("\\", "/")
        text = record.get("texto") or ""
        digest = _hash_text(text)
        mtime = record.get("mtime_ns")
        size = record.get("tamanho")
        previous = bucket.get(relative)
        if (
            previous
            and previous.get("sha256") == digest
            and previous.get("vetor")
            and previous.get("mtime_ns") == mtime
            and previous.get("tamanho") == size
        ):
            continue
        if previous and previous.get("sha256") == digest and previous.get("vetor"):
            previous["mtime_ns"] = mtime
            previous["tamanho"] = size
            continue
        pending.append((relative, digest, mtime, size, text))
    if pending:
        try:
            vectors = _embed_em_lotes(embedder, [item[4] for item in pending])
        except Exception:
            return None
        if not vectors or len(vectors) != len(pending):
            return None
        for item, vector in zip(pending, vectors):
            relative, digest, mtime, size, _text = item
            bucket[relative] = {
                "mtime_ns": mtime,
                "tamanho": size,
                "sha256": digest,
                "vetor": vector,
            }
    if store is not None:
        save_store(store, bucket)
    vectors = []
    for record in records:
        relative = str(record.get("relative") or "").replace("\\", "/")
        entry = bucket.get(relative)
        if not entry or not entry.get("vetor"):
            return None
        vectors.append(entry["vetor"])
    return vectors


def warm_index(root, embedder=None):
    if embedder is None:
        from .consult import default_embedder

        embedder = default_embedder()
    if embedder is None:
        return None
    index = NoteIndex(root, embedder, cache_file(root, embedder))
    started = time.perf_counter()
    changed = index.sync()
    return {
        "refeitas": len(changed),
        "total": len(index.entries),
        "segundos": time.perf_counter() - started,
    }


def medir_arranque(pasta, store, notas=24, pausa=0.004):
    """Mede o arranque do índice em notas sintéticas. Não devolve o texto."""
    root = Path(pasta)
    root.mkdir(parents=True, exist_ok=True)
    for number in range(notas):
        path = root / f"nota-{number}.md"
        path.write_text(
            f"# Nota {number}\n\nTexto sintetico {number} do indice.\n",
            encoding="utf-8",
            newline="\n",
        )

    class Modelo:
        def __init__(self):
            self.lotes = []

        def embed(self, texts):
            self.lotes.append(len(texts))
            time.sleep(pausa * max(1, len(texts)))
            return [[1.0, float(len(text) % 5)] for text in texts]

    def _rodar(modelo):
        index = NoteIndex(root, modelo, store)
        started = time.perf_counter()
        changed = index.sync()
        return changed, time.perf_counter() - started, modelo.lotes

    frio, frio_s, _lotes = _rodar(Modelo())
    morno, morno_s, lotes_morno = _rodar(Modelo())
    alvo = root / "nota-0.md"
    alvo.write_text(
        "# Nota 0\n\nTexto sintetico 0 alterado no indice.\n",
        encoding="utf-8",
        newline="\n",
    )
    um, um_s, lotes_um = _rodar(Modelo())
    return {
        "notas": notas,
        "frio_s": frio_s,
        "morno_s": morno_s,
        "um_s": um_s,
        "refeitas_frio": len(frio),
        "refeitas_morno": list(morno),
        "refeitas_um": list(um),
        "lotes_morno": list(lotes_morno),
        "lotes_um": list(lotes_um),
    }
