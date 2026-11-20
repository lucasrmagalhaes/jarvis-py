"""Consulta somente leitura do vault.

A resposta cita trechos do clone local. Não grava nota, não chama o Claude
e não envia texto das notas a um provedor externo.
"""

import ipaddress
import math
import os
import re
import secrets
import socket
import sys
import threading
from pathlib import Path

from . import config
from .routines import (
    MAX_WALK,
    SEARCH_STOP,
    _read,
    _relative_note,
    _title,
    _without_frontmatter,
    fold,
    iter_notes,
    search_notes,
)

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
PROBE = "frase de aquecimento do modelo local"
VECTOR_MIN = 0.12
NEAR_MIN = 0.05
MODEL_HIGH = 0.72
MODEL_ACCEPT = 0.55
MODEL_MARGIN = 0.08
MAX_CHUNKS = 4000
LINK_RE = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]+)?(?:\|[^\[\]]+)?\]\]")

EXTRA_STOP = {
    "como",
    "foi",
    "sao",
    "ser",
    "esta",
    "este",
    "isso",
    "essa",
    "esse",
    "nao",
    "sim",
    "mais",
    "menos",
    "muito",
    "quando",
    "onde",
    "qual",
    "quais",
    "porque",
    "tambem",
    "entre",
    "ate",
    "ele",
    "ela",
    "eles",
    "elas",
    "voce",
    "seu",
    "sua",
    "seus",
    "suas",
    "meu",
    "minha",
    "tem",
    "ter",
    "notas",
    "nota",
    "escrevi",
    "anotei",
    "escreveu",
    "falei",
    "disse",
    "quero",
    "saber",
    "diz",
    "dizem",
    "fala",
    "falam",
    "registro",
    "registros",
    "vault",
    "jarvis",
}
_STOP = set(SEARCH_STOP) | EXTRA_STOP

_LIBRARIES = {}
_LIBRARIES_LOCK = threading.Lock()

HELP = """\
Uso:
  python -m jarvis.consult
  python -m jarvis.consult --baixar-modelo

Sobe a consulta somente leitura do vault para o Android.
Por padrão escuta só em 127.0.0.1. JARVIS_CONSULT_BIND aceita um IP privado ou lan.
A consulta funciona sem Claude. --baixar-modelo baixa só os pesos do modelo gratuito.
"""


