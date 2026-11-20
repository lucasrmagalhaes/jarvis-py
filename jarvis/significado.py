"""Resposta do que as notas dizem, só com os trechos recuperados.

O trecho entra no cérebro como dado não confiável. A fala cita o título
com [[wikilink]] e diz quando as notas não cobrem a pergunta. Na voz a
resposta é curta e oferece mandar as fontes no Telegram. No texto vêm
as citações. As fontes são títulos, não o texto da nota.
"""

import re
from pathlib import Path

_NAO_COBRE = "As notas não cobrem isso"
_LINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]+)?(?:\|[^\[\]]+)?\]\]")
_FRASE = re.compile(r"(?<=[.!?])\s+")


def responder(root, pergunta, voz=False, embedder=None, cerebro=None, enviar=None):
    del enviar
    assunto = " ".join((pergunta or "").split())
    if len(assunto) < 2:
        return "Sobre o que, senhor?", None
    trechos, aviso = _trechos(root, assunto, embedder)
    trechos = _so_publicos(root, trechos)
    if aviso and not trechos:
        return aviso, None
    if not trechos:
        return _com_aviso(aviso, _NAO_COBRE + ", senhor."), None
    texto = ""
    modelo = cerebro if cerebro is not None else _cerebro_local()
    if modelo is not None:
        prompt = montar_prompt(assunto, trechos)
        try:
            bruto = modelo(prompt)
        except Exception:
            bruto = ""
        texto = _validar(bruto, trechos)
    if not texto:
        texto = _extrair(assunto, trechos)
    if not texto or _nao_cobre(texto):
        return _com_aviso(aviso, _NAO_COBRE + ", senhor."), None
    texto = _com_aviso(aviso, texto)
    fontes = _fontes(trechos)
    if not fontes:
        return _com_aviso(aviso, _NAO_COBRE + ", senhor."), None
    if voz:
        curta = _encurtar(_primeira(texto))
        fala = curta + " Quer que eu mande as fontes no Telegram?"
        return fala, {"kind": "fontes_notas", "fontes": fontes}
    if "Fontes:" not in texto:
        citadas = ", ".join("[[" + item["titulo"] + "]]" for item in fontes)
        texto = texto.rstrip() + " Fontes: " + citadas + "."
    return texto, None


def montar_prompt(pergunta, trechos):
    from .privacidade import destino_atual, prompt_do_turno

    blocos = []
    for trecho in trechos:
        corpo = trecho.texto or ""
        if trecho.heading:
            corpo = trecho.heading + "\n" + corpo
        blocos.append(
            {
                "origem": trecho.titulo or "nota",
                "texto": corpo,
                "sigiloso": False,
            }
        )
    pedido = (
        "Responda somente com o que está nos blocos. "
        "Cite cada nota usada como [[titulo]], com o título exato. "
        "Se os blocos não cobrem a pergunta, responda exatamente: As notas não cobrem isso. "
        "Não invente. Pergunta: " + " ".join((pergunta or "").split())
    )
    return prompt_do_turno(pedido, blocos, destino_atual())


def enviar_fontes(fontes, enviar=None):
    from .privacidade import modo_privado_ativo, texto_para_telegram

    if modo_privado_ativo():
        return "O modo privado está ativo, senhor. Não enviei as fontes."
    linhas = ["Fontes das notas, senhor."]
    for item in fontes or []:
        if not isinstance(item, dict):
            continue
        titulo = _titulo_limpo(item.get("titulo") or "")
        if not titulo or "texto" in item or "text" in item:
            continue
        linhas.append("[[" + titulo + "]]")
    if len(linhas) == 1:
        return "Não há fonte para enviar, senhor."
    texto = texto_para_telegram("\n".join(linhas))
    if not texto:
        return "Não enviei as fontes, senhor."
    chamada = enviar if enviar is not None else _enviar_telegram
    try:
        ok = chamada(texto)
    except Exception:
        return "Não consegui enviar as fontes no Telegram, senhor."
    if not ok:
        return "O Telegram não está pronto, senhor. Não enviei as fontes."
    return "Mandei as fontes no Telegram, senhor."


def _so_publicos(root, trechos):
    """Relê a nota. Se ela ficou sigilosa, o trecho não entra na resposta."""
    from .leitura import ler_texto
    from .paths import caminho_relativo
    from .privacidade import nota_sigilosa

    saida = []
    for trecho in trechos or []:
        caminho = str(getattr(trecho, "caminho", "") or "").replace("\\", "/")
        seguro = caminho_relativo(caminho, exigir_md=True)
        if not seguro:
            continue
        arquivo = Path(root) / seguro
        try:
            if arquivo.is_symlink():
                continue
            texto = ler_texto(arquivo)
        except (OSError, UnicodeError):
            continue
        if nota_sigilosa(root, seguro, texto):
            continue
        saida.append(trecho)
    return saida


