"""Liga notas de fontes diferentes, lembra um ponto antigo e guarda metas.

A fala e o mapa levam título, caminho e tipo de fonte. O texto da nota
não entra no arquivo de meta, no índice nem no log. Gravar mapa, link
ou nota de meta exige confirmação e passa pela validação da escrita.
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

from .busca import dense_cosine
from .guardas import FALA_BLOQUEIO, GuardError, escrever
from .log import LOG
from .routines import _join_pt, _without_frontmatter, fold, normalize_phrase

SEM_VAULT = (
    "O vault não está configurado, senhor. Sem ele eu não leio as notas. "
    "Rode python -m jarvis.setup."
)
LIMIAR_PAR = 0.82
LIMIAR_TEMA = 0.8
_IDADE_ANTIGA = 14
_COMANDOS = {"connect", "resurface", "learn", "progress"}
_ROTULO = {
    "livro": "livro",
    "video": "vídeo",
    "curso": "curso",
    "artigo": "artigo",
    "podcast": "podcast",
    "readwise": "Readwise",
    "nota": "nota",
}
_FONTES_ORDEM = (
    ("livro", "um livro"),
    ("curso", "um curso"),
    ("video", "um vídeo"),
)
_SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_PARADA = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "a",
    "o",
    "os",
    "as",
    "um",
    "uma",
    "no",
    "na",
    "em",
    "para",
    "pra",
    "com",
    "sobre",
    "que",
}
_GERADAS = {"resumo", "pontos", "cartoes", "ligacoes", "referencias", "fontes", "fonte"}
_PESSOAIS = {
    "meus pontos",
    "minhas notas",
    "anotacao",
    "anotacoes",
    "comentario",
    "comentarios",
    "o que eu acho",
    "nota pessoal",
    "eu escrevi",
}
_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$")
_INJECAO = re.compile(
    r"(?i)(ignore\s+as\s+instru|dado-nao-confiavel|</?dado|git\s+push|enviar\s+e-?mail)"
)
_DIA = re.compile(r"\d{4}-\d{2}-\d{2}")
_AMBOS = {
    "grava e liga",
    "grava o mapa e liga",
    "grava o mapa e liga as notas",
    "pode gravar e ligar",
    "sim e liga",
}
_LIGA = {
    "liga",
    "liga as notas",
    "liga as notas sim",
    "acrescenta os links",
    "pode ligar",
}
_MAPA = {
    "grava o mapa",
    "grava o mapa sim",
    "pode gravar o mapa",
    "cria o mapa",
    "grava",
    "grava sim",
}


def embedder_padrao():
    try:
        from .routines import _search_embedder

        modelo = _search_embedder()
    except Exception:
        modelo = None
    if modelo is not None:
        return modelo
    from .primeiro_uso import HashEmbedder

    return HashEmbedder()


def turno(root, intent, message, now, pending, embedder=None):
    kind = getattr(intent, "kind", "")
    ativo = isinstance(pending, dict) and pending.get("kind") == "conexao"
    if not ativo and kind not in _COMANDOS:
        return None
    if root is None:
        return ("reply", SEM_VAULT, None)
    if ativo and kind != "connect":
        if kind == "dismiss":
            return ("reply", "Deixei as ligações como estão, senhor.", None)
        acao = acao_da_frase(message)
        if kind != "chat" or not acao:
            return ("drop",)
        if acao == "nao":
            return ("reply", "Tudo bem, senhor. Não gravei ligações nem mapa.", None)
        return ("write", acao, pending)
    from .semantica import embedder_da_busca, ligada, mensagem_dependencia

    if ligada() and embedder is None and kind == "connect":
        modelo = embedder_da_busca()
        if modelo is None:
            return ("reply", mensagem_dependencia(), None)
    else:
        modelo = embedder if embedder is not None else embedder_padrao()
    if kind == "connect":
        fala, pendente = propor_conexoes(root, getattr(intent, "query", ""), modelo)
        return ("reply", fala, pendente)
    if kind == "resurface":
        return ("reply", fala_lembrete(root, now), None)
    if kind == "learn":
        fala, registro = preparar_meta(root, getattr(intent, "query", ""), now, modelo)
        if registro is None:
            return ("reply", fala, None)
        try:
            gravar_meta_local(registro)
        except Exception:
            LOG.info("meta local nao gravada")
            return ("reply", "Não consegui guardar a meta, senhor.", None)
        if _metas_no_vault():
            return ("write_meta", fala, registro)
        return ("reply", fala, None)
    if kind == "progress":
        tema = getattr(intent, "query", "")
        return ("reply", falar_progresso(root, tema, now, modelo), None)
    return None


def acao_da_frase(mensagem):
    from .routines import NO_WORDS, YES_WORDS

    texto = fold(normalize_phrase(mensagem or ""))
    if not texto:
        return ""
    if texto in _AMBOS:
        return "ambos"
    if texto in NO_WORDS:
        return "nao"
    if texto in _LIGA:
        return "liga"
    if texto in _MAPA or texto in YES_WORDS:
        return "mapa"
    return ""


def propor_conexoes(root, tema, embedder):
    notas = _com_vetores(root, _notas_publicas(root), embedder)
    if notas is None:
        return "Não consegui usar o índice de embeddings, senhor.", None
    assunto = _tema_limpo(tema)
    if assunto:
        notas = _do_tema(notas, assunto, embedder)
    grupo = _melhor_grupo(_pares(notas))
    if len(grupo) < 2:
        if assunto:
            return f"Não encontrei notas de fontes diferentes sobre {assunto}, senhor.", None
        return "Não encontrei notas de fontes diferentes sobre o mesmo assunto, senhor.", None
    titulo = _titulo_mapa(assunto, grupo)
    pares = _pares_do_grupo(grupo)
    fala = _fala_proposta(titulo, pares, grupo)
    pendente = {
        "kind": "conexao",
        "titulo": titulo,
        "notas": [_publico(nota) for nota in grupo],
        "pares": [{"a": par[0], "b": par[1]} for par in pares],
    }
    LOG.info("conexao proposta com %s notas", len(grupo))
    return fala, pendente


def aplicar_conexao(root, pendente, acao, now):
    if not isinstance(pendente, dict) or pendente.get("kind") != "conexao":
        return "Não há ligação pendente, senhor."
    notas = [item for item in (pendente.get("notas") or []) if _nota_pendente(item)]
    if len(notas) < 2:
        return "Não há notas suficientes para ligar, senhor."
    if acao not in {"mapa", "liga", "ambos"}:
        return "Tudo bem, senhor. Não gravei ligações nem mapa."
    mapa = ""
    links = ""
    if acao in {"mapa", "ambos"}:
        mapa = _gravar_mapa(root, pendente.get("titulo") or "Mapa de fontes", notas, now)
    if acao in {"liga", "ambos"}:
        links = _ligar_notas(root, notas)
    if mapa == FALA_BLOQUEIO or links == FALA_BLOQUEIO:
        return FALA_BLOQUEIO
    partes = [parte for parte in (mapa, links) if parte]
    return " ".join(partes) if partes else FALA_BLOQUEIO


def fala_lembrete(root, now):
    hoje = _data(now)
    candidatas = _candidatas_lembrete(root, now)
    if not candidatas:
        return "Não há nota antiga com um ponto seu para lembrar, senhor."
    aberturas = _ler_aberturas()
    escolhida = _ordenar_lembrete(candidatas, aberturas, hoje)[0]
    _marcar_abertura(escolhida["caminho"], hoje)
    LOG.info("lembrete de nota escolhido")
    fonte = _ROTULO.get(escolhida["fonte"], "nota")
    return (
        "Uma nota que faz tempo que você não abre, senhor. "
        + escolhida["titulo"]
        + ", "
        + fonte
        + ". Você escreveu: "
        + escolhida["ponto"]
        + "."
    )


def texto_lembrete_telegram(root, now):
    from .privacidade import modo_privado_ativo, texto_para_telegram

    if modo_privado_ativo() or root is None:
        return ""
    fala = fala_lembrete(root, now)
    if not fala or fala.startswith("Não há"):
        return ""
    limpo = texto_para_telegram(fala, root)
    if not limpo or "sigilos" in fold(limpo):
        return ""
    return limpo


def preparar_meta(root, tema, now, embedder):
    from .guardas import texto_secreto

    assunto = _tema_limpo(tema)
    if not assunto:
        return "Sobre o que você quer aprender, senhor?", None
    if texto_secreto(assunto) or _INJECAO.search(assunto):
        return "Não guardei essa meta, senhor. O tema tem cara de segredo.", None
    notas = _com_vetores(root, _notas_publicas(root), embedder)
    if notas is None:
        notas = []
    else:
        notas = _do_tema(notas, assunto, embedder)
    cartoes = _cartoes_do_tema(root, assunto, notas)
    lacunas = _lacunas(assunto, notas, cartoes)
    plano = montar_plano(notas, cartoes, lacunas, now)
    registro = {
        "tema": assunto,
        "criada": _data(now).isoformat(),
        "atualizada": _data(now).isoformat(),
        "notas": [_publico(nota) for nota in notas[:12]],
        "cartoes": len(cartoes),
        "lacunas": [
            {
                "nome": item["nome"],
                "fontes": list(item["fontes"]),
                "sugestao": item["sugestao"],
            }
            for item in lacunas[:5]
        ],
        "plano": plano,
    }
    return _fala_meta(registro), registro


def gravar_meta_local(registro):
    from . import config
    from .trava import gravar_atomico, trava_arquivo

    path = config.jarvis_home() / "metas.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    chave = _chave_tema(registro.get("tema"))
    limpo = _registro_limpo(registro)
    with trava_arquivo(path.with_name(path.name + ".lock"), mensagem="meta ocupada"):
        atual = _ler_json(path)
        metas = atual.get("metas") if isinstance(atual.get("metas"), dict) else {}
        metas[chave] = limpo
        bruto = json.dumps({"versao": 1, "metas": metas}, ensure_ascii=False, indent=2)
        gravar_atomico(path, bruto + "\n", mode=0o600)
    LOG.info("meta local gravada")


def gravar_nota_meta(root, registro, now):
    from . import config
    from .trava import fila_escrita

    relativa = config.metas_pasta().strip("/") + "/" + _slug(registro.get("tema")) + ".md"
    path = _destino(root, relativa)
    if path is None:
        return "Não gravei a nota da meta, senhor. O destino ficou fora do vault."
    corpo = _render_meta(registro, now)
    try:
        with fila_escrita():
            escrever(path, corpo, raiz=root)
    except GuardError:
        return FALA_BLOQUEIO
    return "Também gravei uma nota da meta no vault."


def falar_progresso(root, tema, now, embedder):
    assunto = _tema_limpo(tema)
    if not assunto:
        return "Sobre qual tema, senhor?"
    notas = _com_vetores(root, _notas_publicas(root), embedder)
    if notas is None:
        notas = []
    else:
        notas = _do_tema(notas, assunto, embedder)
    cartoes = _cartoes_do_tema(root, assunto, notas)
    return _fala_progresso(assunto, cartoes, _data(now))


def sugerir_fontes(nome, presentes):
    """Texto puro. Não monta endereço e não consulta a rede."""
    tem = {fold(item) for item in presentes or []}
    faltam = [rotulo for chave, rotulo in _FONTES_ORDEM if chave not in tem]
    titulo = " ".join(str(nome or "o tema").split())[:80] or "o tema"
    if not faltam:
        return f"Você já tem livro, curso e vídeo sobre {titulo}."
    if len(faltam) == 1:
        lista = faltam[0]
    elif len(faltam) == 2:
        lista = faltam[0] + " ou " + faltam[1]
    else:
        lista = ", ".join(faltam[:-1]) + " ou " + faltam[-1]
    return f"Para {titulo}, procure {lista}. Eu não busco isso na rede."


def montar_plano(notas, cartoes, lacunas, now):
    tarefas = []
    for nota in notas[:4]:
        fonte = _ROTULO.get(nota.get("fonte"), "nota")
        tarefas.append("Leia " + nota["titulo"] + " (" + fonte + ").")
    total = len(cartoes or [])
    if total == 1:
        tarefas.append("Revise 1 cartão que já existe sobre o tema.")
    elif total > 1:
        tarefas.append(f"Revise {total} cartões que já existem sobre o tema.")
    for lacuna in (lacunas or [])[:3]:
        tarefas.append(lacuna["sugestao"])
    if not tarefas:
        tarefas.append(
            "Não há nota nem cartão sobre o tema. "
            "Procure um livro, um curso ou um vídeo. Eu não busco isso na rede."
        )
    tarefas = tarefas[:7]
    dias = _dias_seguintes(now, len(tarefas))
    return [dias[indice] + ": " + tarefas[indice] for indice in range(len(tarefas))]


def _fala_proposta(titulo, pares, grupo):
    bits = []
    for esquerda, direita in pares[:3]:
        bits.append(esquerda + " e " + direita)
    fontes = _join_pt(sorted({_ROTULO.get(nota["fonte"], "nota") for nota in grupo}))
    return (
        "Encontrei ligações entre fontes diferentes, senhor. "
        + _join_pt(bits)
        + ". Fontes: "
        + fontes
        + ". Posso gravar o mapa "
        + titulo
        + " só com esses títulos. "
        + "Diga sim ou grava o mapa para criar a nota. "
        + "Diga liga as notas para acrescentar os links. "
        + "Diga não para deixar como está."
    )


def _fala_meta(registro):
    tema = registro["tema"]
    notas = registro["notas"]
    partes = [f"Guardei a meta {tema} fora do vault, senhor."]
    if notas:
        partes.append("No vault, " + _join_pt([nota["titulo"] for nota in notas[:4]]) + ".")
        fontes = sorted(
            {
                _ROTULO[nota["fonte"]]
                for nota in notas
                if nota.get("fonte") in _ROTULO and nota["fonte"] != "nota"
            }
        )
        if fontes:
            partes.append("Fontes: " + _join_pt(fontes) + ".")
    else:
        partes.append("Ainda não há nota sobre esse tema.")
    total = int(registro.get("cartoes") or 0)
    if total == 1:
        partes.append("Há 1 cartão.")
    else:
        partes.append(f"Há {total} cartões.")
    lacunas = registro.get("lacunas") or []
    if lacunas:
        nomes = _join_pt([item["nome"] for item in lacunas[:3]])
        partes.append("Lacunas: " + nomes + ". " + lacunas[0]["sugestao"])
    plano = registro.get("plano") or []
    if plano:
        partes.append("Plano da semana. " + " ".join(plano[:4]))
    return " ".join(partes)


def _fala_progresso(tema, cartoes, hoje):
    from .review import load_state

    total = len(cartoes)
    if total == 0:
        return f"Não há cartão de revisão sobre {tema}, senhor."
    estado = load_state()
    registros = estado.get("cards") if isinstance(estado.get("cards"), dict) else {}
    revisados = 0
    lapsos = 0
    vencem = 0
    hoje_txt = hoje.isoformat()
    for cartao in cartoes:
        registro = registros.get(cartao["id"]) if isinstance(registros.get(cartao["id"]), dict) else {}
        try:
            reps = int((registro or {}).get("reps") or 0)
        except (TypeError, ValueError):
            reps = 0
        try:
            lapsos += int((registro or {}).get("lapses") or 0)
        except (TypeError, ValueError):
            pass
        if reps > 0:
            revisados += 1
        due = str((registro or {}).get("due") or "")
        if not due or due <= hoje_txt:
            vencem += 1
    cartao = "cartão" if total == 1 else "cartões"
    ligado = "ligado" if total == 1 else "ligados"
    passou = "passou" if revisados == 1 else "passaram"
    lapso = "lapso" if lapsos == 1 else "lapsos"
    vence = "vence" if vencem == 1 else "vencem"
    return (
        f"Em {tema}, senhor, há {total} {cartao} {ligado} ao tema. "
        f"{revisados} já {passou} pela revisão, com {lapsos} {lapso}. "
        f"{vencem} {vence} hoje."
    )


def _lacunas(tema, notas, cartoes):
    por_nome = {}
    for nota in notas:
        for nome in _subtemas(nota.get("texto") or "", nota.get("titulo") or ""):
            item = por_nome.setdefault(fold(nome), {"nome": nome, "fontes": set()})
            if nota.get("fonte") and nota["fonte"] != "nota":
                item["fontes"].add(nota["fonte"])
    achados = []
    for item in por_nome.values():
        fontes = sorted(item["fontes"])
        tema_fontes = {nota["fonte"] for nota in notas if nota.get("fonte") not in {"", "nota"}}
        if _cartao_cobre(item["nome"], cartoes) and not (tema_fontes - set(fontes)):
            continue
        achados.append(
            {
                "nome": item["nome"],
                "fontes": fontes,
                "sugestao": sugerir_fontes(item["nome"], fontes),
            }
        )
    if not achados:
        fontes = sorted({nota["fonte"] for nota in notas if nota.get("fonte") not in {"", "nota"}})
        if not cartoes or len(fontes) < 2:
            achados.append(
                {
                    "nome": tema,
                    "fontes": fontes,
                    "sugestao": sugerir_fontes(tema, fontes),
                }
            )
    achados.sort(key=lambda item: fold(item["nome"]))
    return achados[:5]


def _cartao_cobre(nome, cartoes):
    tokens = [token for token in fold(nome).split() if len(token) >= 3 and token not in _PARADA]
    if not tokens:
        return False
    for cartao in cartoes or []:
        hay = fold(
            (cartao.get("question") or "")
            + " "
            + (cartao.get("path") or "")
            + " "
            + " ".join(cartao.get("tags") or [])
        )
        if all(token in hay for token in tokens):
            return True
    return False


def _subtemas(texto, titulo):
    achados = []
    visto = {fold(titulo or "")}
    for linha in _without_frontmatter(texto).splitlines():
        match = _HEADING.match(linha.strip())
        if not match:
            continue
        nome = " ".join(match.group(1).replace("[", "").replace("]", "").split())[:80]
        chave = fold(nome)
        if not nome or chave in _GERADAS or chave in _PESSOAIS or chave in visto:
            continue
        visto.add(chave)
        achados.append(nome)
        if len(achados) == 8:
            break
    return achados


def _cartoes_do_tema(root, tema, notas):
    from .privacidade import nota_sigilosa
    from .review import scan_cards

    caminhos = {nota["caminho"] for nota in notas}
    tokens = _tokens_tema(tema)
    achados = []
    vistos = set()
    for cartao in scan_cards(root):
        if nota_sigilosa(root, cartao.get("path") or ""):
            continue
        caminho = str(cartao.get("path") or "").replace("\\", "/")
        hay = fold(
            (cartao.get("question") or "")
            + " "
            + caminho
            + " "
            + " ".join(cartao.get("tags") or [])
        )
        if caminho not in caminhos and not (tokens and all(token in hay for token in tokens)):
            continue
        if cartao["id"] in vistos:
            continue
        vistos.add(cartao["id"])
        achados.append(cartao)
    return achados


def _candidatas_lembrete(root, now):
    notas = []
    for nota in _notas_publicas(root):
        ponto = ponto_do_usuario(nota.get("texto") or "")
        if not ponto:
            continue
        idade = _idade_dias(nota.get("mtime") or 0, now)
        item = _publico(nota)
        item["ponto"] = ponto
        item["mtime"] = nota.get("mtime") or 0
        item["idade"] = idade
        notas.append(item)
    antigas = [nota for nota in notas if nota["idade"] >= _IDADE_ANTIGA]
    if antigas:
        return antigas
    return [nota for nota in notas if nota["idade"] >= 1]


def _ordenar_lembrete(notas, aberturas, hoje):
    hoje_txt = hoje.isoformat()

    def chave(nota):
        aberta = aberturas.get(nota["caminho"])
        if aberta == hoje_txt:
            dias = 0
        elif not aberta:
            dias = 10000
        else:
            try:
                dias = (hoje - date.fromisoformat(aberta)).days
            except ValueError:
                dias = 10000
        return (-dias, nota.get("mtime") or 0, nota["caminho"])

    return sorted(notas, key=chave)


def ponto_do_usuario(texto):
    from .privacidade import pedido_limpo
    from .review import parse_card_line

    secao = ""
    pessoal = []
    soltas = []
    cartao = ""
    for linha in _without_frontmatter(texto or "").splitlines():
        bruta = linha.strip()
        if bruta.startswith("<!--"):
            continue
        match = _HEADING.match(bruta)
        if match:
            secao = fold(match.group(1))
            continue
        if bruta.startswith(">"):
            continue
        if ":::" in bruta:
            parsed = parse_card_line(bruta)
            if parsed and not cartao:
                cartao = parsed[1]
            continue
        if bruta.startswith(("- ", "* ")):
            bruta = bruta[2:].strip()
        if not bruta:
            continue
        limpa = _clip_ponto(pedido_limpo(bruta))
        if not limpa or _INJECAO.search(limpa):
            continue
        if secao in _PESSOAIS:
            pessoal.append(limpa)
        elif secao not in _GERADAS:
            soltas.append(limpa)
    escolhido = pessoal[0] if pessoal else (soltas[0] if soltas else "")
    if not escolhido:
        escolhido = _clip_ponto(pedido_limpo(cartao))
    if not escolhido or _INJECAO.search(escolhido):
        return ""
    return escolhido


def _clip_ponto(texto):
    limpo = " ".join(str(texto or "").replace("\u2014", " ").replace("\u2013", " ").split())
    if len(limpo) < 8:
        return ""
    if len(limpo) <= 160:
        return limpo
    cortado = limpo[:160].rsplit(" ", 1)[0]
    return cortado or limpo[:160]


def _notas_publicas(root):
    from .catalogo import obter
    from .privacidade import nota_sigilosa

    try:
        catalogo = obter(root)
    except Exception:
        return []
    notas = []
    for nota in catalogo.notas.values():
        if not nota.util or nota.texto is None:
            continue
        caminho = str(nota.relative or "").replace("\\", "/")
        if not caminho or caminho.startswith(".") or "/." in f"/{caminho}":
            continue
        if nota_sigilosa(root, caminho, nota.texto):
            continue
        titulo = _titulo_limpo(nota.titulo or Path(caminho).stem)
        if not titulo:
            continue
        notas.append(
            {
                "caminho": caminho,
                "titulo": titulo,
                "texto": nota.texto,
                "fonte": tipo_fonte(caminho, nota.texto),
                "mtime_ns": nota.mtime_ns,
                "mtime": (nota.mtime_ns or 0) / 1_000_000_000,
                "tamanho": nota.tamanho,
            }
        )
    notas.sort(key=lambda item: (0 if item["fonte"] != "nota" else 1, item["caminho"]))
    return notas[:800]


def tipo_fonte(relative, texto):
    from . import config

    caminho = fold(str(relative or "").replace("\\", "/"))
    regras = (
        ("readwise", config.readwise_pasta(), ("readwise",)),
        ("video", config.videos_pasta(), ("video", "videos", "vídeo", "vídeos")),
        ("livro", config.livros_pasta(), ("livro", "livros", "book", "books")),
        ("curso", config.cursos_pasta(), ("curso", "cursos", "course", "courses")),
        ("artigo", config.artigos_pasta(), ("artigo", "artigos", "article", "articles")),
        ("podcast", config.podcasts_pasta(), ("podcast", "podcasts")),
    )
    melhor = ""
    tipo = ""
    for nome, pasta, _nomes in regras:
        prefixo = fold(pasta).strip("/")
        if prefixo and (caminho == prefixo or caminho.startswith(prefixo + "/")):
            if len(prefixo) >= len(melhor):
                melhor = prefixo
                tipo = nome
    if tipo:
        return tipo
    meta = _frontmatter(texto)
    valores = []
    for chave in ("tipo", "type", "fonte", "source", "origem", "categoria", "category", "tags"):
        if meta.get(chave):
            valores.append(meta[chave])
    partes = [parte for parte in caminho.split("/")[:-1]]
    for nome, _pasta, nomes in regras:
        chaves = {fold(item) for item in nomes}
        if any(parte in chaves for parte in partes):
            return nome
        for valor in valores:
            tokens = set(fold(valor).replace(",", " ").split())
            if tokens & chaves:
                return nome
    return "nota"


def _com_vetores(root, notas, embedder):
    from .indice_vetor import cache_file, vectors_for
    from .semantica import ligada, vetores_das_notas

    if ligada() and embedder is not None and type(embedder).__name__ != "HashEmbedder":
        return vetores_das_notas(root, notas, embedder)
    if embedder is None or not notas:
        return [] if notas == [] else None
    registros = [
        {
            "relative": nota["caminho"],
            "texto": nota["texto"],
            "mtime_ns": nota.get("mtime_ns"),
            "tamanho": nota.get("tamanho"),
        }
        for nota in notas
    ]
    try:
        vetores = vectors_for(registros, embedder, store=cache_file(root, embedder))
    except Exception:
        return None
    if not vetores or len(vetores) != len(notas):
        return None
    saida = []
    for nota, vetor in zip(notas, vetores):
        if not vetor:
            continue
        item = dict(nota)
        item["vetor"] = vetor
        saida.append(item)
    return saida


def _do_tema(notas, tema, embedder):
    tokens = _tokens_tema(tema)
    vetor = _vetor_consulta(embedder, tema)
    escolhidas = []
    for nota in notas:
        if vetor and dense_cosine(vetor, nota.get("vetor") or []) >= LIMIAR_TEMA:
            escolhidas.append(nota)
            continue
        if tokens and all(token in fold(nota.get("titulo") or "") for token in tokens):
            escolhidas.append(nota)
    return escolhidas


def _vetor_consulta(embedder, tema):
    if embedder is None:
        return None
    try:
        rows = embedder.embed([tema])
    except Exception:
        return None
    if not rows:
        return None
    try:
        return [float(value) for value in list(rows[0])]
    except (TypeError, ValueError):
        return None


def _pares(notas):
    achados = []
    for indice, esquerda in enumerate(notas):
        for direita in notas[indice + 1 :]:
            if esquerda["fonte"] == direita["fonte"]:
                continue
            if esquerda["fonte"] == "nota" and direita["fonte"] == "nota":
                continue
            score = dense_cosine(esquerda.get("vetor") or [], direita.get("vetor") or [])
            if score < LIMIAR_PAR:
                continue
            achados.append((score, esquerda, direita))
    achados.sort(key=lambda item: (-item[0], item[1]["caminho"], item[2]["caminho"]))
    return achados


def _melhor_grupo(pares):
    if not pares:
        return []
    vizinhos = {}
    por_caminho = {}
    for score, esquerda, direita in pares:
        vizinhos.setdefault(esquerda["caminho"], []).append((score, direita))
        vizinhos.setdefault(direita["caminho"], []).append((score, esquerda))
        por_caminho[esquerda["caminho"]] = esquerda
        por_caminho[direita["caminho"]] = direita
    inicio = pares[0][1]["caminho"]
    vistos = {inicio}
    fila = [inicio]
    while fila and len(vistos) < 6:
        atual = fila.pop(0)
        for _score, outro in sorted(vizinhos.get(atual, []), key=lambda item: -item[0]):
            if outro["caminho"] in vistos:
                continue
            vistos.add(outro["caminho"])
            fila.append(outro["caminho"])
            if len(vistos) >= 6:
                break
    grupo = [por_caminho[caminho] for caminho in vistos if caminho in por_caminho]
    fontes = {nota["fonte"] for nota in grupo}
    if len(grupo) < 2 or len(fontes) < 2:
        return []
    grupo.sort(key=lambda nota: nota["caminho"])
    return grupo


def _pares_do_grupo(grupo):
    caminhos = {nota["caminho"] for nota in grupo}
    pares = []
    for esquerda in grupo:
        for direita in grupo:
            if esquerda["caminho"] >= direita["caminho"]:
                continue
            if esquerda["caminho"] not in caminhos:
                continue
            if esquerda["fonte"] == direita["fonte"]:
                continue
            pares.append((esquerda["titulo"], direita["titulo"]))
    return pares[:6]


def _titulo_mapa(assunto, grupo):
    if assunto:
        return "Mapa: " + assunto
    comum = None
    for nota in grupo:
        tokens = {
            token
            for token in fold(nota["titulo"]).split()
            if len(token) >= 4 and token not in _PARADA
        }
        comum = tokens if comum is None else comum & tokens
    if comum:
        return "Mapa: " + sorted(comum)[0]
    return "Mapa de fontes"


def _gravar_mapa(root, titulo, notas, now):
    from . import config
    from .trava import fila_escrita

    pasta = config.mapas_pasta().strip("/")
    base = pasta + "/mapa-" + _slug(titulo)
    relativa = base + ".md"
    path = _destino_livre(root, relativa)
    if path is None:
        return "Não gravei o mapa, senhor. O destino ficou fora do vault."
    corpo = _render_mapa(titulo, notas, now)
    try:
        with fila_escrita():
            escrever(path, corpo, raiz=root)
    except GuardError:
        return FALA_BLOQUEIO
    return "Gravei o mapa " + titulo + ", senhor."


def _ligar_notas(root, notas):
    from .leitura import ler_texto
    from .privacidade import nota_sigilosa
    from .trava import fila_escrita

    alvos = []
    bloqueados = 0
    for nota in notas:
        path = _destino(root, nota["caminho"])
        if path is None:
            bloqueados += 1
            continue
        alvos.append((nota, path))
    if len(alvos) < 2:
        return FALA_BLOQUEIO
    ligados = 0
    try:
        with fila_escrita():
            vivos = []
            for nota, path in alvos:
                if not path.is_file():
                    bloqueados += 1
                    continue
                try:
                    atual = ler_texto(path)
                except (OSError, UnicodeError):
                    bloqueados += 1
                    continue
                if nota_sigilosa(root, nota["caminho"], atual):
                    bloqueados += 1
                    continue
                vivos.append((nota, path, atual))
            if len(vivos) < 2:
                return FALA_BLOQUEIO
            for nota, path, atual in vivos:
                outros = [
                    item[0]["titulo"]
                    for item in vivos
                    if item[0]["caminho"] != nota["caminho"]
                ]
                novo = _acrescentar_links(atual, outros)
                if novo == atual:
                    ligados += 1
                    continue
                escrever(path, novo, raiz=root)
                ligados += 1
    except GuardError:
        return FALA_BLOQUEIO
    if ligados == 0:
        return FALA_BLOQUEIO
    fala = "Liguei as notas pelos títulos, senhor."
    if bloqueados == 1:
        fala += " 1 nota ficou bloqueada."
    elif bloqueados:
        fala += f" {bloqueados} notas ficaram bloqueadas."
    return fala


def _acrescentar_links(texto, titulos):
    novos = []
    bruto = texto or ""
    for titulo in titulos:
        link = _wikilink(titulo)
        if not link or link in bruto:
            continue
        novos.append("- " + link)
    if not novos:
        return bruto
    base = bruto.rstrip() + "\n"
    if "## Ligações" not in base:
        base += "\n## Ligações\n"
    if not base.endswith("\n"):
        base += "\n"
    base += "\n".join(novos) + "\n"
    return base


def _render_mapa(titulo, notas, now):
    linhas = [
        "---",
        "title: " + _yaml(titulo),
        "tipo: moc",
        "date: " + _data(now).isoformat(),
        "---",
        "",
        "# " + titulo,
        "",
        "Notas de fontes diferentes sobre o mesmo assunto.",
        "",
    ]
    for nota in notas:
        link = _wikilink(nota["titulo"])
        if not link:
            continue
        fonte = _ROTULO.get(nota.get("fonte"), "nota")
        linhas.append("- " + link + " (" + fonte + ")")
    linhas.append("")
    return "\n".join(linhas)


def _render_meta(registro, now):
    titulo = "Meta: " + (registro.get("tema") or "tema")
    linhas = [
        "---",
        "title: " + _yaml(titulo),
        "tipo: meta",
        "date: " + _data(now).isoformat(),
        "---",
        "",
        "# " + titulo,
        "",
        "## O que já existe",
        "",
    ]
    notas = registro.get("notas") or []
    if notas:
        for nota in notas:
            link = _wikilink(nota.get("titulo"))
            if not link:
                continue
            fonte = _ROTULO.get(nota.get("fonte"), "nota")
            linhas.append("- " + link + " (" + fonte + ")")
    else:
        linhas.append("- Nenhuma nota ainda.")
    linhas.extend(["", "Cartões relacionados: " + str(int(registro.get("cartoes") or 0)) + ".", ""])
    linhas.extend(["## Lacunas", ""])
    lacunas = registro.get("lacunas") or []
    if lacunas:
        for item in lacunas:
            linhas.append("- " + item["nome"] + ". " + item["sugestao"])
    else:
        linhas.append("- Nenhuma lacuna marcada.")
    linhas.extend(["", "## Plano da semana", ""])
    for passo in registro.get("plano") or []:
        linhas.append("- " + passo)
    linhas.append("")
    return "\n".join(linhas)


def _wikilink(titulo):
    limpo = " ".join(str(titulo or "").replace("[", "").replace("]", "").split())[:160]
    if not limpo:
        return ""
    return "[[" + limpo + "]]"


def _yaml(valor):
    texto = " ".join(str(valor or "").split())[:160]
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _publico(nota):
    return {
        "titulo": nota.get("titulo") or "",
        "caminho": str(nota.get("caminho") or "").replace("\\", "/"),
        "fonte": nota.get("fonte") or "nota",
    }


def _nota_pendente(item):
    if not isinstance(item, dict):
        return False
    caminho = str(item.get("caminho") or "").replace("\\", "/")
    titulo = " ".join(str(item.get("titulo") or "").split())
    return bool(caminho and titulo and "texto" not in item and "text" not in item)


def _destino(root, relativa):
    from .guardas import caminho_bloqueado, caminho_dentro
    from .paths import caminho_relativo

    seguro = caminho_relativo(relativa)
    if not seguro:
        return None
    path = Path(root) / seguro
    if caminho_bloqueado(path) or not caminho_dentro(root, path):
        return None
    return path


def _destino_livre(root, relativa):
    from .paths import caminho_relativo

    seguro = caminho_relativo(relativa)
    path = _destino(root, seguro)
    if path is None:
        return None
    if not path.exists():
        return path
    pasta_rel, nome = seguro.rsplit("/", 1) if "/" in seguro else ("", seguro)
    base = nome[:-3] if nome.lower().endswith(".md") else nome
    for numero in range(2, 6):
        pedaco = base + "-" + str(numero) + ".md"
        candidato_rel = pasta_rel + "/" + pedaco if pasta_rel else pedaco
        candidato = _destino(root, candidato_rel)
        if candidato is not None and not candidato.exists():
            return candidato
    return None


def _ler_aberturas():
    from . import config
    from .paths import caminho_relativo

    data = _ler_json(config.jarvis_home() / "aberturas.json")
    notas = data.get("notas") if isinstance(data.get("notas"), dict) else {}
    limpo = {}
    for chave, valor in notas.items():
        relativo = caminho_relativo(chave)
        if not relativo or not isinstance(valor, str) or not _DIA.fullmatch(valor):
            continue
        limpo[relativo] = valor
    return limpo


def _marcar_abertura(caminho, hoje):
    from . import config
    from .paths import caminho_relativo
    from .trava import gravar_atomico, trava_arquivo

    relativo = caminho_relativo(caminho)
    if not relativo:
        return
    path = config.jarvis_home() / "aberturas.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with trava_arquivo(path.with_name(path.name + ".lock"), mensagem="abertura ocupada"):
        atual = _ler_aberturas()
        atual[relativo] = hoje.isoformat()
        if len(atual) > 400:
            ordenadas = sorted(atual.items(), key=lambda item: item[1])
            atual = dict(ordenadas[-400:])
        bruto = json.dumps({"versao": 1, "notas": atual}, ensure_ascii=True, indent=2)
        gravar_atomico(path, bruto + "\n", mode=0o600)


def _registro_limpo(registro):
    notas = []
    for nota in registro.get("notas") or []:
        if not isinstance(nota, dict):
            continue
        publico = _publico(nota)
        if publico["titulo"] and publico["caminho"]:
            notas.append(publico)
    lacunas = []
    for item in registro.get("lacunas") or []:
        if not isinstance(item, dict):
            continue
        nome = " ".join(str(item.get("nome") or "").split())[:80]
        if not nome:
            continue
        lacunas.append(
            {
                "nome": nome,
                "fontes": [str(fonte) for fonte in (item.get("fontes") or [])][:6],
                "sugestao": " ".join(str(item.get("sugestao") or "").split())[:240],
            }
        )
    plano = [" ".join(str(passo).split())[:240] for passo in (registro.get("plano") or [])][:7]
    return {
        "tema": " ".join(str(registro.get("tema") or "").split())[:80],
        "criada": str(registro.get("criada") or "")[:10],
        "atualizada": str(registro.get("atualizada") or "")[:10],
        "notas": notas[:12],
        "cartoes": int(registro.get("cartoes") or 0),
        "lacunas": lacunas[:5],
        "plano": [passo for passo in plano if passo],
    }


def _ler_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _frontmatter(texto):
    bruto = texto or ""
    if not bruto.startswith("---"):
        return {}
    fim = bruto.find("\n---", 3)
    if fim == -1:
        return {}
    achados = {}
    for linha in bruto[3:fim].splitlines():
        if ":" not in linha or linha[:1] in {" ", "\t"}:
            continue
        chave, valor = linha.split(":", 1)
        chave = fold(chave.strip())
        valor = valor.strip().strip("\"'")
        if chave and valor:
            achados[chave] = valor
    return achados


def _titulo_limpo(titulo):
    limpo = " ".join(str(titulo or "").replace("[", "").replace("]", "").split())
    return limpo[:160]


def _tema_limpo(tema):
    from .privacidade import pedido_limpo

    limpo = " ".join(pedido_limpo(tema or "").replace("\u2014", " ").replace("\u2013", " ").split())
    return limpo[:80]


def _tokens_tema(tema):
    return [token for token in fold(tema).split() if len(token) >= 3 and token not in _PARADA]


def _chave_tema(tema):
    chave = "-".join(_tokens_tema(tema)) or _slug(tema)
    return chave[:80] or "tema"


def _slug(texto):
    slug = re.sub(r"[^a-z0-9]+", "-", fold(texto or "")).strip("-")
    return slug[:40] or "tema"


def _data(now):
    if hasattr(now, "date"):
        try:
            return now.date()
        except Exception:
            pass
    return date.today()


def _dias_seguintes(now, quantidade):
    inicio = _data(now)
    return [_SEMANA[(inicio + timedelta(days=indice)).weekday()] for indice in range(quantidade)]


def _idade_dias(mtime, now):
    try:
        atual = now.timestamp()
    except Exception:
        return 0
    if not mtime or mtime <= 0 or atual < mtime:
        return 0
    return (atual - mtime) / 86400.0


def _metas_no_vault():
    from . import config

    return bool(config.metas_no_vault())