class Chunk:
    def __init__(self, relative, title, heading, plain, links):
        self.relative = relative
        self.title = title
        self.heading = heading
        self.plain = plain
        self.links = links


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._stamp = None
        self._chunks = []
        self._weights = []
        self._idf = {}
        self._model_rows = None
        self._model_stamp = None
        self._model_id = None

    def rank_vector(self, query):
        with self._lock:
            self._ensure_unlocked()
            chunks = list(self._chunks)
            weights = list(self._weights)
            idf = dict(self._idf)
        words = content_words(query)
        query_weight = _weight(_features_from_words(words), idf)
        scored = [
            (_cosine(query_weight, weight), chunk)
            for chunk, weight in zip(chunks, weights)
        ]
        scored.sort(key=lambda item: (-item[0], item[1].relative))
        return scored

    def rank_model(self, query, embedder):
        with self._lock:
            self._ensure_unlocked()
            chunks = list(self._chunks)
            stamp = self._stamp
            cached = (
                self._model_rows
                if self._model_stamp == stamp and self._model_id == id(embedder)
                else None
            )
        if not chunks:
            return []
        rows = cached if cached is not None else _embed_all(
            embedder, [chunk.plain for chunk in chunks]
        )
        if not rows or len(rows) != len(chunks):
            return None
        if cached is None:
            with self._lock:
                if self._stamp == stamp:
                    self._model_rows = rows
                    self._model_stamp = stamp
                    self._model_id = id(embedder)
        try:
            query_rows = embedder.embed([query])
        except Exception:
            return None
        if not query_rows:
            return None
        scored = [
            (_dense_cosine(query_rows[0], row), chunk)
            for chunk, row in zip(chunks, rows)
        ]
        scored.sort(key=lambda item: (-item[0], item[1].relative))
        return scored

    def model_vectors(self, embedder):
        """Vetores já calculados dos trechos. None se o modelo não responder."""

        if embedder is None:
            return None
        with self._lock:
            self._ensure_unlocked()
            chunks = list(self._chunks)
            stamp = self._stamp
            cached = (
                self._model_rows
                if self._model_stamp == stamp and self._model_id == id(embedder)
                else None
            )
        if not chunks:
            return []
        rows = cached if cached is not None else _embed_all(
            embedder, [chunk.plain for chunk in chunks]
        )
        if not rows or len(rows) != len(chunks):
            return None
        if cached is None:
            with self._lock:
                if self._stamp == stamp:
                    self._model_rows = rows
                    self._model_stamp = stamp
                    self._model_id = id(embedder)
        paired = []
        for chunk, row in zip(chunks, rows):
            try:
                paired.append((chunk, [float(value) for value in list(row)]))
            except (TypeError, ValueError):
                return None
        return paired

    def chunks(self):
        with self._lock:
            self._ensure_unlocked()
            return list(self._chunks)

    def _ensure_unlocked(self):
        paths = _note_paths(self.root)
        current = _stamp(paths)
        if current == self._stamp:
            return
        chunks = _chunks_from(self.root, paths)
        feats = [_features(chunk.plain) for chunk in chunks]
        idf = _idf(feats)
        self._chunks = chunks
        self._idf = idf
        self._weights = [_weight(feat, idf) for feat in feats]
        self._stamp = current
        self._model_rows = None
        self._model_stamp = None
        self._model_id = None


class LocalModel:
    """Modelo já presente em disco. A consulta não dispara download."""

    def __init__(self, cache_dir, opener=None):
        self.cache_dir = Path(cache_dir)
        self._opener = opener or open_model
        self._model = None
        self._failed = False

    def embed(self, texts):
        if self._failed or not has_onnx(self.cache_dir):
            return None
        if self._model is None:
            previous = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"
            try:
                self._model = self._opener(self.cache_dir, True)
            except Exception:
                self._model = None
            finally:
                if previous is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = previous
            if self._model is None:
                self._failed = True
                return None
        try:
            rows = list(self._model.embed([str(text) for text in texts]))
        except Exception:
            self._failed = True
            return None
        vectors = []
        for row in rows:
            vectors.append([float(value) for value in list(row)])
        if len(vectors) != len(list(texts)):
            return None
        return vectors


def reset_libraries():
    with _LIBRARIES_LOCK:
        _LIBRARIES.clear()


def get_library(root):
    key = str(Path(root).resolve())
    with _LIBRARIES_LOCK:
        library = _LIBRARIES.get(key)
        if library is None:
            library = Library(key)
            _LIBRARIES[key] = library
            if len(_LIBRARIES) > 4:
                oldest = next(iter(_LIBRARIES))
                if oldest != key:
                    _LIBRARIES.pop(oldest, None)
        return library


