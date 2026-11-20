"""Catálogo em memória das notas já lidas.

A segunda passagem só relê o arquivo cujo tamanho ou mtime mudou.
O texto não é gravado em disco. Os n-gramas ficam em vetores de
código numérico, os tokens repetidos apontam para a mesma string
e as linhas já dobradas ficam prontas para o bônus da busca.
"""

import os
import sys
import time
from pathlib import Path

from .leitura import avisar, iter_markdown, ler_nota_marcada

_RAIZES = {}
_ORDEM = []
_LIMITE = 4


class Preparo:
    def __init__(self, dobrado):
        self.dobrado = dobrado
        self._tokens = None
        self._palavras = None
        self._gramas = None
        self._linhas = None

    @property
    def tokens(self):
        prontos = self._tokens
        if prontos is None:
            from .busca import _TOKEN_RE

            prontos = tuple(sys.intern(token) for token in _TOKEN_RE.findall(self.dobrado))
            self._tokens = prontos
        return prontos

    @property
    def palavras(self):
        prontas = self._palavras
        if prontas is None:
            prontas = tuple(token for token in self.tokens if len(token) >= 3)
            self._palavras = prontas
        return prontas

    @property
    def linhas(self):
        prontas = self._linhas
        if prontas is None:
            prontas = tuple(self.dobrado.splitlines())
            self._linhas = prontas
        return prontas

    @property
    def gramas(self):
        prontas = self._gramas
        if prontas is None:
            from .busca import Gramas

            prontas = Gramas.das_palavras(self.palavras)
            self._gramas = prontas
        return prontas


class Nota:
    def __init__(self, path, relative, mtime_ns, tamanho, sha256, texto, titulo, cartoes):
        self.path = path
        self.relative = relative
        self.mtime_ns = mtime_ns
        self.tamanho = tamanho
        self.sha256 = sha256
        self.texto = texto
        self.titulo = titulo
        self._tags = None
        self.cartoes = cartoes
        self._preparo = None
        self._preparado = False
        self.sigilosa = False
        self.util = texto is not None

    @property
    def tags(self):
        prontas = self._tags
        if prontas is None:
            prontas = []
            if self.texto is not None:
                try:
                    prontas = _tags(self.texto)
                except Exception:
                    avisar(self.relative, "leitura")
            self._tags = prontas
        return prontas

    @property
    def preparo(self):
        if self._preparado:
            return self._preparo
        pronto = None
        if self.util:
            try:
                pronto = _preparar(self.titulo, self.texto)
            except Exception:
                avisar(self.relative, "leitura")
                pronto = _preparar(self.titulo, "")
        self._preparo = pronto
        self._preparado = True
        return pronto


