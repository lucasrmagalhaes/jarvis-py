"""Busca híbrida local: BM25 e, quando houver, embeddings.

Sem pesos de embeddings, a resposta fica na palavra. O Reciprocal Rank
Fusion junta as listas que existirem. A pasta .obsidian não entra.
"""

import array
import math
import re
import sys
import unicodedata
from collections import Counter
from functools import lru_cache

RRF_K = 60
BM25_K1 = 1.5
BM25_B = 0.75
MODEL_HIGH = 0.72
MODEL_ACCEPT = 0.55
MODEL_MARGIN = 0.08

SCOPES = {
    "livros": "Tecnologia/Livros",
    "videos": "Tecnologia/Vídeos",
    "cursos": "Tecnologia/Cursos",
}


def scope_map():
    try:
        from . import config

        return {
            "livros": config.livros_pasta(),
            "videos": config.videos_pasta(),
            "cursos": config.cursos_pasta(),
        }
    except Exception:
        return dict(SCOPES)

_SCOPE_RE = re.compile(
    r"(?i)(?:^|\s)(?:nos|nas)\s+(livros|v[ií]deos|videos|cursos)\b"
)
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")


_COMBINANTES = {}


def _tabela_de_combinantes():
    if not _COMBINANTES:
        _COMBINANTES.update(
            dict.fromkeys(
                codigo
                for codigo in range(sys.maxunicode + 1)
                if unicodedata.combining(chr(codigo))
            )
        )
    return _COMBINANTES


_FORA_DO_ASCII = re.compile(r"[^\x00-\x7f]+")


@lru_cache(maxsize=4096)
def _dobrar_trecho(trecho):
    return unicodedata.normalize("NFKD", trecho).translate(_tabela_de_combinantes())


def _trocar_trecho(achado):
    return _dobrar_trecho(achado.group())


def fold(text):
    bruto = text or ""
    if bruto.isascii():
        return bruto.casefold()
    return _FORA_DO_ASCII.sub(_trocar_trecho, bruto).casefold()


def parse_scope(query):
    folder = ""

    def replace(match):
        nonlocal folder
        key = fold(match.group(1))
        scopes = _scope_atual()
        if key in scopes and not folder:
            folder = scopes[key]
        return " "

    cleaned = _SCOPE_RE.sub(replace, query or "")
    return " ".join(cleaned.split()), folder


def _scope_atual():
    return scope_map()


def in_scope(relative, folder):
    rel = (relative or "").replace("\\", "/").strip("/")
    if not rel or rel.startswith(".") or "/." in f"/{rel}/":
        return False
    parts = [part for part in rel.split("/") if part]
    if any(part == ".obsidian" or part.startswith(".") for part in parts):
        return False
    if not folder:
        return True
    prefix = folder.strip("/")
    if rel == prefix or rel.startswith(prefix + "/"):
        return True
    folded = fold(rel)
    folded_prefix = fold(prefix)
    return folded == folded_prefix or folded.startswith(folded_prefix + "/")


def needed_count(count):
    if count <= 2:
        return count
    return max(2, int(round(count * 0.67)))


def exact_support(words, text):
    if not words:
        return 0
    tokens = set(_WORD_RE.findall(fold(text)))
    return exact_from_words(words, tokens)


def exact_from_words(words, tokens):
    if not words:
        return 0
    known = tokens if isinstance(tokens, set) else set(tokens or [])
    return sum(1 for word in words if word in known)


@lru_cache(maxsize=512)
def _padrao_inteiro(word):
    return re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])")


@lru_cache(maxsize=512)
def _padrao_prefixo(prefixo):
    return re.compile(r"(?<![a-z0-9])" + re.escape(prefixo) + r"[a-z0-9]*")


def tem_palavra(dobrado, word):
    if word not in dobrado or not _WORD_RE.fullmatch(word):
        return False
    return _padrao_inteiro(word).search(dobrado) is not None


def exact_do_texto(words, dobrado):
    if not words:
        return 0
    return sum(1 for word in words if tem_palavra(dobrado, word))