def answer(root, query, embedder=None, vector_min=VECTOR_MIN):
    from .busca import in_scope, parse_scope

    cleaned = _clean_query(query)
    lexical, scope = parse_scope(cleaned)
    folder = Path(root)
    if not folder.is_dir():
        return _empty(cleaned, "A pasta do vault não está acessível.", [])
    words = content_words(lexical)
    if not words:
        return _empty(cleaned, "A consulta não tem termos para buscar no vault.", [])

    library = get_library(folder)
    vector_ranked = [
        (score, chunk)
        for score, chunk in library.rank_vector(lexical)
        if in_scope(chunk.relative, scope)
    ]
    need = _needed(words)
    accepted = [
        (score, chunk)
        for score, chunk in vector_ranked
        if score >= vector_min and _support(words, chunk.plain) >= need
    ]
    chunks = [chunk for chunk in library.chunks() if in_scope(chunk.relative, scope)]

    model_strong = []
    if embedder is not None:
        try:
            model_ranked = library.rank_model(lexical, embedder)
        except Exception:
            model_ranked = None
        if model_ranked:
            model_ranked = [
                (score, chunk)
                for score, chunk in model_ranked
                if in_scope(chunk.relative, scope)
            ]
        if model_ranked and _accept_model(model_ranked):
            model_strong = [
                (score, chunk)
                for score, chunk in model_ranked
                if score >= MODEL_ACCEPT
            ]

    bm25_ranked = _bm25_passages(chunks, words)
    use_vector = [] if model_strong else accepted
    lists = []
    labels = []
    if bm25_ranked:
        lists.append(bm25_ranked)
        labels.append("palavra")
    if use_vector:
        lists.append(use_vector)
        labels.append("vetorial")
    if model_strong:
        lists.append(model_strong)
        labels.append("modelo")
    if lists:
        fused = _fuse_chunks(lists)
        picked = _unique(fused, 3)
        if picked:
            return _pack(folder, cleaned, _mode_label(labels), picked, chunks)

    textual = _textual_pick(
        folder,
        [hit for hit in search_notes(folder, lexical) if in_scope(hit.relative, scope)],
        chunks,
    )
    if textual:
        return _pack(folder, cleaned, "textual", textual, chunks)

    nearby = []
    seen = set()
    for score, chunk in vector_ranked:
        if chunk.relative in seen:
            continue
        if _trecho_sigiloso(folder, chunk):
            continue
        if score < NEAR_MIN or _support(words, chunk.plain) <= 0:
            continue
        seen.add(chunk.relative)
        nearby.append(_source(folder, chunk, score))
        if len(nearby) >= 2:
            break
    if nearby:
        return _empty(
            cleaned,
            "Não há evidência suficiente no vault para responder. "
            "Os trechos próximos não sustentam a resposta.",
            nearby,
        )
    return _empty(cleaned, "Não há evidência no vault para essa consulta.", [])


def content_words(query):
    return [
        token
        for token in re.findall(r"[a-z0-9]{3,}", fold(query))
        if token not in _STOP
    ]


def has_onnx(cache_dir):
    root = Path(cache_dir)
    if not root.is_dir():
        return False
    try:
        return any(path.suffix == ".onnx" and path.is_file() for path in root.rglob("*"))
    except OSError:
        return False


def open_model(cache_dir, local_only, loader=None):
    loader = loader or _load_embedding_class
    embedding_cls = loader()
    if embedding_cls is None:
        return None
    kwargs = {"model_name": MODEL_NAME, "cache_dir": str(cache_dir)}
    if local_only:
        kwargs["local_files_only"] = True
    try:
        return embedding_cls(**kwargs)
    except TypeError:
        if local_only:
            return None
        return embedding_cls(model_name=MODEL_NAME, cache_dir=str(cache_dir))


def default_embedder():
    if not config.consult_model_enabled():
        return None
    cache = config.consult_model_dir()
    if not has_onnx(cache):
        return None
    return LocalModel(cache)


def download_model(cache_dir=None, opener=None):
    cache = Path(cache_dir) if cache_dir is not None else config.consult_model_dir()
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 1, "Não consegui preparar a pasta do modelo local."
    try:
        os.chmod(cache, 0o700)
    except OSError:
        pass
    if opener is None:
        if _load_embedding_class() is None:
            return (
                1,
                "Para o modelo gratuito, instale com: pip install -r requirements-consult.txt",
            )

        def opener(path, local_only):
            model = open_model(path, local_only)
            if model is None:
                raise RuntimeError("modelo")
            list(model.embed([PROBE]))
            return model

    try:
        opener(cache, False)
    except Exception:
        return (
            1,
            "Não consegui baixar o modelo local. A consulta segue na busca vetorial e na textual.",
        )
    return (
        0,
        "Modelo local gravado em "
        + str(cache)
        + ". O download traz só os pesos. As notas do vault não entram nele.",
    )


