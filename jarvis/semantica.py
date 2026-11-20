"""Índice semântico local, partido por título.

Os embeddings saem só desta máquina: sentence-transformers, ou o Ollama
quando JARVIS_CEREBRO=ollama. O arquivo fica em ~/.jarvis e guarda
mtime, tamanho, hash e vetor. O texto da nota não entra nele e não é enviado.
Nota com #sigiloso, inclusive com BOM ou quebra do Windows, e pasta privada
ficam de fora. O padrão JARVIS_BUSCA=palavras não usa este índice.
"""

import hashlib
import json
import re
import threading
from pathlib import Path

_LOCK = threading.RLock()
_MODELO_ST = None
_LOTE = 16
_TETO = 8000
_PISO = 0.35
MODELO_NOME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_PROIBIDO = {"texto", "text", "body", "conteudo", "plain", "heading", "titulo"}


def modo():
    from .ajustes import busca_modo

    return busca_modo()


def ligada():
    return modo() in {"semantica", "hibrida"}


def mensagem_dependencia():
    from . import config

    if config.cerebro_raw() == "ollama":
        return (
            "A busca semântica pelo Ollama não está disponível, senhor. "
            "Confira se ele está no ar nesta máquina."
        )
    return (
        "A busca semântica precisa do pacote sentence-transformers nesta máquina, senhor. "
        "Sem ele eu busco só por palavra."
    )


def mensagem_falha(embedder):
    if isinstance(embedder, OllamaEmbedder):
        return (
            "A busca semântica pelo Ollama não respondeu, senhor. "
            "Confira se ele está no ar nesta máquina."
        )
    return mensagem_dependencia()


def _sentence_ok():
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def embedder_da_busca(transport=None):
    """Modelo local, ou None se o pacote não está nesta máquina."""

    from . import config

    if config.cerebro_raw() == "ollama":
        return OllamaEmbedder(transport=transport)
    if not _sentence_ok():
        return None
    return SentenceEmbedder()