def fuzzy_do_texto(words, dobrado):
    if not words:
        return 0
    found = 0
    for word in words:
        if tem_palavra(dobrado, word):
            found += 1
            continue
        if len(word) < 5:
            continue
        prefixo = word[:5]
        if prefixo not in dobrado or not _WORD_RE.fullmatch(prefixo):
            continue
        vistos = set()
        for token in _padrao_prefixo(prefixo).findall(dobrado):
            if token in vistos:
                continue
            vistos.add(token)
            limit = min(len(word), len(token))
            prefix = 5
            while prefix < limit and word[prefix] == token[prefix]:
                prefix += 1
            if prefix / max(len(word), len(token)) >= 0.6:
                found += 1
                break
    return found


def fuzzy_support(words, text):
    if not words:
        return 0
    return fuzzy_from_tokens(words, _WORD_RE.findall(fold(text)))


def fuzzy_from_tokens(words, tokens):
    if not words:
        return 0
    found = 0
    known = list(tokens or [])
    exatos = set(known)
    for word in words:
        if word in exatos:
            found += 1
            continue
        if len(word) < 5:
            continue
        for token in known:
            if len(token) < 4:
                continue
            limit = min(len(word), len(token))
            prefix = 0
            while prefix < limit and word[prefix] == token[prefix]:
                prefix += 1
            longest = max(len(word), len(token))
            if prefix >= 5 and prefix / longest >= 0.6:
                found += 1
                break
    return found


def line_bonus(text, words):
    if not words:
        return 0.0
    best = 0
    for line in (text or "").splitlines():
        folded = fold(line)
        present = sum(1 for word in words if word in folded)
        if present > best:
            best = present
    bonus = 0.2 * best
    if len(words) > 1 and best == len(words):
        bonus += 1.5
    phrase = " ".join(words)
    if len(words) > 1 and phrase and phrase in fold(text):
        bonus += 0.8
    return bonus


def line_bonus_pronta(linhas, dobrado, words):
    if not words:
        return 0.0
    if linhas is None:
        linhas = (dobrado or "").splitlines()
    best = 0
    for folded in linhas or []:
        present = sum(1 for word in words if word in folded)
        if present > best:
            best = present
    bonus = 0.2 * best
    if len(words) > 1 and best == len(words):
        bonus += 1.5
    phrase = " ".join(words)
    if len(words) > 1 and phrase and phrase in (dobrado or ""):
        bonus += 0.8
    return bonus


def bm25_ranking(docs, words, k1=BM25_K1, b=BM25_B):
    total = len(docs)
    if not total or not words:
        return [0.0] * total
    query = []
    seen = set()
    for word in words:
        token = fold(word)
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        query.append(token)
    if not query:
        return [0.0] * total
    tokenized = []
    for doc in docs:
        tokenized.append(_TOKEN_RE.findall(fold(doc)))
    df = {}
    lengths = []
    for tokens in tokenized:
        lengths.append(len(tokens) or 1)
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    average = sum(lengths) / total or 1.0
    scores = []
    for tokens, length in zip(tokenized, lengths):
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        score = 0.0
        for token in query:
            freq = tf.get(token, 0)
            if not freq:
                continue
            docs_with = df.get(token, 0)
            idf = math.log(1.0 + (total - docs_with + 0.5) / (docs_with + 0.5))
            denom = freq + k1 * (1.0 - b + b * length / average)
            score += idf * (freq * (k1 + 1.0)) / denom
        scores.append(score)
    return scores


def bm25_tokens(tokenized, words, k1=BM25_K1, b=BM25_B):
    total = len(tokenized)
    if not total or not words:
        return [0.0] * total
    query = []
    seen = set()
    for word in words:
        token = fold(word)
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        query.append(token)
    if not query:
        return [0.0] * total
    df = {}
    lengths = []
    for tokens in tokenized:
        lengths.append(len(tokens) or 1)
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    average = sum(lengths) / total or 1.0
    scores = []
    for tokens, length in zip(tokenized, lengths):
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        score = 0.0
        for token in query:
            freq = tf.get(token, 0)
            if not freq:
                continue
            docs_with = df.get(token, 0)
            idf = math.log(1.0 + (total - docs_with + 0.5) / (docs_with + 0.5))
            denom = freq + k1 * (1.0 - b + b * length / average)
            score += idf * (freq * (k1 + 1.0)) / denom
        scores.append(score)
    return scores