def resolve_bind(raw):
    text = (raw or "").strip().lower()
    if text in {"", "loopback", "local", "127.0.0.1"}:
        return "127.0.0.1"
    if text == "::1":
        return "::1"
    if text in {"lan", "localhost", "0.0.0.0", "::"}:
        return None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if ip.version == 4 and ip.is_loopback:
        return "127.0.0.1"
    if ip.version == 6 and ip.is_loopback:
        return "::1"
    if (
        ip.is_private
        and not ip.is_link_local
        and not ip.is_unspecified
        and not ip.is_multicast
        and not ip.is_reserved
    ):
        return str(ip)
    return None


def pick_lan_host():
    found = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        candidate = info[4][0]
        if _private_ipv4(candidate) and candidate not in found:
            found.append(candidate)
    routed = ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))
            routed = sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        routed = ""
    if _private_ipv4(routed):
        if routed in found:
            found.remove(routed)
        found.insert(0, routed)
    return found[0] if found else None


def banner(host, port, token):
    shown = "[" + host + "]" if ":" in host else host
    link = "http://" + shown + ":" + str(port) + "/entrar?t=" + token
    lines = [
        "Consulta somente leitura do vault.",
        "A página não grava notas, não chama o Claude e não envia as notas para fora.",
        "O token muda quando este processo reinicia e não fica gravado na página.",
    ]
    if host in {"127.0.0.1", "::1"}:
        lines.append(
            "Escuta só em " + shown + ":" + str(port) + ". Nada é publicado na internet."
        )
        lines.append(
            "No Android, com cabo: adb reverse tcp:" + str(port) + " tcp:" + str(port)
        )
        lines.append("Depois abra o link abaixo no Chrome do telefone.")
    else:
        lines.append(
            "Escuta no IP privado "
            + shown
            + ":"
            + str(port)
            + ", para a mesma rede Wi-Fi."
        )
        lines.append("Não encaminhe essa porta no roteador e não use rede pública.")
    lines.append(link)
    lines.append("Ctrl+C encerra.")
    return "\n".join(lines)


def main(argv=None):
    from .consult_http import serve

    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(HELP)
        return 0
    if any(item.startswith("-") and item != "--baixar-modelo" for item in args):
        print(HELP)
        return 2
    if "--baixar-modelo" in args:
        code, message = download_model()
        print(message)
        return code
    root = config.vault_dir()
    if root is None or not Path(root).is_dir():
        print("Defina JARVIS_VAULT com a pasta do clone. Sem essa pasta eu não leio as notas.")
        return 1
    requested = config.consult_bind()
    if requested.strip().lower() == "lan":
        host = pick_lan_host()
    else:
        host = resolve_bind(requested)
    if not host:
        print(
            "JARVIS_CONSULT_BIND recusado. Use 127.0.0.1, um IP privado ou lan. "
            "O serviço não foi aberto."
        )
        return 1
    port = config.consult_port()
    token = secrets.token_urlsafe(24)
    try:
        server = serve(root, token, host, port, embedder=default_embedder())
    except OSError:
        print("A porta " + str(port) + " não abriu em " + host + ".")
        return 1
    print(banner(host, port, token))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        server.server_close()
    return 0


def _load_embedding_class():
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None
    return TextEmbedding


def _note_paths(root):
    paths = []
    for path in iter_notes(root):
        paths.append(path)
        if len(paths) >= MAX_WALK:
            break
    return paths


def _stamp(paths):
    items = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(items)


def _chunks_from(root, paths):
    chunks = []
    root = Path(root)
    for path in paths:
        relative = _relative_note(root, path)
        if not _safe_relative(relative):
            continue
        raw = _read(path)
        title = safe_text(_title(path, raw), 160) or Path(relative).stem
        for heading, plain, section in _sections(_without_frontmatter(raw)):
            chunks.append(Chunk(relative, title, heading, plain, _links(section)))
            if len(chunks) >= MAX_CHUNKS:
                return chunks
    return chunks


def _sections(body):
    sections = []
    heading = ""
    buffer = []
    for line in (body or "").splitlines():
        if line.startswith("#"):
            if buffer:
                sections.append((heading, "\n".join(buffer)))
            heading = safe_text(line, 120)
            buffer = [line]
        else:
            buffer.append(line)
    if buffer:
        sections.append((heading, "\n".join(buffer)))
    windows = []
    for heading, section in sections:
        plain = safe_text(section, 4000)
        if len(plain) <= 40:
            continue
        if len(plain) <= 700:
            windows.append((heading, plain, section))
            continue
        bucket = []
        size = 0
        for line in section.splitlines():
            bucket.append(line)
            size += len(line) + 1
            if size >= 600:
                _store_window(windows, heading, bucket)
                bucket = []
                size = 0
        if bucket:
            _store_window(windows, heading, bucket)
    return windows


def _store_window(windows, heading, bucket):
    text = "\n".join(bucket)
    shown = safe_text(text, 700)
    if len(shown) > 40:
        windows.append((heading, shown, text))


def _links(raw):
    found = []
    for match in LINK_RE.finditer(raw or ""):
        target = " ".join(match.group(1).split())
        if not target or ".." in target or target.startswith("."):
            continue
        if len(target) > 180 or target in found:
            continue
        found.append(target)
        if len(found) >= 12:
            break
    return found


def _features(text):
    words = [
        token
        for token in re.findall(r"[a-z0-9]{3,}", fold(text))
        if token not in _STOP
    ]
    return _features_from_words(words)


def _features_from_words(words):
    counts = {}
    for word in words:
        key = "w:" + word
        counts[key] = counts.get(key, 0) + 1
        if len(word) < 4:
            continue
        for gram in _grams(word):
            gkey = "c:" + gram
            counts[gkey] = counts.get(gkey, 0) + 1
    return counts


def _grams(word):
    padded = "<" + word + ">"
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def _idf(docs):
    df = {}
    total = len(docs)
    for feats in docs:
        for key in feats:
            df[key] = df.get(key, 0) + 1
    return {
        key: math.log((total + 1) / (freq + 1)) + 1.0 for key, freq in df.items()
    }


def _weight(counts, idf):
    weights = {}
    for key, tf in counts.items():
        factor = idf.get(key)
        if not factor:
            continue
        weights[key] = (1.0 + math.log(tf)) * factor
    return weights