def _trechos(root, pergunta, embedder):
    from .semantica import (
        _PISO,
        _um_por_nota,
        buscar_trechos,
        embedder_da_busca,
        mensagem_dependencia,
        mensagem_falha,
        modo,
    )
    from .busca import parse_scope
    from .routines import hybrid_notes

    atual = modo()
    lexical, pasta = parse_scope(pergunta)
    aviso = ""
    modelo = embedder
    semanticos = []
    if atual in {"semantica", "hibrida"}:
        if modelo is None:
            modelo = embedder_da_busca()
        if modelo is None:
            aviso = mensagem_dependencia()
        else:
            semanticos = buscar_trechos(
                root,
                lexical or pergunta,
                modelo,
                limite=6,
                pasta=pasta,
            )
            if semanticos is None:
                aviso = mensagem_falha(modelo)
                semanticos = []
    por_sentido = list(_um_por_nota(semanticos)[:4])
    if atual == "semantica" and por_sentido:
        return por_sentido, aviso
    hits = hybrid_notes(root, pergunta, embedder=None, limit=4)
    por_palavra = _de_hits(root, hits, lexical or pergunta, _PISO)
    if atual == "hibrida" and por_sentido:
        vistos = {item.caminho for item in por_sentido}
        extra = [item for item in por_palavra if item.caminho not in vistos]
        return (por_sentido + extra)[:4], aviso
    return por_palavra, aviso


def _de_hits(root, hits, pergunta, piso):
    from .catalogo import obter
    from .routines import fold
    from .semantica import Trecho, _publica, fatiar

    try:
        catalogo = obter(root)
    except Exception:
        return []
    tokens = _tokens(pergunta)
    achados = []
    for hit in hits or []:
        nota = catalogo.notas.get(str(hit.relative).replace("\\", "/"))
        if not _publica(root, nota):
            continue
        melhor = None
        for heading, plain in fatiar(nota.texto):
            if tokens and any(token in fold(plain) for token in tokens):
                melhor = (heading, plain)
                break
        if melhor is None:
            fatias = fatiar(nota.texto)
            if not fatias:
                continue
            melhor = fatias[0]
        achados.append(
            Trecho(
                str(hit.relative).replace("\\", "/"),
                hit.title,
                melhor[0],
                melhor[1],
                None,
                piso,
            )
        )
    return achados


def _cerebro_local():
    from .cerebro import cerebro_name, complete

    if cerebro_name() != "ollama":
        return None

    def responder_local(prompt):
        return complete(
            "Responda em português, só com os blocos, e cite [[titulo]].",
            prompt,
        )

    return responder_local


def _validar(bruto, trechos):
    texto = " ".join(str(bruto or "").replace("\u2014", ", ").replace("\u2013", ", ").split())
    if not texto:
        return ""
    if _nao_cobre(texto) and not _links_validos(texto, trechos):
        return _NAO_COBRE + ", senhor."
    frases = _FRASE.split(texto)
    boas = []
    for frase in frases:
        links = _links(frase)
        if links and _links_validos(frase, trechos):
            boas.append(frase.strip())
    if not boas:
        return ""
    return " ".join(boas)


def _extrair(pergunta, trechos):
    from .semantica import _PISO

    frases = []
    for trecho in trechos[:3]:
        frase = _frase_util(trecho.texto, pergunta, trecho.score, _PISO)
        titulo = _titulo_limpo(trecho.titulo)
        if not frase or not titulo:
            continue
        frases.append(frase + " [[" + titulo + "]].")
    return " ".join(frases)


def _frase_util(texto, pergunta, score, piso):
    from .routines import fold

    frases = _sentencas(texto)
    tokens = _tokens(pergunta)
    for frase in frases:
        folded = fold(frase)
        if tokens and any(token in folded for token in tokens):
            return frase
    if score >= piso and frases:
        return frases[0]
    return ""


def _sentencas(texto):
    bruto = " ".join(str(texto or "").replace("\u2014", " ").replace("\u2013", " ").split())
    partes = [parte.strip() for parte in _FRASE.split(bruto) if parte.strip()]
    return partes[:4]


def _tokens(texto):
    from .routines import SEARCH_STOP, fold

    found = []
    for token in fold(texto or "").split():
        if len(token) < 3 or token in SEARCH_STOP:
            continue
        if token not in found:
            found.append(token)
    return found


def _links(texto):
    achados = []
    for match in _LINK.finditer(texto or ""):
        titulo = _titulo_limpo(match.group(1))
        if titulo and titulo not in achados:
            achados.append(titulo)
    return achados


def _links_validos(texto, trechos):
    from .routines import fold

    conhecidos = {fold(item.titulo) for item in trechos if item.titulo}
    links = _links(texto)
    if not links:
        return False
    return all(fold(link) in conhecidos for link in links)


def _nao_cobre(texto):
    from .routines import fold

    return fold(_NAO_COBRE) in fold(texto or "")


def _fontes(trechos):
    fontes = []
    vistos = set()
    for trecho in trechos:
        titulo = _titulo_limpo(trecho.titulo)
        caminho = str(trecho.caminho or "").replace("\\", "/")
        if not titulo or not caminho or caminho in vistos:
            continue
        vistos.add(caminho)
        fontes.append({"titulo": titulo, "caminho": caminho})
    return fontes


def _titulo_limpo(titulo):
    limpo = " ".join(str(titulo or "").replace("[", " ").replace("]", " ").split())
    return limpo[:160]


def _primeira(texto):
    partes = _FRASE.split(texto or "")
    return (partes[0] if partes else "").strip()


def _encurtar(texto):
    if len(texto) <= 280:
        return texto
    cortado = texto[:280].rsplit(" ", 1)[0]
    return (cortado or texto[:280]).rstrip(".,;:") + "."


def _com_aviso(aviso, texto):
    if aviso and texto and not texto.startswith(aviso):
        return aviso + " " + texto
    return texto or aviso or ""


def _enviar_telegram(texto):
    from . import config
    from .telegram import TelegramRefused, build_bot

    if not config.telegram_ready():
        return False
    try:
        bot = build_bot(lambda _mensagem: None)
        return bool(bot.send_text(texto))
    except TelegramRefused:
        return False