class Catalogo:
    def __init__(self):
        self.notas = {}

    def sincronizar(self, root, progresso=None):
        from .routines import MAX_WALK, _title

        raiz = Path(root)
        try:
            base = raiz.resolve()
        except OSError:
            return []
        base_txt = str(base)
        prefixo = base_txt if base_txt.endswith(os.sep) else base_txt + os.sep
        caminhos = []
        for path in iter_markdown(raiz):
            if len(caminhos) >= MAX_WALK:
                avisar("vault", "teto-de-notas")
                break
            caminhos.append(path)
        total = len(caminhos)
        vistos = set()
        titulos = {}
        mudou = []
        inicio = time.perf_counter()
        for indice, path in enumerate(caminhos, 1):
            bruto = str(path)
            if bruto.startswith(prefixo):
                relativo = bruto[len(prefixo) :].replace("\\", "/")
            else:
                try:
                    relativo = path.relative_to(base).as_posix()
                except ValueError:
                    self._tick(progresso, indice, total, inicio)
                    continue
            if not relativo or relativo.startswith(".") or "/." in f"/{relativo}":
                self._tick(progresso, indice, total, inicio)
                continue
            vistos.add(relativo)
            try:
                stat = path.stat()
            except OSError:
                avisar(relativo, "leitura")
                self._tick(progresso, indice, total, inicio)
                continue
            atual = self.notas.get(relativo)
            # Alguns discos só avançam o mtime a cada poucos milissegundos.
            # Uma gravação nesse intervalo mantém tamanho e carimbo iguais.
            recente = time.time_ns() - stat.st_mtime_ns < 20_000_000
            if (
                atual is not None
                and atual.mtime_ns == stat.st_mtime_ns
                and atual.tamanho == stat.st_size
                and not recente
            ):
                self._titulo(titulos, atual)
                self._tick(progresso, indice, total, inicio)
                continue
            try:
                texto, digest, sigilosa = ler_nota_marcada(path, relativo)
            except Exception:
                avisar(relativo, "leitura")
                texto, digest, sigilosa = None, "", False
            titulo = path.stem
            cartoes = []
            if texto is not None:
                try:
                    titulo = _title(path, texto) or path.stem
                    cartoes = _cartoes(texto, relativo)
                except Exception:
                    avisar(relativo, "leitura")
            nota = Nota(
                path,
                relativo,
                stat.st_mtime_ns,
                stat.st_size,
                digest,
                texto,
                titulo,
                cartoes,
            )
            nota.sigilosa = bool(nota.util and sigilosa)
            self.notas[relativo] = nota
            mudou.append(relativo)
            self._titulo(titulos, nota)
            self._tick(progresso, indice, total, inicio)
        for chave in list(self.notas):
            if chave not in vistos:
                del self.notas[chave]
        return mudou

    def _titulo(self, vistos, nota):
        if not nota.util:
            return
        from .routines import fold

        chave = fold(nota.titulo or "")
        if not chave:
            return
        if chave in vistos and vistos[chave] != nota.relative:
            avisar(nota.relative, "titulo")
        else:
            vistos[chave] = nota.relative

    def _tick(self, progresso, feito, total, inicio):
        if progresso is None:
            return
        if feito != total and feito % 25 != 0:
            return
        progresso(feito, total, time.perf_counter() - inicio)


def obter(root, progresso=None):
    try:
        chave = str(Path(root).resolve())
    except OSError:
        chave = str(root)
    catalogo = _RAIZES.get(chave)
    if catalogo is None:
        catalogo = Catalogo()
        _RAIZES[chave] = catalogo
        _ORDEM.append(chave)
        while len(_ORDEM) > _LIMITE:
            antigo = _ORDEM.pop(0)
            _RAIZES.pop(antigo, None)
    elif chave in _ORDEM:
        _ORDEM.remove(chave)
        _ORDEM.append(chave)
    catalogo.sincronizar(root, progresso=progresso)
    return catalogo


def limpar_catalogo():
    _RAIZES.clear()
    _ORDEM.clear()


def _cartoes(texto, relativo):
    from .review import _visible_lines, parse_card_line

    achados = []
    if ":::" not in (texto or ""):
        return achados
    for linha in _visible_lines(texto):
        parsed = parse_card_line(linha, relativo)
        if parsed is not None:
            achados.append(parsed)
    return achados


def _tags(texto):
    import re

    from .routines import fold

    tags = []

    def adicionar(valor):
        token = str(valor or "").strip().strip("\"'").lstrip("#")
        token = token.strip()
        if not token or token in tags or len(token) > 40:
            return
        tags.append(token)

    bruto = texto or ""
    bloco = ""
    if bruto.startswith("---"):
        fim = bruto.find("\n---", 3)
        if fim != -1:
            bloco = bruto[3:fim]
    esperando = False
    for linha in bloco.splitlines():
        if linha[:1] in {" ", "\t"}:
            item = linha.strip()
            if esperando and item.startswith("- "):
                adicionar(item[2:])
            continue
        esperando = False
        if ":" not in linha:
            continue
        chave, valor = linha.split(":", 1)
        if fold(chave.strip()) not in {"tags", "tag"}:
            continue
        valor = valor.strip()
        if not valor:
            esperando = True
            continue
        for parte in re.split(r"[,\[\]]+", valor):
            adicionar(parte)
    for achado in re.finditer(r"(?<![\w/])#([A-Za-z0-9_-]{1,40})", bruto):
        adicionar(achado.group(1))
        if len(tags) >= 12:
            break
    return tags[:12]


def _preparar(titulo, texto):
    from .busca import fold

    return Preparo(fold((titulo or "") + "\n" + (texto or "")))