def _cosine(left, right):
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = 0.0
    for key, value in left.items():
        other = right.get(key)
        if other:
            dot += value * other
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _dense_cosine(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for one, other in zip(left, right):
        dot += one * other
        left_norm += one * one
        right_norm += other * other
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


def _needed(words):
    count = len(words)
    if count <= 2:
        return count
    return max(2, int(round(count * 0.67)))


def _support(words, text):
    return sum(1 for word in words if _word_hit(word, text))


def _word_hit(word, text):
    tokens = re.findall(r"[a-z0-9]{3,}", fold(text))
    if word in tokens:
        return True
    if len(word) < 5:
        return False
    for token in tokens:
        if len(token) < 4:
            continue
        limit = min(len(word), len(token))
        prefix = 0
        while prefix < limit and word[prefix] == token[prefix]:
            prefix += 1
        longest = max(len(word), len(token))
        if prefix >= 5 and prefix / longest >= 0.6:
            return True
    return False


def _accept_model(ranked):
    best = ranked[0][0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    if best >= MODEL_HIGH:
        return True
    return best >= MODEL_ACCEPT and best - second >= MODEL_MARGIN


def _unique(ranked, limit):
    picked = []
    seen = set()
    for score, chunk in ranked:
        if chunk.relative in seen:
            continue
        seen.add(chunk.relative)
        picked.append((score, chunk))
        if len(picked) >= limit:
            break
    return picked


def _bm25_passages(chunks, words):
    from .busca import bm25_ranking, exact_support, line_bonus, needed_count

    if not chunks or not words:
        return []
    need = needed_count(len(words))
    kept = []
    docs = []
    for chunk in chunks:
        blob = (chunk.title or "") + "\n" + (chunk.plain or "")
        if exact_support(words, blob) < need:
            continue
        kept.append(chunk)
        docs.append(blob)
    if not kept:
        return []
    scores = bm25_ranking(docs, words)
    ranked = []
    for chunk, score, blob in zip(kept, scores, docs):
        total = score + line_bonus(blob, words)
        if total <= 0:
            continue
        ranked.append((total, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1].relative, item[1].heading))
    return ranked


def _fuse_chunks(lists):
    from .busca import fuse_rrf

    sequences = [[chunk for _score, chunk in ranking] for ranking in lists]
    fused = fuse_rrf(
        sequences,
        key=lambda chunk: (chunk.relative, chunk.heading, chunk.plain[:80]),
    )
    return [(score, chunk) for score, chunk in fused]


def _mode_label(labels):
    if labels == ["modelo"]:
        return "modelo"
    if labels == ["vetorial"]:
        return "vetorial"
    if labels == ["palavra"]:
        return "palavra"
    if len(labels) > 1:
        return "hibrida"
    return labels[0] if labels else "palavra"


def _textual_pick(root, hits, chunks):
    by_path = {}
    for chunk in chunks:
        by_path.setdefault(chunk.relative, chunk)
    picked = []
    seen = set()
    for hit in hits:
        relative = hit.relative or ""
        if relative in seen or not _safe_relative(relative):
            continue
        if not _path_inside(root, hit.path):
            continue
        seen.add(relative)
        chunk = by_path.get(relative)
        if chunk is None:
            chunk = Chunk(
                relative,
                safe_text(hit.title, 160) or relative,
                "",
                safe_text(hit.snippet, 280),
                [],
            )
        picked.append((1.0, chunk))
        if len(picked) >= 3:
            break
    return picked


def _path_inside(root, path):
    from .paths import esta_dentro

    return esta_dentro(path, root, oserror=True)


def _safe_relative(relative):
    from .paths import relativo_consulta

    return relativo_consulta(relative)


def _trecho_sigiloso(root, chunk):
    try:
        from .privacidade import nota_sigilosa
    except Exception:
        return False
    relative = getattr(chunk, "relative", "") or ""
    if not relative:
        return False
    plain = getattr(chunk, "plain", None)
    path = Path(root) / relative
    if nota_sigilosa(root, path, plain):
        return True
    if path.is_file():
        return nota_sigilosa(root, path, None)
    return False


def _sem_sigilo(root, picked):
    kept = []
    for item in picked or []:
        chunk = item[1] if isinstance(item, tuple) and len(item) > 1 else item
        if _trecho_sigiloso(root, chunk):
            continue
        kept.append(item)
    return kept


def _pack(root, query, mode, picked, chunks):
    picked = _sem_sigilo(root, picked)
    chunks = _sem_sigilo(root, [(0, chunk) for chunk in chunks])
    chunks = [item[1] for item in chunks]
    if not picked:
        return _empty(query, "Não há evidência no vault para essa consulta.", [])
    sources = [_source(root, chunk, score) for score, chunk in picked]
    return {
        "query": query,
        "evidence": True,
        "read_only": True,
        "persisted": False,
        "mode": mode,
        "answer": _evidence_text(sources),
        "sources": sources,
        "nearby": [],
        "suggestions": _suggestions(chunks, sources),
    }


def _empty(query, text, nearby):
    return {
        "query": query,
        "evidence": False,
        "read_only": True,
        "persisted": False,
        "mode": "nenhuma",
        "answer": text,
        "sources": [],
        "nearby": nearby,
        "suggestions": {"persisted": False, "flashcards": [], "connections": []},
    }


def _evidence_text(sources):
    bits = [
        "A resposta usa só os trechos abaixo. O que não aparece neles fica sem evidência."
    ]
    for source in sources:
        bits.append(
            "Na nota "
            + source["title"]
            + ", caminho "
            + source["path"]
            + ": "
            + source["excerpt"]
        )
    return " ".join(bits)


def _source(root, chunk, score):
    return {
        "title": chunk.title,
        "path": chunk.relative,
        "heading": chunk.heading,
        "excerpt": chunk.plain[:280],
        "wikilink": _wikilink(chunk.relative),
        "obsidian": _obsidian(root, chunk.relative),
        "score": round(float(score), 4),
    }


def _suggestions(chunks, sources):
    cards = []
    for source in sources:
        front = source["heading"] or ("O que a nota registra: " + source["title"])
        cards.append(
            {
                "front": front[:160],
                "back": source["excerpt"],
                "path": source["path"],
                "persisted": False,
            }
        )
        if len(cards) >= 3:
            break
    return {
        "persisted": False,
        "flashcards": cards,
        "connections": _connections(chunks, sources),
    }


def _connections(chunks, sources):
    index = {}
    by_path = {}
    for chunk in chunks:
        relative = chunk.relative
        stem = relative[:-3] if relative.lower().endswith(".md") else relative
        index.setdefault(fold(stem), relative)
        index.setdefault(fold(Path(stem).name), relative)
        if chunk.title:
            index.setdefault(fold(chunk.title), relative)
        by_path.setdefault(relative, []).extend(chunk.links)
    found = []
    seen = set()
    for source in sources:
        for target in by_path.get(source["path"], []):
            resolved = index.get(fold(target))
            if not resolved or resolved == source["path"]:
                continue
            key = (source["path"], resolved)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "origin": source["path"],
                    "target": resolved,
                    "wikilink": "[[" + target + "]]",
                    "reason": "link já existente na nota",
                    "persisted": False,
                }
            )
    paths = []
    for source in sources:
        if source["path"] not in paths:
            paths.append(source["path"])
    if len(paths) >= 2 and (paths[0], paths[1]) not in seen:
        found.append(
            {
                "origin": paths[0],
                "target": paths[1],
                "wikilink": "",
                "reason": "apareceram juntas nesta consulta",
                "persisted": False,
            }
        )
    return found[:8]


