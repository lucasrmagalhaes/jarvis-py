"""Importa destaques de Kindle, PDF e KOReader para uma nota por livro.

O desenho segue o Readwise: a nota é idempotente, a repetição não duplica
e só entra destaque novo. O texto do destaque não vai para o log.
Arquivo de origem é dado, não pedido.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from .log import LOG

_FONTES = {"kindle", "pdf", "koreader"}
_LIMITE_TEXTO = 8_000_000
_LIMITE_PDF = 40_000_000
_MAX_ARQUIVOS = 200
_MAX_PROFUNDIDADE = 4
_MAX_TRECHOS = 2000
_MAX_PAGINAS = 2500
_MAX_ANOTACOES = 4000
_MAX_CONTEUDO = 4000
_ID = re.compile(r"^[0-9a-f]{16}$")
_BLOCO = re.compile(r"(?s)<!-- dt:([0-9a-f]{16}) -->\n(.*?)<!-- /dt -->")
_POS = re.compile(
    r"(?i)(?:location|loc\.|posi[cç][aã]o|position)\s+(\d+)"
)
_PAGINA = re.compile(r"(?i)(?:\bpage\b|p[aá]gina)\s+(\d+)")
_EDICAO = re.compile(
    r"(?i)(?:\s*[:\-]\s*)?(?:"
    r"\d+\s*[aªoº]?\s*edi[cç][aã]o|"
    r"edi[cç][aã]o(?:\s+kindle|\s+revista|\s+\d+)|"
    r"\d+(?:st|nd|rd|th)\s+edition|"
    r"(?:first|second|third|fourth|fifth|revised|kindle)\s+edition"
    r")\b"
)
_NOTA_MD = re.compile(r"(?i)^(?:nota|note)\s*:\s*(.*)$")
_PAGINA_MD = re.compile(r"(?i)^(?:p[aá]gina|page)\s+(\d+)\.?$")
_RESERVADOS = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "lpt1",
    "lpt2",
    "lpt3",
}

FALTA_VAULT = (
    "O vault não está configurado, senhor. "
    "Sem ele eu não gravo os destaques. "
    "Rode python -m jarvis.setup."
)
FALTA_PYPDF = (
    "Falta o pacote pypdf, senhor. Sem ele eu não leio anotações de PDF."
)
FALTA_ARQUIVO = "Não encontrei o arquivo, senhor."
ARQUIVO_BLOQUEADO = "Não li o arquivo, senhor. O caminho está bloqueado."
ATALHO = "Não li o arquivo, senhor. O caminho é um atalho."
FORMATO = "Não reconheci o formato desse arquivo, senhor."
VAZIO = "Esse arquivo não tem destaque, senhor."
GRANDE = "O arquivo é grande demais, senhor. Não importei."
CODIFICACAO = "Não li o arquivo, senhor. A codificação precisa ser UTF-8."
PDF_ILEGIVEL = "Não consegui ler o PDF, senhor."
PDF_PROTEGIDO = "Não li o PDF, senhor. Ele está protegido."
PASTA_PRIVADA = "Não importei, senhor. A pasta dos destaques é privada."
BLOQUEADO_VAULT = "Não importei, senhor. O vault está bloqueado para escrita agora."
ESCRITA_BLOQUEADA = "Não importei, senhor. A escrita foi bloqueada."
OCUPADO = "Não importei, senhor. O vault está ocupado."
NADA_NOVO = "Não há destaque novo, senhor."
ENTRADA_VAZIA = "Não encontrei destaque na pasta de entrada, senhor."
ENTRADA_AUSENTE = (
    "A pasta de entrada dos destaques não existe, senhor. "
    "Defina JARVIS_DESTAQUES_ENTRADA."
)
ENTRADA_DENTRO = (
    "Não importei, senhor. A pasta de entrada precisa ficar fora do vault."
)
ENTRADA_OBSIDIAN = "Não importei, senhor. A pasta .obsidian está bloqueada."
USO = (
    "Uso:\n"
    "  python -m jarvis destaques kindle ARQUIVO [--cartoes]\n"
    "  python -m jarvis destaques pdf ARQUIVO [--cartoes]\n"
    "  python -m jarvis destaques koreader ARQUIVO [--cartoes]"
)


class Resultado:
    def __init__(self, speech, ok=True, criados=0, ids=None):
        self.speech = speech
        self.ok = ok
        self.criados = criados
        self.ids = list(ids or [])


class Trecho:
    def __init__(self, texto, nota="", pagina=None, posicao=None, tipo="destaque"):
        self.texto = sanitizar(texto)
        self.nota = sanitizar(nota)
        self.pagina = pagina if isinstance(pagina, int) and pagina > 0 else None
        self.posicao = posicao if isinstance(posicao, int) and posicao > 0 else None
        self.tipo = tipo if tipo in {"destaque", "nota"} else "destaque"
        self.id = ""


class Livro:
    def __init__(self, titulo, autor, fonte, trechos):
        self.titulo = sanitizar(titulo) or "Sem título"
        self.autor = sanitizar(autor)
        self.fonte = fonte if fonte in _FONTES else "kindle"
        self.fontes = {self.fonte}
        self.trechos = list(trechos or [])


def sanitizar(valor):
    """Tira BOM, quebra do Windows e o fecho do bloco não confiável."""
    texto = str(valor or "")
    if texto.startswith("\ufeff"):
        texto = texto[1:]
    texto = texto.replace("\x00", "")
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = texto.replace("</dado-nao-confiavel>", "</dado nao confiavel>")
    texto = texto.replace("<dado-nao-confiavel", "<dado nao confiavel")
    return texto.strip()


def como_dado(texto):
    """Embrulha o destaque para um prompt. A nota gravada não leva a marca."""
    from .privacidade import embrulhar

    return embrulhar("destaque", sanitizar(texto))


def pasta_destino():
    from . import config

    bruto = config.destaques_pasta()
    return bruto or "Leituras/Destaques"


def pasta_entrada():
    from . import config

    return config.destaques_entrada()


def preparar_entrada(root, fonte, read_only=False, session=None):
    if read_only:
        return BLOQUEADO_VAULT
    codigo = fonte if fonte in _FONTES else ""
    relativa, problema = _preparar_pasta(root)
    if problema:
        return problema
    del relativa
    arquivos, aviso = _listar_entrada(root, codigo)
    if aviso:
        return aviso
    livros, recusados, falta_pdf = _ler_arquivos(arquivos, codigo)
    if falta_pdf and not livros:
        return FALTA_PYPDF
    if not livros:
        if falta_pdf:
            return FALTA_PYPDF
        return ENTRADA_VAZIA
    fala, novos, _nomes = prever(root, livros)
    if falta_pdf:
        fala = _acrescentar(fala, "Os PDFs ficaram de fora. " + FALTA_PYPDF)
    if recusados and "recusad" not in fala:
        fala = _com_recusa(fala, recusados)
    if novos > 0 and session is not None:
        session["pending"] = {"kind": "destaques", "fonte": codigo}
    LOG.info(
        "destaques previa fonte=%s novos=%s",
        codigo or "misto",
        novos,
    )
    return fala


def concluir_oferta(root, pending):
    dados = pending if isinstance(pending, dict) else {}
    kind = dados.get("kind")
    if kind == "destaques_cartoes":
        fala = _gravar_oferta_cartoes(root, dados.get("ids") or [])
        return fala, None
    if kind != "destaques":
        return NADA_NOVO, None
    fonte = dados.get("fonte") if dados.get("fonte") in _FONTES else ""
    arquivos, aviso = _listar_entrada(root, fonte)
    if aviso:
        return aviso, None
    livros, recusados, falta_pdf = _ler_arquivos(arquivos, fonte)
    if not livros:
        if falta_pdf:
            return FALTA_PYPDF, None
        return ENTRADA_VAZIA, None
    resultado = importar_livros(
        root, livros, recusados_extra=recusados, oferecer=True
    )
    seguinte = None
    if resultado.ok and resultado.criados and resultado.ids:
        seguinte = {"kind": "destaques_cartoes", "ids": resultado.ids[:400]}
    fala = resultado.speech
    if falta_pdf:
        fala = _acrescentar(fala, FALTA_PYPDF)
    return fala, seguinte


def prever(root, livros):
    from .guardas import texto_secreto
    from .privacidade import nota_sigilosa

    nomes = []
    novos = 0
    livros_novos = 0
    recusados = 0
    relativa, problema = _preparar_pasta(root)
    if problema:
        return problema, 0, []
    pasta = Path(root) / relativa
    for livro in _mesclar(livros):
        if _recusar_meta(livro, texto_secreto):
            recusados += max(1, len(livro.trechos))
            continue
        chave = chave_livro(livro.titulo, livro.autor)
        caminho, texto = _achar(pasta, chave)
        if caminho is not None and nota_sigilosa(root, _relativo(root, caminho), texto):
            recusados += len(livro.trechos) or 1
            continue
        blocos, _ordem = _blocos(texto)
        acrescentados = 0
        for trecho in livro.trechos:
            if _recusar_trecho(trecho, texto_secreto):
                recusados += 1
                continue
            identificar(trecho)
            if not trecho.id or trecho.id in blocos:
                continue
            blocos[trecho.id] = trecho.id
            acrescentados += 1
        if acrescentados:
            livros_novos += 1
            novos += acrescentados
            seguro = _titulo_seguro(livro.titulo, texto_secreto)
            if seguro:
                nomes.append(seguro)
    return _fala_previa(livros_novos, novos, recusados, nomes), novos, nomes


def importar_livros(root, livros, cartoes=False, recusados_extra=0, oferecer=False):
    from .guardas import GuardError
    from .trava import TravaOcupada, fila_escrita

    relativa, problema = _preparar_pasta(root)
    if problema:
        return Resultado(problema, ok=False)
    try:
        with fila_escrita():
            stats, ids = _aplicar(root, relativa, livros)
            cartoes_n = 0
            if cartoes and ids:
                cartoes_n = _aplicar_cartoes(root, relativa, ids)
    except GuardError:
        return Resultado(ESCRITA_BLOQUEADA, ok=False)
    except TravaOcupada:
        return Resultado(OCUPADO, ok=False)
    except OSError:
        LOG.error("destaques: escrita falhou")
        return Resultado(ESCRITA_BLOQUEADA, ok=False)
    stats["recusados"] += recusados_extra
    fala = _fala_gravou(stats, oferecer=oferecer and not cartoes)
    if cartoes_n:
        fala = _acrescentar(fala, _fala_cartoes(cartoes_n))
    LOG.info(
        "destaques livros=%s novos=%s atualizados=%s recusados=%s",
        stats["notas"],
        stats["criados"],
        stats["atualizados"],
        stats["recusados"],
    )
    return Resultado(fala, ok=True, criados=stats["criados"], ids=ids)


def importar_arquivo(root, caminho, fonte, cartoes=False):
    if fonte not in _FONTES:
        return Resultado(FORMATO, ok=False)
    origem, aviso = _origem_segura(caminho)
    if aviso:
        return Resultado(aviso, ok=False)
    if fonte == "pdf" and _leitor_pdf() is None:
        return Resultado(FALTA_PYPDF, ok=False)
    livros, codigo = _parse_caminho(origem, fonte)
    if codigo:
        return Resultado(_fala_codigo(codigo), ok=False)
    if not livros:
        return Resultado(VAZIO, ok=False)
    resultado = importar_livros(root, livros, cartoes=cartoes, oferecer=False)
    if resultado.ok and not cartoes and resultado.criados:
        resultado.speech += (
            " Use --cartoes para gravar cartões em rascunho. Depois diga revisa rascunhos."
        )
    return resultado


def chave_livro(titulo, autor):
    from .routines import fold

    limpo = _limpar_edicao(titulo)
    tema = re.sub(r"[^a-z0-9]+", " ", fold(limpo)).strip()
    pessoa = re.sub(r"[^a-z0-9]+", " ", _autor_norm(autor)).strip()
    return (tema or "sem titulo") + "|" + pessoa


def identificar(trecho):
    from .routines import fold

    base = trecho.texto or trecho.nota
    chave = fold(" ".join(base.split()))
    if not chave:
        trecho.id = ""
        return
    trecho.id = hashlib.sha256(chave.encode("utf-8")).hexdigest()[:16]


def main(argv=None):
    from .vault import Vault

    bruto_args = list(argv or [])
    if any(item in {"-h", "--help", "ajuda"} for item in bruto_args):
        print(USO)
        return 0
    args = [item for item in bruto_args if item != "--cartoes"]
    cartoes = "--cartoes" in bruto_args
    if len(args) != 2 or args[0] not in _FONTES:
        print(USO)
        return 2
    fonte, bruto = args
    vault = Vault.from_env()
    if vault is None:
        print(FALTA_VAULT)
        return 1
    _relativa, problema = _preparar_pasta(vault.path)
    if problema:
        print(problema)
        return 1
    prep = vault.prepare()
    print(prep.detail)
    if prep.fatal or not prep.ok or prep.read_only:
        if prep.read_only:
            print(BLOQUEADO_VAULT)
        return 1
    resultado = importar_arquivo(vault.path, bruto, fonte, cartoes=cartoes)
    print(resultado.speech)
    if not resultado.ok:
        return 1
    if resultado.criados or "Atualizei" in resultado.speech or "Importei" in resultado.speech:
        publicado = vault.publish("importa destaques")
        print(publicado.detail)
        if not publicado.ok or publicado.fatal:
            return 1
    return 0


def _preparar_pasta(root):
    from .privacidade import nota_sigilosa
    from .readwise import resolve_folder

    relativa, problema = resolve_folder(root, pasta_destino())
    if problema:
        return None, problema
    if nota_sigilosa(root, relativa, ""):
        return None, PASTA_PRIVADA
    return relativa, None


def _listar_entrada(root, fonte):
    pasta = pasta_entrada()
    try:
        if not pasta.is_dir():
            return [], ENTRADA_AUSENTE
        if pasta.is_symlink():
            return [], ATALHO
    except OSError:
        return [], ENTRADA_AUSENTE
    if _tem_obsidian(pasta):
        return [], ENTRADA_OBSIDIAN
    if _dentro(root, pasta) or _dentro(pasta, root):
        return [], ENTRADA_DENTRO
    arquivos = []
    base = pasta.resolve()
    vault = _resolvido(root)
    for atual, dirnames, nomes in os.walk(base):
        atual_path = Path(atual)
        try:
            profundidade = len(atual_path.resolve().relative_to(base).parts)
        except (OSError, ValueError):
            dirnames[:] = []
            continue
        if profundidade > _MAX_PROFUNDIDADE:
            dirnames[:] = []
            continue
        mantidos = []
        for nome in dirnames:
            if not nome or nome.startswith(".") or nome == ".obsidian":
                continue
            filho = atual_path / nome
            if filho.is_symlink():
                continue
            if vault is not None and _resolvido(filho) == vault:
                continue
            mantidos.append(nome)
        dirnames[:] = mantidos
        for nome in nomes:
            if len(arquivos) >= _MAX_ARQUIVOS:
                break
            if not nome or nome.startswith("."):
                continue
            caminho = atual_path / nome
            if not _aceita(caminho, fonte):
                continue
            arquivos.append(caminho)
    arquivos.sort()
    return arquivos, ""


def _aceita(caminho, fonte):
    if caminho.is_symlink() or not caminho.is_file():
        return False
    if _origem_segura(caminho)[1]:
        return False
    sufixo = caminho.suffix.casefold()
    if fonte == "kindle":
        return sufixo == ".txt"
    if fonte == "pdf":
        return sufixo == ".pdf"
    if fonte == "koreader":
        return sufixo in {".lua", ".json", ".md"}
    return sufixo in {".txt", ".pdf", ".lua", ".json", ".md"}


def _ler_arquivos(arquivos, fonte):
    livros = []
    recusados = 0
    falta_pdf = False
    for caminho in arquivos:
        escolhida = fonte or _fonte_pelo_sufixo(caminho)
        if escolhida == "pdf" and _leitor_pdf() is None:
            falta_pdf = True
            continue
        try:
            achados, codigo = _parse_caminho(caminho, escolhida)
        except OSError:
            LOG.error("destaques: leitura falhou")
            recusados += 1
            continue
        if codigo in {"grande", "codificacao", "ilegivel", "protegido", "bloqueado"}:
            recusados += 1
            continue
        livros.extend(achados)
    return livros, recusados, falta_pdf


def _fonte_pelo_sufixo(caminho):
    sufixo = Path(caminho).suffix.casefold()
    if sufixo == ".pdf":
        return "pdf"
    if sufixo == ".txt":
        return "kindle"
    return "koreader"


def _parse_caminho(caminho, fonte):
    if fonte == "pdf":
        return _parse_pdf(caminho)
    texto, codigo = _ler_texto_arquivo(caminho)
    if codigo:
        return [], codigo
    if fonte == "kindle":
        return _parse_kindle(texto)
    if fonte == "koreader":
        return _parse_koreader(texto, caminho)
    return [], "formato"


def _ler_texto_arquivo(caminho):
    from .leitura import texto_de_bytes
    from .paths import abrir_leitura, e_atalho, tamanho_arquivo

    if e_atalho(caminho):
        return "", "atalho"
    try:
        tamanho = tamanho_arquivo(caminho)
    except OSError:
        return "", "arquivo"
    if tamanho > _LIMITE_TEXTO:
        return "", "grande"
    try:
        with abrir_leitura(caminho) as arquivo:
            bruto = arquivo.read(_LIMITE_TEXTO + 1)
    except OSError:
        return "", "arquivo"
    if len(bruto) > _LIMITE_TEXTO:
        return "", "grande"
    try:
        texto = texto_de_bytes(bruto)
    except UnicodeError:
        return "", "codificacao"
    return sanitizar(texto) + ("\n" if texto.endswith(("\n", "\r")) else ""), ""


def _parse_kindle(texto):
    bruto = sanitizar(texto)
    if "==========" not in bruto:
        return [], "formato"
    partes = re.split(r"(?m)^={10,}\s*$", bruto)
    grupos = {}
    ordem = []
    viu_meta = False
    for parte in partes:
        linhas = [linha.rstrip() for linha in parte.split("\n")]
        while linhas and not linhas[0].strip():
            linhas.pop(0)
        while linhas and not linhas[-1].strip():
            linhas.pop()
        if len(linhas) < 2 or not _e_meta(linhas[1]):
            continue
        viu_meta = True
        titulo, autor = _separar_titulo(linhas[0])
        if not titulo:
            continue
        tipo = _tipo_kindle(linhas[1])
        if not tipo:
            continue
        corpo = "\n".join(linhas[2:]).strip()
        pagina = _primeiro_int(_PAGINA, linhas[1])
        posicao = _primeiro_int(_POS, linhas[1])
        chave = titulo + "\n" + autor
        if chave not in grupos:
            grupos[chave] = []
            ordem.append((titulo, autor, chave))
        grupos[chave].append(
            Trecho(corpo, pagina=pagina, posicao=posicao, tipo=tipo)
        )
    if not viu_meta:
        return [], "formato"
    livros = []
    for titulo, autor, chave in ordem:
        trechos = _juntar_notas(grupos[chave])
        if trechos:
            livros.append(Livro(titulo, autor, "kindle", trechos[:_MAX_TRECHOS]))
    if not livros:
        return [], "vazio"
    return livros, ""


def _e_meta(linha):
    texto = (linha or "").strip()
    if not texto:
        return False
    return texto[0] == "-" or ord(texto[0]) in (0x2013, 0x2014)


def _tipo_kindle(meta):
    from .routines import fold

    cabeca = fold(meta.split("|", 1)[0])
    if re.search(r"\b(bookmark|marcador)\b", cabeca):
        return ""
    if re.search(r"\b(note|nota)\b", cabeca):
        return "nota"
    if "highlight" in cabeca or "destaque" in cabeca:
        return "destaque"
    return ""


def _juntar_notas(trechos):
    por_posicao = {}
    saida = []
    for trecho in trechos:
        if trecho.tipo == "nota" and trecho.posicao and trecho.posicao in por_posicao:
            alvo = por_posicao[trecho.posicao]
            if not alvo.nota and trecho.texto:
                alvo.nota = trecho.texto
                continue
        saida.append(trecho)
        if trecho.tipo == "destaque" and trecho.posicao:
            por_posicao[trecho.posicao] = trecho
    return [item for item in saida if item.texto or item.nota]


def _parse_koreader(texto, caminho):
    sufixo = Path(caminho).suffix.casefold()
    if sufixo == ".json" or texto.lstrip().startswith(("{", "[")):
        livros, codigo = _parse_json(texto)
        if livros or codigo == "vazio" or sufixo == ".json":
            return livros, codigo
    if sufixo == ".lua" or "return" in texto[:200] or "[\"annotations\"]" in texto or "['annotations']" in texto:
        livros, codigo = _parse_lua(texto)
        if livros or codigo == "vazio" or sufixo == ".lua":
            return livros, codigo
    if sufixo == ".md" or texto.lstrip().startswith("#"):
        return _parse_markdown(texto)
    return [], "formato"


def _parse_json(texto):
    try:
        carga = json.loads(texto)
    except json.JSONDecodeError:
        return [], "formato"
    brutos = carga if isinstance(carga, list) else [carga]
    if isinstance(carga, dict) and isinstance(carga.get("books"), list):
        brutos = carga["books"]
    livros = []
    for item in brutos:
        if not isinstance(item, dict):
            continue
        titulo = sanitizar(item.get("title") or item.get("document") or "")
        autor = sanitizar(item.get("author") or item.get("authors") or "")
        entradas = (
            item.get("entries")
            or item.get("highlights")
            or item.get("annotations")
            or []
        )
        trechos = _trechos_de_lista(entradas)
        if trechos:
            livros.append(Livro(titulo or "Sem título", autor, "koreader", trechos))
    if not livros:
        return [], "vazio" if isinstance(carga, (dict, list)) else "formato"
    return livros, ""


def _trechos_de_lista(entradas):
    if isinstance(entradas, dict):
        entradas = list(entradas.values())
    if not isinstance(entradas, list):
        return []
    trechos = []
    for item in entradas:
        if not isinstance(item, dict):
            continue
        tipo = _tipo_drawer(item.get("drawer") or item.get("type") or item.get("style"))
        if not tipo:
            continue
        texto = sanitizar(item.get("text") or item.get("content") or item.get("highlight") or "")
        nota = sanitizar(item.get("note") or item.get("annotation") or item.get("comment") or "")
        pagina = _inteiro(item.get("page") or item.get("pageno") or item.get("page_number"))
        if tipo == "nota" and not texto:
            trechos.append(Trecho("", nota, pagina=pagina, tipo="nota"))
        elif texto or nota:
            trechos.append(Trecho(texto, nota, pagina=pagina, tipo="destaque"))
        if len(trechos) >= _MAX_TRECHOS:
            break
    return [item for item in trechos if item.texto or item.nota]


def _tipo_drawer(valor):
    from .routines import fold

    nome = fold(str(valor or ""))
    if not nome:
        return "destaque"
    if "bookmark" in nome or "marcador" in nome or "strike" in nome:
        return ""
    if nome in {"note", "nota"}:
        return "nota"
    if nome in {"highlight", "underline", "underscore", "lighten", "invert", "destaque", "squiggly"}:
        return "destaque"
    return ""


def _parse_lua(texto):
    try:
        tabela = _Lua(texto).parse()
    except _LuaErro:
        return [], "formato"
    if not isinstance(tabela, dict):
        return [], "formato"
    titulo, autor = _meta_lua(tabela)
    trechos = []
    for chave in ("annotations", "highlight", "highlights"):
        trechos.extend(_trechos_lua(tabela.get(chave)))
    trechos = trechos[:_MAX_TRECHOS]
    if not trechos:
        return [], "vazio"
    return [Livro(titulo, autor, "koreader", trechos)], ""


def _meta_lua(tabela):
    titulo = ""
    autor = ""
    for chave in ("doc_props", "stats", "doc_settings"):
        bloco = tabela.get(chave)
        if not isinstance(bloco, dict):
            continue
        titulo = titulo or sanitizar(bloco.get("title") or bloco.get("display_title") or "")
        autor = autor or sanitizar(bloco.get("authors") or bloco.get("author") or "")
    return titulo or "Sem título", autor


def _trechos_lua(bloco):
    trechos = []
    for item in _valores(bloco):
        if not isinstance(item, dict):
            continue
        tipo = _tipo_drawer(item.get("drawer"))
        if not tipo:
            continue
        texto = sanitizar(item.get("text") or "")
        nota = sanitizar(item.get("note") or "")
        pagina = _inteiro(item.get("pageno") if item.get("pageno") is not None else item.get("page"))
        if tipo == "nota" and not texto:
            trechos.append(Trecho("", nota, pagina=pagina, tipo="nota"))
        elif texto or nota:
            trechos.append(Trecho(texto, nota, pagina=pagina, tipo="destaque"))
    return [item for item in trechos if item.texto or item.nota]


def _parse_markdown(texto):
    linhas = sanitizar(texto).split("\n")
    titulo = ""
    autor = ""
    blocos = []
    atual = []
    for linha in linhas:
        faixa = linha.strip()
        if faixa == "---" and atual:
            blocos.append(atual)
            atual = []
            continue
        if not titulo and faixa.startswith("#"):
            titulo = faixa.lstrip("#").strip()
            continue
        if titulo and faixa.startswith("#"):
            continue
        if not autor:
            par = re.match(r"(?i)^(?:autor|author)\s*:\s*(.+)$", faixa)
            if par:
                autor = par.group(1).strip()
                continue
            estrela = re.match(r"^\*([^*]+)\*$", faixa)
            if estrela:
                autor = estrela.group(1).strip()
                continue
        atual.append(linha)
    if atual:
        blocos.append(atual)
    trechos = []
    viu_citacao = False
    for bloco in blocos:
        trecho, citacao = _trecho_markdown(bloco)
        viu_citacao = viu_citacao or citacao
        if trecho is not None:
            trechos.append(trecho)
    if not viu_citacao:
        return [], "formato"
    if not trechos:
        return [], "vazio"
    return [Livro(titulo or "Sem título", autor, "koreader", trechos[:_MAX_TRECHOS])], ""


def _trecho_markdown(linhas):
    citacoes = []
    nota = ""
    pagina = None
    citacao = False
    for bruta in linhas:
        faixa = bruta.strip()
        if faixa.startswith(">"):
            citacao = True
            citacoes.append(faixa[1:].lstrip())
            continue
        pagina_md = _PAGINA_MD.match(faixa)
        if pagina_md:
            pagina = int(pagina_md.group(1))
            continue
        nota_md = _NOTA_MD.match(faixa)
        if nota_md:
            nota = sanitizar(nota_md.group(1))
    texto = sanitizar("\n".join(citacoes))
    from .routines import fold

    if fold(texto) in {"bookmark", "marcador"}:
        return None, citacao
    if not texto and not nota:
        return None, citacao
    return Trecho(texto, nota, pagina=pagina, tipo="destaque"), citacao


def _leitor_pdf():
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    return PdfReader


def _parse_pdf(caminho):
    from .paths import caminho_de_abertura, tamanho_arquivo

    leitor = _leitor_pdf()
    if leitor is None:
        return [], "pypdf"
    try:
        tamanho = tamanho_arquivo(caminho)
    except OSError:
        return [], "arquivo"
    if tamanho > _LIMITE_PDF:
        return [], "grande"
    try:
        reader = leitor(caminho_de_abertura(caminho))
        if getattr(reader, "is_encrypted", False):
            return [], "protegido"
        meta = reader.metadata
        titulo = sanitizar(getattr(meta, "title", "") or "") if meta is not None else ""
        autor = sanitizar(getattr(meta, "author", "") or "") if meta is not None else ""
        paginas = reader.pages
        try:
            total = len(paginas)
        except Exception:
            return [], "ilegivel"
        if total > _MAX_PAGINAS:
            return [], "grande"
        trechos = []
        vistas = 0
        for indice, page in enumerate(paginas, start=1):
            if indice > _MAX_PAGINAS:
                break
            bruto = page.get("/Annots") or []
            if not isinstance(bruto, list):
                bruto = [bruto]
            for anotacao in bruto:
                vistas += 1
                if vistas > _MAX_ANOTACOES:
                    break
                obj = anotacao.get_object() if hasattr(anotacao, "get_object") else anotacao
                trecho = _anotacao_pdf(page, obj, indice)
                if trecho is not None:
                    trechos.append(trecho)
                if len(trechos) >= _MAX_TRECHOS:
                    break
            if vistas > _MAX_ANOTACOES or len(trechos) >= _MAX_TRECHOS:
                break
    except Exception:
        LOG.error("destaques: pdf ilegivel")
        return [], "ilegivel"
    if not titulo:
        titulo = sanitizar(Path(caminho).stem) or "Sem título"
    if not trechos:
        return [], "vazio"
    return [Livro(titulo, autor, "pdf", trechos)], ""


def _texto_pdf(valor):
    if isinstance(valor, (bytes, bytearray)):
        texto = bytes(valor).decode("utf-8", errors="replace")
    else:
        texto = str(valor or "")
    return sanitizar(texto)[:_MAX_CONTEUDO]


def _anotacao_pdf(page, obj, numero):
    if not hasattr(obj, "get"):
        return None
    subtipo = str(obj.get("/Subtype") or "")
    conteudo = _texto_pdf(obj.get("/Contents") or "")
    if subtipo in {"/Link", "/Popup", "/Widget", "/StrikeOut"}:
        return None
    if subtipo in {"/Text", "/FreeText"}:
        if not conteudo:
            return None
        return Trecho("", conteudo, pagina=numero, tipo="nota")
    if subtipo not in {"/Highlight", "/Underline", "/Squiggly"}:
        return None
    extraido = ""
    if "/QuadPoints" in obj:
        extraido = _texto_pdf(_texto_quadros(page, obj.get("/QuadPoints")))
    if extraido and conteudo and _igual_folha(extraido, conteudo):
        conteudo = ""
    if extraido and conteudo:
        return Trecho(extraido, conteudo, pagina=numero, tipo="destaque")
    texto = extraido or conteudo
    if not texto:
        return None
    return Trecho(texto, "", pagina=numero, tipo="destaque")


def _texto_quadros(page, quads):
    caixas = _caixas(quads)
    if not caixas:
        return ""
    partes = []

    def visitar(text, _cm, tm, _fonte, _tamanho):
        if not text or not str(text).strip():
            return
        try:
            x = float(tm[4])
            y = float(tm[5])
        except (TypeError, ValueError, IndexError):
            return
        for x0, y0, x1, y1 in caixas:
            if (x0 - 4) <= x <= (x1 + 4) and (y0 - 4) <= y <= (y1 + 4):
                partes.append(str(text))
                return

    try:
        page.extract_text(visitor_text=visitar)
    except Exception:
        return ""
    return "".join(partes)


def _caixas(quads):
    numeros = []
    for item in quads or []:
        if len(numeros) >= 8000:
            break
        try:
            numeros.append(float(item))
        except (TypeError, ValueError):
            continue
    caixas = []
    for indice in range(0, len(numeros) - 7, 8):
        xs = numeros[indice : indice + 8 : 2]
        ys = numeros[indice + 1 : indice + 8 : 2]
        caixas.append((min(xs), min(ys), max(xs), max(ys)))
    return caixas


def _aplicar(root, relativa, livros):
    from .guardas import GuardError, escrever, texto_secreto
    from .leitura import ler_texto
    from .privacidade import nota_sigilosa

    pasta = Path(root) / relativa
    stats = {"criados": 0, "atualizados": 0, "notas": 0, "recusados": 0}
    novos = []
    for livro in _mesclar(livros):
        if _recusar_meta(livro, texto_secreto):
            stats["recusados"] += max(1, len(livro.trechos))
            _recusa("segredo")
            continue
        chave = chave_livro(livro.titulo, livro.autor)
        destino, existente = _achar(pasta, chave)
        if destino is not None and nota_sigilosa(root, _relativo(root, destino), existente):
            stats["recusados"] += len(livro.trechos) or 1
            _recusa("sigilo")
            continue
        blocos, ordem = _blocos(existente)
        criados = 0
        atualizados = 0
        ids_novos = []
        for trecho in livro.trechos:
            if _recusar_trecho(trecho, texto_secreto):
                stats["recusados"] += 1
                _recusa("segredo")
                continue
            identificar(trecho)
            if not trecho.id:
                continue
            render = _render_trecho(trecho)
            anterior = blocos.get(trecho.id)
            if anterior is None:
                blocos[trecho.id] = render
                ordem.append(trecho.id)
                criados += 1
                ids_novos.append(trecho.id)
                continue
            if _sem_rascunho(anterior) == render:
                continue
            mantidos = _linhas_rascunho(anterior)
            blocos[trecho.id] = render if not mantidos else render + "\n\n" + "\n".join(mantidos)
            atualizados += 1
        if criados == 0 and atualizados == 0:
            continue
        if existente:
            livro.fontes.update(_fontes_gravadas(existente))
        corpo = _render_nota(livro, chave, blocos, ordem, existente)
        relativo = relativa + "/" + (destino.name if destino is not None else "nota.md")
        if not corpo.strip() or texto_secreto(corpo) or nota_sigilosa(root, relativo, corpo):
            stats["recusados"] += criados or 1
            _recusa("segredo")
            continue
        if destino is None:
            destino = pasta / _nome_arquivo(livro, chave, pasta)
        if destino.is_symlink() or not _dentro(root, destino):
            stats["recusados"] += 1
            _recusa("fora")
            continue
        if destino.is_file():
            try:
                fresco = ler_texto(destino)
            except (OSError, UnicodeError):
                fresco = ""
            if nota_sigilosa(root, _relativo(root, destino), fresco):
                stats["recusados"] += criados or 1
                _recusa("sigilo")
                continue
        try:
            escrever(destino, corpo, raiz=Path(root))
        except GuardError:
            stats["recusados"] += 1
            continue
        stats["criados"] += criados
        stats["atualizados"] += atualizados
        stats["notas"] += 1
        novos.extend(ids_novos)
    return stats, novos


def _aplicar_cartoes(root, relativa, ids):
    from .guardas import GuardError, escrever, texto_secreto
    from .leitura import ler_texto
    from .privacidade import nota_sigilosa

    queridos = [item for item in ids if isinstance(item, str) and _ID.match(item)]
    if not queridos:
        return 0
    pasta = Path(root) / relativa
    if not pasta.is_dir():
        return 0
    gravados = 0
    for caminho in sorted(pasta.glob("*.md")):
        if not caminho.is_file() or caminho.is_symlink():
            continue
        try:
            atual = ler_texto(caminho)
        except (OSError, UnicodeError):
            continue
        relativo = _relativo(root, caminho)
        if nota_sigilosa(root, relativo, atual):
            _recusa("sigilo")
            continue
        novo, quantidade, linhas = _inserir_cartoes(atual, queridos)
        if quantidade == 0:
            continue
        if texto_secreto(novo) or nota_sigilosa(root, relativo, novo):
            _recusa("segredo")
            continue
        try:
            escrever(caminho, novo, checar="\n".join(linhas), raiz=Path(root))
        except GuardError:
            continue
        gravados += quantidade
    if gravados:
        LOG.info("destaques cartoes=%s", gravados)
    return gravados


def _gravar_oferta_cartoes(root, ids):
    from .guardas import GuardError
    from .trava import TravaOcupada, fila_escrita

    relativa, problema = _preparar_pasta(root)
    if problema:
        return problema
    try:
        with fila_escrita():
            gravados = _aplicar_cartoes(root, relativa, ids)
    except GuardError:
        return ESCRITA_BLOQUEADA
    except TravaOcupada:
        return OCUPADO
    except OSError:
        LOG.error("destaques: escrita falhou")
        return ESCRITA_BLOQUEADA
    if not gravados:
        return "Não gravei cartão, senhor. Não havia destaque novo disponível."
    return _fala_cartoes(gravados)


def _inserir_cartoes(texto, ids):
    queridos = set(ids)
    linhas = []
    total = 0

    def trocar(match):
        nonlocal total
        identificador = match.group(1)
        corpo = match.group(2).strip("\n")
        if identificador not in queridos or _linhas_rascunho(corpo):
            return match.group(0)
        destaque, nota, _pagina = _partes_bloco(corpo)
        linha = _linha_cartao(destaque, nota)
        if not linha:
            return match.group(0)
        total += 1
        linhas.append(linha)
        return "<!-- dt:%s -->\n%s\n\n%s\n<!-- /dt -->" % (identificador, corpo, linha)

    novo = _BLOCO.sub(trocar, _normalizar(texto))
    if not novo.endswith("\n"):
        novo += "\n"
    return novo, total, linhas


def _linha_cartao(texto, nota):
    from .guardas import texto_secreto

    base = " ".join((texto or "").split())
    resposta = " ".join((nota or "").split()) or base
    if not base:
        base = resposta
    if not base or not resposta:
        return ""
    if len(base) > 220:
        base = base[:217].rstrip() + "..."
    if len(resposta) > 300:
        resposta = resposta[:297].rstrip() + "..."
    pergunta = ("O que este destaque registra: " + base).replace(":::", " ")
    resposta = resposta.replace(":::", " ")
    if texto_secreto(pergunta) or texto_secreto(resposta):
        return ""
    if _sigilo(pergunta) or _sigilo(resposta):
        return ""
    return "- [rascunho] " + pergunta + " ::: " + resposta


def _partes_bloco(corpo):
    texto = []
    nota = []
    pagina = None
    for linha in (corpo or "").split("\n"):
        if _linhas_rascunho(linha):
            continue
        pagina_linha = re.fullmatch(r"Página (\d+)\.", linha.strip())
        if pagina_linha:
            pagina = int(pagina_linha.group(1))
            continue
        if linha.startswith("> "):
            texto.append(linha[2:])
        elif linha == ">":
            texto.append("")
        elif linha.strip():
            nota.append(linha.strip())
    return "\n".join(texto).strip(), "\n".join(nota).strip(), pagina


def _render_trecho(trecho):
    corpo = trecho.texto or trecho.nota
    linhas = []
    for linha in corpo.split("\n"):
        linhas.append("> " + linha if linha else ">")
    if trecho.pagina:
        linhas.append("")
        linhas.append("Página %d." % trecho.pagina)
    if trecho.texto and trecho.nota:
        linhas.append("")
        linhas.append(trecho.nota)
    return "\n".join(linhas).strip("\n")


def _render_nota(livro, chave, blocos, ordem, anterior=""):
    titulo = _campo(anterior, "title") or " ".join(livro.titulo.split()) or "Sem título"
    autor = _campo(anterior, "author")
    if autor is None:
        autor = " ".join(livro.autor.split())
    fonte = _campo(anterior, "source") or _fonte_exibicao(livro)
    etiquetas = sorted(livro.fontes | {"leitura"})
    linhas = [
        "---",
        "title: " + _yaml(titulo),
        "author: " + _yaml(autor),
        "source: " + _yaml(fonte),
        "url: \"\"",
        "tags:",
    ]
    for etiqueta in etiquetas:
        linhas.append("  - " + _yaml(etiqueta))
    linhas.append("destaques_chave: " + _yaml(chave))
    linhas.extend(["---", "", "# " + titulo.replace("\n", " "), ""])
    for identificador in ordem:
        if identificador not in blocos:
            continue
        linhas.append("<!-- dt:%s -->" % identificador)
        linhas.append(blocos[identificador].strip("\n"))
        linhas.append("<!-- /dt -->")
        linhas.append("")
    return "\n".join(linhas).rstrip() + "\n"


def _blocos(texto):
    blocos = {}
    ordem = []
    for match in _BLOCO.finditer(_normalizar(texto)):
        identificador = match.group(1)
        if identificador in blocos:
            continue
        blocos[identificador] = match.group(2).strip("\n")
        ordem.append(identificador)
    return blocos, ordem


def _achar(pasta, chave):
    from .leitura import ler_texto

    if not pasta.is_dir():
        return None, ""
    marca = "destaques_chave: " + _yaml(chave)
    for caminho in sorted(pasta.glob("*.md")):
        if not caminho.is_file() or caminho.is_symlink():
            continue
        try:
            texto = ler_texto(caminho)
        except (OSError, UnicodeError):
            continue
        frente = _frente(texto)
        if any(linha.strip() == marca for linha in frente.splitlines()):
            return caminho, texto
    return None, ""


def _campo(texto, nome):
    prefixo = nome + ":"
    for linha in _frente(texto).splitlines():
        if not linha.startswith(prefixo):
            continue
        valor = linha.split(":", 1)[1].strip()
        if len(valor) >= 2 and valor[0] == '"' and valor[-1] == '"':
            valor = valor[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return valor
    return None


def _fontes_gravadas(texto):
    from .routines import fold

    achadas = set()
    for linha in _frente(texto).splitlines():
        faixa = linha.strip()
        if faixa.startswith("source:"):
            valor = _campo(texto, "source") or ""
        elif faixa.startswith("- "):
            valor = faixa[2:].strip().strip('"')
        else:
            continue
        chave = fold(valor)
        if chave in _FONTES:
            achadas.add(chave)
    return achadas


def _frente(texto):
    bruto = _normalizar(texto)
    if not bruto.startswith("---\n"):
        return ""
    fim = bruto.find("\n---", 4)
    if fim == -1:
        return ""
    return bruto[4:fim]


def _nome_arquivo(livro, chave, pasta):
    base = _slug(livro.titulo)
    autor = _slug(livro.autor)
    extras = [""]
    if autor and autor != base:
        extras.append("-" + autor)
    extras.append("-" + hashlib.sha256(chave.encode("utf-8")).hexdigest()[:6])
    for extra in extras:
        nome = (base + extra).strip("-") or "leitura"
        candidato = nome + ".md"
        if not (pasta / candidato).exists():
            return candidato
    return base + "-leitura.md"


def _slug(texto):
    from .routines import fold

    slug = re.sub(r"[^a-z0-9]+", "-", fold(texto or "")).strip("-")[:48].strip("-")
    if slug in _RESERVADOS:
        slug = slug + "-livro"
    return slug or "leitura"


def _mesclar(livros):
    ordem = []
    grupos = {}
    for livro in livros:
        if not isinstance(livro, Livro):
            continue
        chave = chave_livro(livro.titulo, livro.autor)
        if chave not in grupos:
            grupos[chave] = Livro(livro.titulo, livro.autor, livro.fonte, [])
            ordem.append(chave)
        atual = grupos[chave]
        atual.fontes.update(livro.fontes)
        if len(_limpar_edicao(livro.titulo)) < len(_limpar_edicao(atual.titulo)):
            atual.titulo = livro.titulo
        if livro.autor and (not atual.autor or ("," in atual.autor and "," not in livro.autor)):
            atual.autor = livro.autor
        atual.trechos.extend(livro.trechos)
    saida = []
    for chave in ordem:
        livro = grupos[chave]
        livro.titulo = _limpar_edicao(livro.titulo) or livro.titulo
        livro.trechos = _dedupar(livro.trechos)
        if livro.trechos:
            saida.append(livro)
    return saida


def _dedupar(trechos):
    ordem = []
    por_id = {}
    for trecho in trechos:
        if not trecho.texto and not trecho.nota:
            continue
        identificar(trecho)
        if not trecho.id:
            continue
        anterior = por_id.get(trecho.id)
        if anterior is None:
            por_id[trecho.id] = trecho
            ordem.append(trecho.id)
        elif trecho.nota and not anterior.nota:
            anterior.nota = trecho.nota
        elif trecho.pagina and not anterior.pagina:
            anterior.pagina = trecho.pagina
    return [por_id[item] for item in ordem][:_MAX_TRECHOS]


def _separar_titulo(linha):
    texto = " ".join((linha or "").split())
    autor = ""
    while True:
        achado = re.search(r"\s*\(([^()]*)\)\s*$", texto)
        if not achado:
            break
        miolo = achado.group(1).strip()
        texto = texto[: achado.start()].rstrip()
        if _eh_edicao(miolo):
            continue
        if not autor and miolo:
            autor = miolo
            continue
        texto = (texto + " (" + miolo + ")").strip()
        break
    return _limpar_edicao(texto), autor


def _eh_edicao(texto):
    return bool(_EDICAO.search(" " + (texto or "").strip() + " "))


def _limpar_edicao(titulo):
    texto = sanitizar(titulo)
    texto = _EDICAO.sub(" ", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" :-")
    return texto


def _autor_norm(autor):
    from .routines import fold

    texto = " ".join((autor or "").split())
    if texto.count(",") == 1:
        esquerda, direita = [parte.strip() for parte in texto.split(",")]
        if esquerda and direita:
            texto = direita + " " + esquerda
    return fold(texto)


def _fonte_exibicao(livro):
    ordem = [fonte for fonte in ("kindle", "pdf", "koreader") if fonte in livro.fontes]
    return ordem[0] if ordem else livro.fonte


def _normalizar(texto):
    bruto = texto or ""
    if bruto.startswith("\ufeff"):
        bruto = bruto[1:]
    return bruto.replace("\r\n", "\n").replace("\r", "\n")


def _sem_rascunho(corpo):
    linhas = [linha for linha in (corpo or "").split("\n") if not _linhas_rascunho(linha)]
    while linhas and not linhas[-1].strip():
        linhas.pop()
    return "\n".join(linhas).strip("\n")


def _linhas_rascunho(corpo):
    return [
        linha
        for linha in (corpo or "").split("\n")
        if "[rascunho]" in linha.casefold() and ":::" in linha
    ]


def _yaml(valor):
    texto = " ".join(sanitizar(valor).split())
    texto = texto.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + texto + '"'


def _recusar_meta(livro, texto_secreto):
    return (
        texto_secreto(livro.titulo)
        or texto_secreto(livro.autor)
        or _sigilo(livro.titulo)
        or _sigilo(livro.autor)
    )


def _recusar_trecho(trecho, texto_secreto):
    return (
        texto_secreto(trecho.texto)
        or texto_secreto(trecho.nota)
        or _sigilo(trecho.texto)
        or _sigilo(trecho.nota)
    )


def _sigilo(texto):
    from .privacidade import nota_sigilosa

    if not str(texto or "").strip():
        return False
    return nota_sigilosa(None, "destaque.md", texto)


def _titulo_seguro(titulo, texto_secreto):
    texto = " ".join(sanitizar(titulo).split())[:80]
    if not texto or texto_secreto(texto) or _sigilo(texto):
        return ""
    return texto


def _fala_previa(livros, novos, recusados, nomes):
    if novos <= 0:
        return _com_recusa(NADA_NOVO, recusados)
    fala = "Encontrei %s e %s, senhor." % (
        _contagem(livros, "livro", "livros"),
        _contagem(novos, "destaque novo", "destaques novos"),
    )
    if nomes:
        fala += " " + _juntar_nomes(nomes) + "."
    fala += " Confirma a importação?"
    return _com_recusa(fala, recusados)


def _fala_gravou(stats, oferecer):
    criados = stats["criados"]
    atualizados = stats["atualizados"]
    notas = stats["notas"]
    if criados == 0 and atualizados == 0:
        fala = NADA_NOVO
    else:
        partes = []
        if criados:
            partes.append("importei " + _contagem(criados, "destaque", "destaques"))
        if atualizados:
            partes.append("atualizei %d" % atualizados)
        corpo = " e ".join(partes)
        fala = corpo[:1].upper() + corpo[1:]
        fala += " em %s, senhor." % _contagem(notas, "nota", "notas")
    if oferecer and criados:
        fala += " Quer cartões em rascunho para os destaques novos?"
    return _com_recusa(fala, stats["recusados"])


def _fala_cartoes(quantidade):
    return (
        "Gravei %s em rascunho, senhor. Diga revisa rascunhos para conferir."
        % _contagem(quantidade, "cartão", "cartões")
    )


def _contagem(valor, um, varios):
    if valor == 1:
        return "1 " + um
    return "%d %s" % (valor, varios)


def _juntar_nomes(nomes):
    mostrados = nomes[:4]
    if len(mostrados) == 1:
        texto = mostrados[0]
    elif len(mostrados) == 2:
        texto = mostrados[0] + " e " + mostrados[1]
    else:
        texto = ", ".join(mostrados[:-1]) + " e " + mostrados[-1]
    resto = len(nomes) - len(mostrados)
    if resto == 1:
        texto += " e mais 1"
    elif resto > 1:
        texto += " e mais %d" % resto
    return texto


def _com_recusa(fala, recusados):
    if not recusados:
        return fala
    extra = " Um trecho foi recusado." if recusados == 1 else " Trechos foram recusados."
    return fala + extra


def _acrescentar(fala, extra):
    if not extra:
        return fala
    base = (fala or "").rstrip()
    if not base:
        return extra
    return base + " " + extra


def _fala_codigo(codigo):
    return {
        "pypdf": FALTA_PYPDF,
        "arquivo": FALTA_ARQUIVO,
        "bloqueado": ARQUIVO_BLOQUEADO,
        "atalho": ATALHO,
        "formato": FORMATO,
        "vazio": VAZIO,
        "grande": GRANDE,
        "codificacao": CODIFICACAO,
        "ilegivel": PDF_ILEGIVEL,
        "protegido": PDF_PROTEGIDO,
    }.get(codigo, FORMATO)


def _recusa(codigo):
    permitidos = {"obsidian", "credencial", "fora", "vazio", "segredo", "sigilo", "bloqueada"}
    LOG.info("escrita recusada: %s", codigo if codigo in permitidos else "bloqueada")


def _origem_segura(caminho):
    from .guardas import caminho_bloqueado
    from .paths import e_arquivo_regular, e_atalho

    alvo = Path(caminho)
    try:
        if e_atalho(alvo):
            return None, ATALHO
        if not e_arquivo_regular(alvo):
            return None, FALTA_ARQUIVO
    except OSError:
        return None, FALTA_ARQUIVO
    if caminho_bloqueado(alvo) or _tem_obsidian(alvo):
        return None, ARQUIVO_BLOQUEADO
    return alvo, ""


def _tem_obsidian(caminho):
    return any(parte == ".obsidian" for parte in Path(caminho).parts)


def _dentro(raiz, caminho):
    base = _resolvido(raiz)
    alvo = _resolvido(caminho)
    if base is None or alvo is None:
        return False
    try:
        alvo.relative_to(base)
    except ValueError:
        return False
    return True


def _resolvido(caminho):
    try:
        return Path(caminho).resolve()
    except OSError:
        return None


def _relativo(raiz, caminho):
    base = _resolvido(raiz)
    alvo = _resolvido(caminho)
    if base is None or alvo is None:
        return ""
    try:
        return alvo.relative_to(base).as_posix()
    except ValueError:
        return ""


def _inteiro(valor):
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return valor if valor > 0 else None
    if isinstance(valor, float) and valor.is_integer():
        numero = int(valor)
        return numero if numero > 0 else None
    if isinstance(valor, str) and valor.strip().isdigit():
        numero = int(valor.strip())
        return numero if numero > 0 else None
    return None


def _primeiro_int(padrao, texto):
    achado = padrao.search(texto or "")
    if not achado:
        return None
    return int(achado.group(1))


def _igual_folha(esquerda, direita):
    from .routines import fold

    return fold(" ".join(esquerda.split())) == fold(" ".join(direita.split()))


def _valores(bloco):
    if isinstance(bloco, dict):
        saida = list(bloco.get("_lista") or [])
        for chave, valor in bloco.items():
            if chave == "_lista":
                continue
            saida.append(valor)
        return saida
    if isinstance(bloco, list):
        return list(bloco)
    return []


class _LuaErro(Exception):
    pass


class _Lua:
    def __init__(self, texto):
        self.s = texto or ""
        self.n = len(self.s)
        self.i = 0
        self.prof = 0

    def parse(self):
        self._pular()
        if self._comeca("return") and self._fim_id(6):
            self.i += 6
            self._pular()
        valor = self._valor()
        return valor

    def _valor(self):
        self._pular()
        if self.i >= self.n:
            raise _LuaErro()
        char = self.s[self.i]
        if char == "{":
            return self._tabela()
        if char in {'"', "'"}:
            return self._curta()
        if char == "[":
            longo = self._longo()
            if longo is None:
                raise _LuaErro()
            return longo
        if char == "-" or char.isdigit():
            return self._numero()
        if self._comeca("true") and self._fim_id(4):
            self.i += 4
            return True
        if self._comeca("false") and self._fim_id(5):
            self.i += 5
            return False
        if self._comeca("nil") and self._fim_id(3):
            self.i += 3
            return None
        raise _LuaErro()

    def _tabela(self):
        if self.prof > 40:
            raise _LuaErro()
        self.prof += 1
        self.i += 1
        tabela = {"_lista": []}
        while True:
            self._pular()
            if self.i >= self.n:
                raise _LuaErro()
            if self.s[self.i] == "}":
                self.i += 1
                break
            chave, valor = self._campo()
            if chave is None:
                tabela["_lista"].append(valor)
            else:
                tabela[str(chave)] = valor
            self._pular()
            if self.i < self.n and self.s[self.i] in {",", ";"}:
                self.i += 1
        self.prof -= 1
        return tabela

    def _campo(self):
        self._pular()
        if self.s[self.i] == "[":
            seguinte = self.s[self.i + 1] if self.i + 1 < self.n else ""
            if seguinte in "[=":
                return None, self._valor()
            self.i += 1
            self._pular()
            chave = self._valor()
            self._pular()
            if self.i >= self.n or self.s[self.i] != "]":
                raise _LuaErro()
            self.i += 1
            self._pular()
            if self.i >= self.n or self.s[self.i] != "=":
                raise _LuaErro()
            self.i += 1
            return chave, self._valor()
        if self.s[self.i].isalpha() or self.s[self.i] == "_":
            inicio = self.i
            self.i += 1
            while self.i < self.n and (self.s[self.i].isalnum() or self.s[self.i] == "_"):
                self.i += 1
            nome = self.s[inicio : self.i]
            self._pular()
            if self.i < self.n and self.s[self.i] == "=":
                self.i += 1
                return nome, self._valor()
            raise _LuaErro()
        return None, self._valor()

    def _curta(self):
        aspas = self.s[self.i]
        self.i += 1
        partes = []
        while self.i < self.n:
            char = self.s[self.i]
            if char == aspas:
                self.i += 1
                return "".join(partes)
            if char == "\\":
                self.i += 1
                if self.i >= self.n:
                    raise _LuaErro()
                escapado = self.s[self.i]
                partes.append(
                    {
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                        "\\": "\\",
                        '"': '"',
                        "'": "'",
                    }.get(escapado, escapado)
                )
                self.i += 1
                continue
            partes.append(char)
            self.i += 1
        raise _LuaErro()

    def _longo(self):
        if self.s[self.i] != "[":
            return None
        nivel = 0
        j = self.i + 1
        while j < self.n and self.s[j] == "=":
            nivel += 1
            j += 1
        if j >= self.n or self.s[j] != "[":
            return None
        fecha = "]" + ("=" * nivel) + "]"
        inicio = j + 1
        fim = self.s.find(fecha, inicio)
        if fim < 0:
            raise _LuaErro()
        self.i = fim + len(fecha)
        return self.s[inicio:fim]

    def _numero(self):
        inicio = self.i
        if self.s[self.i] == "-":
            self.i += 1
        while self.i < self.n and self.s[self.i].isdigit():
            self.i += 1
        if self.i < self.n and self.s[self.i] == ".":
            self.i += 1
            while self.i < self.n and self.s[self.i].isdigit():
                self.i += 1
        bruto = self.s[inicio : self.i]
        if bruto in {"", "-", "."} or len(bruto) > 18:
            raise _LuaErro()
        if "." in bruto:
            return float(bruto)
        return int(bruto)

    def _pular(self):
        while self.i < self.n:
            if self.s[self.i].isspace():
                self.i += 1
                continue
            if self.s.startswith("--", self.i):
                self.i += 2
                if self.i < self.n and self.s[self.i] == "[":
                    longo = self._longo()
                    if longo is not None:
                        continue
                while self.i < self.n and self.s[self.i] not in "\n\r":
                    self.i += 1
                continue
            break

    def _comeca(self, palavra):
        return self.s.startswith(palavra, self.i)

    def _fim_id(self, tamanho):
        fim = self.i + tamanho
        if fim < self.n and (self.s[fim].isalnum() or self.s[fim] == "_"):
            return False
        return True