def fuse_rrf(rankings, key, k=RRF_K):
    scores = {}
    found = {}
    for ranking in rankings:
        for index, item in enumerate(ranking):
            marker = key(item)
            scores[marker] = scores.get(marker, 0.0) + 1.0 / (k + index + 1)
            found.setdefault(marker, item)
    ordered = sorted(scores, key=lambda marker: (-scores[marker], str(marker)))
    return [(scores[marker], found[marker]) for marker in ordered]


def dense_cosine(left, right):
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


def model_is_usable(scores):
    if not scores:
        return False
    best = scores[0]
    second = scores[1] if len(scores) > 1 else 0.0
    if best >= MODEL_HIGH:
        return True
    return best >= MODEL_ACCEPT and best - second >= MODEL_MARGIN


_ALFABETO = "<>0123456789abcdefghijklmnopqrstuvwxyz"
_BASE = len(_ALFABETO)
_INDICE = {char: index for index, char in enumerate(_ALFABETO)}


def _grams(text):
    counts = {}
    for word in _WORD_RE.findall(fold(text)):
        padded = "<" + word + ">"
        for index in range(len(padded) - 2):
            gram = padded[index : index + 3]
            counts[gram] = counts.get(gram, 0) + 1
    return counts


def _codigo_grama(gram):
    if len(gram) != 3:
        return None
    return _codigo_trio(gram[0], gram[1], gram[2])


def _codigo_trio(a, b, c):
    ia = _INDICE.get(a)
    ib = _INDICE.get(b)
    ic = _INDICE.get(c)
    if ia is None or ib is None or ic is None:
        return None
    return (ia * _BASE + ib) * _BASE + ic


_TABELA_NUMPY = []
_MINIMO_NUMPY = 64


def _gramas_com_numpy(palavras):
    longas = [word for word in palavras or () if len(word) >= 3]
    if len(longas) < _MINIMO_NUMPY:
        return None
    try:
        import numpy as np

        bruto = ("<" + "><".join(longas) + ">").encode("ascii")
    except (ImportError, UnicodeError):
        return None
    if not _TABELA_NUMPY:
        tabela = np.full(256, -1, dtype=np.int64)
        for char, indice in _INDICE.items():
            tabela[ord(char)] = indice
        _TABELA_NUMPY.append(tabela)
    letras = np.frombuffer(bruto, dtype=np.uint8)
    indices = _TABELA_NUMPY[0][letras]
    if int(indices.min()) < 0:
        return None
    fecho = letras == ord(">")
    validos = ~(fecho[:-2] | fecho[1:-1])
    codigos = (indices[:-2] * _BASE + indices[1:-1]) * _BASE + indices[2:]
    unicos, vezes = np.unique(codigos[validos], return_counts=True)
    vezes = np.minimum(vezes, 65535)
    chaves = array.array("H")
    chaves.frombytes(unicos.astype(np.uint16).tobytes())
    valores = array.array("H")
    valores.frombytes(vezes.astype(np.uint16).tobytes())
    norma = math.sqrt(int(np.dot(vezes.astype(np.int64), vezes.astype(np.int64))))
    return chaves, valores, norma


@lru_cache(maxsize=65536)
def _codigos_da_palavra(word):
    padded = "<" + word + ">"
    codigos = []
    for index in range(len(padded) - 2):
        codigo = _codigo_trio(padded[index], padded[index + 1], padded[index + 2])
        if codigo is not None:
            codigos.append(codigo)
    return tuple(codigos)