class SentenceEmbedder:
    """Modelo pequeno e multilíngue. Só carrega na hora de calcular."""

    def embed(self, texts):
        if not texts:
            return []
        if not _sentence_ok():
            return None
        model = _modelo_st()
        if model is None:
            return None
        try:
            rows = model.encode(
                [str(text) for text in texts],
                batch_size=_LOTE,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
        except Exception:
            return None
        vectors = [_vetor(row) for row in rows]
        if any(item is None for item in vectors) or len(vectors) != len(list(texts)):
            return None
        return vectors


class OllamaEmbedder:
    """Embeddings do Ollama em 127.0.0.1. O texto não vai para a nuvem."""

    def __init__(self, transport=None, model=None):
        self.transport = transport
        self.model = model

    def embed(self, texts):
        if not texts:
            return []
        from . import config
        from .cerebro import default_transport, ollama_base, ollama_model

        base = ollama_base()
        if not base:
            return None
        call = self.transport or default_transport
        payload = {
            "model": self.model or ollama_model(),
            "input": [str(text) for text in texts],
        }
        try:
            body = call("POST", base + "/api/embed", payload, config.ollama_timeout())
        except Exception:
            return None
        rows = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(rows, list) or len(rows) != len(list(texts)):
            return None
        vectors = [_vetor(row) for row in rows]
        if any(item is None for item in vectors):
            return None
        return vectors


def _modelo_st():
    global _MODELO_ST
    if _MODELO_ST is not None:
        return _MODELO_ST
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    from . import config

    pasta = config.jarvis_home() / "modelos"
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        _MODELO_ST = SentenceTransformer(MODELO_NOME, cache_folder=str(pasta))
    except Exception:
        _MODELO_ST = None
    return _MODELO_ST


def _vetor(row):
    try:
        values = [float(value) for value in list(row)]
    except (TypeError, ValueError):
        return None
    if not values:
        return None
    return values


def _modelo_id(embedder):
    nome = type(embedder).__name__
    if isinstance(embedder, SentenceEmbedder):
        nome = "st-" + MODELO_NOME.rsplit("/", 1)[-1]
    elif isinstance(embedder, OllamaEmbedder) and embedder.model:
        nome = "ollama-" + str(embedder.model)
    elif isinstance(embedder, OllamaEmbedder):
        from . import config

        nome = "ollama-" + config.ollama_model()
    limpo = re.sub(r"[^A-Za-z0-9._-]", "-", nome)[:48]
    return limpo or "modelo"


def caminho_indice(root, embedder):
    from . import config

    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    base = _base_fora_do_vault(config.jarvis_home(), root)
    return base / "indices" / ("semantica-" + _modelo_id(embedder) + "-" + digest + ".json")


def _base_fora_do_vault(base, root):
    if not _dentro(base, root):
        return Path(base)
    casa = Path.home() / ".jarvis"
    if not _dentro(casa, root):
        return casa
    return Path(base)


def _dentro(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False
    return True


def fatiar(texto):
    """Parte a nota por título. Trecho curto demais fica de fora."""

    from .routines import _without_frontmatter

    body = texto or ""
    if body.startswith("\ufeff"):
        body = body[1:]
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = _without_frontmatter(body)
    heading = ""
    buffer = []
    partes = []

    def flush():
        plain = "\n".join(buffer).strip()
        if len(plain) >= 12:
            partes.append((heading, plain[:700]))

    for line in body.split("\n"):
        if line.startswith("#"):
            flush()
            heading = " ".join(line.lstrip("#").split())[:120]
            buffer = []
            continue
        buffer.append(line)
        if sum(len(item) + 1 for item in buffer) >= 600:
            flush()
            buffer = []
    flush()
    if not partes:
        corpo = body.strip()
        if len(corpo) >= 12:
            partes.append(("", corpo[:700]))
    return partes[:12]


def _texto_do_trecho(heading, plain):
    if heading:
        return heading + "\n" + plain
    return plain


class Trecho:
    def __init__(self, caminho, titulo, heading, texto, vetor, score=0.0):
        self.caminho = caminho
        self.titulo = titulo
        self.heading = heading
        self.texto = texto
        self.vetor = vetor
        self.score = score


class IndiceSemantico:
    def __init__(self, root, embedder, store=None):
        self.root = Path(root)
        self.embedder = embedder
        self.store = Path(store) if store is not None else caminho_indice(self.root, embedder)
        self.entries = {}
        self.modelo = _modelo_id(embedder)

    def sincronizar(self):
        """Recalcula só a nota nova ou alterada. None se o modelo falhar."""

        with _LOCK:
            from .trava import trava_arquivo

            self.store.parent.mkdir(parents=True, exist_ok=True)
            with trava_arquivo(self.store.with_name(self.store.name + ".lock"), espera=120):
                self.entries = _carregar(self.store, self.modelo)
                return self._recalcular()

    def _recalcular(self):
        from .catalogo import obter
        from .log import LOG

        try:
            catalogo = obter(self.root)
        except Exception:
            return None
        seen = set()
        pending = []
        total = sum(len(item.get("trechos") or []) for item in self.entries.values())
        for nota in catalogo.notas.values():
            if not _publica(self.root, nota):
                continue
            relative = str(nota.relative).replace("\\", "/")
            fatias = fatiar(nota.texto)
            if not fatias:
                continue
            if total + len(fatias) > _TETO and relative not in self.entries:
                continue
            seen.add(relative)
            previous = self.entries.get(relative)
            vetores = (previous or {}).get("trechos") or []
            if (
                previous
                and previous.get("mtime_ns") == nota.mtime_ns
                and previous.get("tamanho") == nota.tamanho
                and previous.get("sha256") == nota.sha256
                and len(vetores) == len(fatias)
            ):
                continue
            if (
                previous
                and previous.get("sha256") == nota.sha256
                and len(vetores) == len(fatias)
            ):
                previous["mtime_ns"] = nota.mtime_ns
                previous["tamanho"] = nota.tamanho
                continue
            for indice, (heading, plain) in enumerate(fatias):
                pending.append((relative, indice, _texto_do_trecho(heading, plain), nota))
            total += len(fatias)
        if pending:
            try:
                vectors = _em_lotes(self.embedder, [item[2] for item in pending])
            except Exception:
                return None
            if not vectors or len(vectors) != len(pending):
                return None
            grouped = {}
            for item, vector in zip(pending, vectors):
                relative, _indice, _texto, nota = item
                bucket = grouped.setdefault(
                    relative,
                    {
                        "mtime_ns": nota.mtime_ns,
                        "tamanho": nota.tamanho,
                        "sha256": nota.sha256,
                        "trechos": [],
                    },
                )
                bucket["trechos"].append(vector)
            for relative, entry in grouped.items():
                nota_atual = catalogo.notas.get(relative)
                if not _ainda_publica(self.root, relative, nota_atual):
                    self.entries.pop(relative, None)
                    continue
                self.entries[relative] = entry
        for key in list(self.entries):
            if key not in seen:
                del self.entries[key]
        _gravar(self.store, self.entries, self.modelo)
        refeitas = list(dict.fromkeys(item[0] for item in pending))
        LOG.info("indice semantico refeitas=%s", len(refeitas))
        return refeitas


def _em_lotes(embedder, texts):
    vectors = []
    for start in range(0, len(texts), _LOTE):
        chunk = texts[start : start + _LOTE]
        rows = embedder.embed(chunk)
        if not rows or len(rows) != len(chunk):
            return None
        converted = [_vetor(row) for row in rows]
        if any(item is None for item in converted):
            return None
        vectors.extend(converted)
    return vectors


def _ainda_publica(root, relative, nota):
    """Relê o arquivo. Uma nota que ganhou #sigiloso durante o embedding fica de fora."""
    if not _publica(root, nota):
        return False
    from .leitura import ler_texto
    from .paths import caminho_relativo
    from .privacidade import nota_sigilosa

    seguro = caminho_relativo(str(relative or "").replace("\\", "/"), exigir_md=True)
    if not seguro:
        return False
    arquivo = Path(root) / seguro
    try:
        if arquivo.is_symlink():
            return False
        fresco = ler_texto(arquivo)
    except (OSError, UnicodeError):
        return False
    return not nota_sigilosa(root, seguro, fresco)


def _publica(root, nota):
    from .privacidade import nota_sigilosa

    if nota is None or not nota.util or nota.texto is None:
        return False
    relative = str(nota.relative or "").replace("\\", "/")
    if not relative or relative.startswith(".") or "/." in f"/{relative}/":
        return False
    parts = [part for part in relative.split("/") if part]
    if any(part == ".obsidian" or part.startswith(".") for part in parts):
        return False
    try:
        if nota_sigilosa(root, relative, nota.texto):
            return False
    except Exception:
        return False
    return True


def _carregar(path, modelo):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("modelo") != modelo:
        return {}
    notes = data.get("notas")
    cleaned = {}
    if isinstance(notes, dict):
        for key, value in notes.items():
            entry = _limpar(value)
            if entry is not None:
                cleaned[str(key).replace("\\", "/")] = entry
    return cleaned


def _limpar(value):
    if not isinstance(value, dict):
        return None
    if any(key in value for key in _PROIBIDO):
        return None
    rows = value.get("trechos")
    if not isinstance(rows, list) or not rows:
        return None
    vectors = []
    width = None
    for row in rows:
        vector = _vetor(row)
        if vector is None:
            return None
        if width is None:
            width = len(vector)
        if len(vector) != width:
            return None
        vectors.append(vector)
    return {
        "mtime_ns": value.get("mtime_ns"),
        "tamanho": value.get("tamanho"),
        "sha256": str(value.get("sha256") or ""),
        "trechos": vectors,
    }


def _gravar(path, entries, modelo):
    safe = {}
    for key, value in entries.items():
        entry = _limpar(value)
        if entry is not None:
            safe[str(key).replace("\\", "/")] = entry
    raw = json.dumps(
        {"versao": 1, "modelo": modelo, "notas": safe},
        ensure_ascii=True,
    ).encode("utf-8")
    from .trava import gravar_atomico

    gravar_atomico(path, raw, mode=0o600)


def buscar_trechos(root, consulta, embedder, limite=8, store=None, pasta=""):
    """Trechos parecidos com a pergunta. None se o modelo falhar."""

    if embedder is None:
        return None
    index = IndiceSemantico(root, embedder, store)
    changed = index.sincronizar()
    if changed is None:
        return None
    from .busca import dense_cosine, in_scope
    from .catalogo import obter

    try:
        query_rows = embedder.embed([consulta or ""])
    except Exception:
        return None
    query = _vetor(query_rows[0]) if query_rows else None
    if query is None:
        return None
    try:
        catalogo = obter(root)
    except Exception:
        return None
    ranked = []
    for relative, entry in index.entries.items():
        if pasta and not in_scope(relative, pasta):
            continue
        nota = catalogo.notas.get(relative)
        if not _publica(root, nota):
            continue
        fatias = fatiar(nota.texto)
        vectors = entry.get("trechos") or []
        if len(fatias) != len(vectors):
            continue
        for (heading, plain), vector in zip(fatias, vectors):
            score = dense_cosine(query, vector)
            if score < _PISO:
                continue
            ranked.append(
                Trecho(
                    relative,
                    _titulo(nota),
                    heading,
                    plain,
                    vector,
                    score,
                )
            )
    ranked.sort(key=lambda item: (-item.score, item.caminho, item.heading))
    return ranked[: max(1, int(limite)) * 4]


def _titulo(nota):
    titulo = " ".join(str(nota.titulo or Path(nota.relative).stem).split())
    return titulo[:160] or Path(nota.relative).stem


def hits_da_busca(root, consulta, modo_atual, embedder=None, limite=5, store=None):
    """Junta a busca por palavra com a semelhança, conforme o modo."""

    from .busca import fuse_rrf, parse_scope
    from .routines import hybrid_notes

    lexical, pasta = parse_scope(consulta or "")
    aviso = ""
    trechos = []
    if modo_atual in {"semantica", "hibrida"}:
        modelo = embedder if embedder is not None else embedder_da_busca()
        if modelo is None:
            aviso = mensagem_dependencia()
        else:
            trechos = buscar_trechos(
                root,
                lexical or consulta,
                modelo,
                limite=max(limite, 8),
                store=store,
                pasta=pasta,
            )
            if trechos is None:
                aviso = mensagem_falha(modelo)
                trechos = []
    if modo_atual == "semantica":
        return [_hit(item) for item in _um_por_nota(trechos)[:limite]], aviso
    palavras = hybrid_notes(root, consulta, embedder=None, limit=max(limite, 8))
    if modo_atual != "hibrida" or not trechos:
        return list(palavras[:limite]), aviso
    por_nota = _um_por_nota(trechos)
    ordem_v = []
    prontos = {}
    for hit in palavras:
        prontos[hit.relative] = hit
    for item in por_nota:
        if item.caminho not in ordem_v:
            ordem_v.append(item.caminho)
        prontos.setdefault(item.caminho, _hit(item))
    fused = fuse_rrf(
        [[hit.relative for hit in palavras], ordem_v],
        key=lambda item: item,
    )
    hits = [prontos[marker] for _score, marker in fused[:limite] if marker in prontos]
    return hits, aviso


def _um_por_nota(trechos):
    melhores = {}
    for item in trechos or []:
        atual = melhores.get(item.caminho)
        if atual is None or item.score > atual.score:
            melhores[item.caminho] = item
    return sorted(melhores.values(), key=lambda item: (-item.score, item.caminho))


def _hit(trecho):
    from .routines import Hit

    snippet = " ".join((trecho.texto or "").split())[:180]
    return Hit(Path(trecho.caminho), trecho.titulo, snippet, trecho.caminho)


def notas_parecidas(root, consulta, embedder, limit=5, store=None):
    """Títulos parecidos pelo índice. None se o modelo falhar."""

    if embedder is None:
        return None
    index = IndiceSemantico(root, embedder, store)
    if index.sincronizar() is None:
        return None
    from .busca import dense_cosine
    from .catalogo import obter
    from .routines import fold

    try:
        catalogo = obter(root)
    except Exception:
        return None
    grupos = {}
    for relative, entry in index.entries.items():
        nota = catalogo.notas.get(relative)
        if not _publica(root, nota):
            continue
        fatias = fatiar(nota.texto)
        vectors = entry.get("trechos") or []
        if not fatias or len(fatias) != len(vectors):
            continue
        centro = _centroide(vectors)
        if centro is None:
            continue
        grupos[relative] = (centro, _titulo(nota))
    if not grupos:
        return []
    ancora = _ancora(grupos, consulta, fold)
    if ancora and ancora in grupos:
        consulta_vetor = grupos[ancora][0]
    else:
        try:
            rows = embedder.embed([consulta or ""])
        except Exception:
            return None
        consulta_vetor = _vetor(rows[0]) if rows else None
        if consulta_vetor is None:
            return None
    ranked = []
    for relative, (vector, titulo) in grupos.items():
        if relative == ancora:
            continue
        score = dense_cosine(consulta_vetor, vector)
        if score < _PISO:
            continue
        ranked.append((score, titulo, relative))
    ranked.sort(key=lambda item: (-item[0], item[2]))
    saida = []
    for _score, titulo, relative in ranked[:limit]:
        saida.append(
            {
                "titulo": titulo,
                "caminho": relative,
            }
        )
        if len(saida) >= limit:
            break
    return saida


def _ancora(grupos, consulta, fold):
    folded = fold(consulta or "")
    if not folded:
        return ""
    for relative, (_vector, titulo) in grupos.items():
        stem = relative[:-3] if relative.lower().endswith(".md") else relative
        nomes = {
            fold(titulo),
            fold(stem),
            fold(Path(stem).name),
            fold(relative),
        }
        if folded in nomes:
            return relative
    return ""


def _centroide(vectors):
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
            total[index] += float(value)
    count = float(len(vectors))
    return [value / count for value in total]


def vetores_das_notas(root, notas, embedder, store=None):
    """Centros do índice semântico, na mesma ordem útil das notas públicas."""

    if embedder is None:
        return None
    if not notas:
        return []
    index = IndiceSemantico(root, embedder, store)
    if index.sincronizar() is None:
        return None
    from .catalogo import obter

    try:
        catalogo = obter(root)
    except Exception:
        return None
    centros = {}
    for relative, entry in index.entries.items():
        nota = catalogo.notas.get(relative)
        if not _publica(root, nota):
            continue
        centro = _centroide(entry.get("trechos") or [])
        if centro is not None:
            centros[relative] = centro
    saida = []
    for nota in notas:
        caminho = str(nota.get("caminho") or "").replace("\\", "/")
        centro = centros.get(caminho)
        if centro is None:
            continue
        item = dict(nota)
        item["vetor"] = centro
        saida.append(item)
    return saida