def _wikilink(relative):
    stem = relative[:-3] if relative.lower().endswith(".md") else relative
    return "[[" + stem + "]]"


def _obsidian(root, relative):
    from urllib.parse import quote

    vault = Path(root).name or "vault"
    file_name = relative[:-3] if relative.lower().endswith(".md") else relative
    return (
        "obsidian://open?vault="
        + quote(vault, safe="")
        + "&file="
        + quote(file_name, safe="/")
    )


def _clean_query(query):
    text = str(query or "").replace("\u2014", " ").replace("\u2013", " ")
    return " ".join(text.split())[:500]


def safe_text(text, limit):
    from .routines import _plain

    cleaned = _plain(text).replace("<", " ").replace(">", " ")
    cleaned = "".join(char for char in cleaned if char.isprintable())
    return " ".join(cleaned.split())[:limit]


def _private_ipv4(text):
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return (
        ip.version == 4
        and ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_unspecified
        and not ip.is_multicast
        and not ip.is_reserved
    )


def _embed_all(embedder, texts):
    rows = []
    for start in range(0, len(texts), 32):
        batch = texts[start : start + 32]
        try:
            part = embedder.embed(batch)
        except Exception:
            return None
        if not part or len(part) != len(batch):
            return None
        rows.extend(part)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