class Gramas:
    """N-gramas da nota em dois vetores de código. A chave deixa de ser o texto."""

    __slots__ = ("chaves", "valores", "norma")

    def __init__(self, chaves, valores, norma):
        self.chaves = chaves
        self.valores = valores
        self.norma = norma

    @classmethod
    def das_palavras(cls, palavras):
        rapidas = _gramas_com_numpy(palavras)
        if rapidas is not None:
            return cls(*rapidas)
        counts = {}
        for word, vezes in Counter(palavras or ()).items():
            if len(word) < 3:
                continue
            for codigo in _codigos_da_palavra(word):
                counts[codigo] = counts.get(codigo, 0) + vezes
        return cls._dos_codigos(counts)

    @classmethod
    def da_contagem(cls, counts):
        codigos = {}
        for gram, valor in (counts or {}).items():
            if isinstance(gram, int):
                codigo = gram
            else:
                codigo = _codigo_grama(gram)
            if codigo is None or valor <= 0:
                continue
            codigos[codigo] = int(valor)
        return cls._dos_codigos(codigos)

    @classmethod
    def _dos_codigos(cls, codigos):
        pares = sorted(codigos.items())
        chaves = array.array("H", (codigo for codigo, _valor in pares))
        valores = array.array("H", (min(valor, 65535) for _codigo, valor in pares))
        norma = math.sqrt(sum(int(valor) * int(valor) for valor in valores))
        return cls(chaves, valores, norma)

    def get(self, gram, default=0):
        codigo = gram if isinstance(gram, int) else _codigo_grama(gram)
        if codigo is None:
            return default
        chaves = self.chaves
        lo = 0
        hi = len(chaves)
        while lo < hi:
            meio = (lo + hi) // 2
            atual = chaves[meio]
            if atual < codigo:
                lo = meio + 1
            elif atual > codigo:
                hi = meio
            else:
                return int(self.valores[meio])
        return default

    def __bool__(self):
        return bool(self.chaves)


def _cosseno_gramas(left, right):
    """Cosseno de dois vetores já ordenados. A norma da nota fica pronta."""

    chaves_e = left.chaves
    chaves_d = right.chaves
    vals_e = left.valores
    vals_d = right.valores
    i = 0
    j = 0
    n_e = len(chaves_e)
    n_d = len(chaves_d)
    dot = 0.0
    while i < n_e and j < n_d:
        a = chaves_e[i]
        b = chaves_d[j]
        if a == b:
            dot += int(vals_e[i]) * int(vals_d[j])
            i += 1
            j += 1
        elif a < b:
            i += 1
        else:
            j += 1
    if not left.norma or not right.norma:
        return 0.0
    return dot / (left.norma * right.norma)


def _consulta_numpy(gramas):
    import numpy as np

    q = np.zeros(_BASE * _BASE * _BASE, dtype=np.float64)
    for indice, codigo in enumerate(gramas.chaves):
        q[codigo] = gramas.valores[indice]
    return q, float(np.sqrt(np.dot(q, q)))


def _cosseno_numpy(q, norma_q, right):
    import numpy as np

    if norma_q == 0.0 or not right.norma or not len(right.chaves):
        return 0.0
    idx = np.frombuffer(right.chaves, dtype=np.uint16).astype(np.int64)
    vals = np.frombuffer(right.valores, dtype=np.uint16).astype(np.float64)
    return float(np.dot(vals, q[idx])) / (norma_q * right.norma)


def _cosseno_compacto(left, right):
    dot = 0.0
    for gram, value in left.items():
        other = right.get(gram, 0)
        if other:
            dot += value * other
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = right.norma
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _sparse_cosine(left, right):
    if not left or not right:
        return 0.0
    if not isinstance(left, dict) or not isinstance(right, dict):
        if isinstance(left, dict):
            return _cosseno_compacto(left, right)
        if isinstance(right, dict):
            return _cosseno_compacto(right, left)
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = 0.0
    for gram, value in left.items():
        other = right.get(gram)
        if other:
            dot += value * other
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def spelling_ranking(docs, words, floor=0.12, caches=None, pular=None):
    """Ordena por n-gramas de caractere. É variação de grafia, ainda na palavra."""

    if not docs or not words:
        return []
    query = _grams(" ".join(words))
    if not query:
        return []
    consulta = Gramas.da_contagem(query)
    try:
        q, norma_q = _consulta_numpy(consulta)
    except ImportError:
        q, norma_q = None, 0.0
    ranked = []
    for index, doc in enumerate(docs):
        if pular is not None and index in pular:
            continue
        pronto = caches[index] if caches is not None else None
        if pronto is not None:
            if fuzzy_do_texto(words, pronto.dobrado) <= 0:
                continue
            gramas = pronto.gramas
            if isinstance(gramas, Gramas):
                if q is None:
                    score = _cosseno_gramas(consulta, gramas)
                else:
                    score = _cosseno_numpy(q, norma_q, gramas)
            else:
                score = _sparse_cosine(query, gramas)
        else:
            if fuzzy_support(words, doc) <= 0:
                continue
            score = _sparse_cosine(query, _grams(doc))
        if score < floor:
            continue
        ranked.append((score, index))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked
