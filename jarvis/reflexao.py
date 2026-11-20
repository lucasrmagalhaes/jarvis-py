"""Explicação de Feynman, perguntas socráticas e revisão semanal.

A nota entra na comparação como dado não confiável. Nota com #sigiloso
ou em pasta privada não vai para o cérebro, para o Telegram nem para o log.
O cartão da lacuna fica em rascunho. A revisão semanal só grava depois do sim.
"""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .log import LOG
from .routines import NO_WORDS, YES_WORDS, _join_pt, fold, normalize_phrase

SEM_VAULT = (
    "O vault não está configurado, senhor. Sem ele eu não leio as notas. "
    "Rode python -m jarvis.setup."
)
FALA_DOMINGO = (
    "Senhor, é domingo. Quando puder, diga revisão semanal para fechar a semana."
)
_COMANDOS = {"feynman", "socratic", "weekly"}
_PERMITIDOS = {
    "feynman": {"chat", "feynman", "dismiss", "review_grade"},
    "socratic": {"chat", "socratic", "dismiss", "review_grade"},
    "weekly": {"chat", "weekly", "dismiss", "review_grade"},
}
_PERGUNTAS = (
    "O que foi bem nesta semana, senhor?",
    "O que você aprendeu, senhor?",
    "O que travou, senhor?",
    "Qual o foco da próxima semana, senhor?",
)
_TITULOS = (
    "O que foi bem",
    "O que aprendi",
    "O que travou",
    "Foco da próxima semana",
)
_NIVEIS = ("o que", "por que", "como")
_PARADA = {
    "que",
    "com",
    "para",
    "pra",
    "por",
    "uma",
    "uns",
    "umas",
    "nao",
    "sim",
    "como",
    "mais",
    "menos",
    "muito",
    "sobre",
    "entre",
    "quando",
    "onde",
    "porque",
    "pelo",
    "pela",
    "pelos",
    "pelas",
    "este",
    "esta",
    "esse",
    "essa",
    "isso",
    "isto",
    "seu",
    "sua",
    "seus",
    "suas",
    "voce",
    "senhor",
    "jarvis",
    "tema",
    "nota",
    "notas",
    "qual",
    "quais",
    "dos",
    "das",
    "nos",
    "nas",
    "num",
    "numa",
    "sao",
    "ser",
    "ter",
    "tem",
    "foi",
    "era",
    "estao",
    "the",
    "and",
}
_GERADAS = {"resumo", "pontos", "cartoes", "referencias", "ligacoes", "fontes", "fonte"}
_GLOSA = ("ou seja", "quer dizer", "significa", "isto e", "em outras palavras")
_TOKEN = re.compile(r"[a-z0-9]{3,}")
_RUIM = re.compile(
    r"(?i)(git\s+push|enviar\s+e-?mail|envie\s+um\s+e-?mail|sendmessage|"
    r"ignore\s+as\s+instru|dado-nao-confiavel|</?dado)"
)
_FIM = re.compile(r"(?i)^fim-(\d{4}-\d{2}-\d{2})\.md$")
_SEMANA_ARQ = re.compile(r"(?i)^revisao-semanal-\d{4}-W\d{2}\.md$")
_ISO = re.compile(r"^\d{4}-W\d{2}$")
_MARCA = re.compile(
    r"(?is)(lacuna|erro|jarg[aã]o|jargon|cartao|cartão)\s*:\s*"
    r"(.+?)(?=(?:\s(?:lacuna|erro|jarg[aã]o|jargon|cartao|cartão)\s*:)|$)"
)


def turno(root, intent, message, now, pending, cerebro=None):
    kind = getattr(intent, "kind", "")
    ativo = ""
    if isinstance(pending, dict) and pending.get("kind") in _PERMITIDOS:
        ativo = pending.get("kind")
    if not ativo and kind not in _COMANDOS:
        return None
    if ativo and kind not in _PERMITIDOS[ativo]:
        if kind in _COMANDOS:
            pending = None
            ativo = ""
        elif kind == "review_pause":
            return None
        else:
            return ("drop",)
    if root is None:
        return ("reply", SEM_VAULT, None)
    if kind == "feynman" or ativo == "feynman":
        return _turno_feynman(root, intent, message, now, pending, cerebro)
    if kind == "socratic" or ativo == "socratic":
        return _turno_socratico(root, intent, message, now, pending)
    if kind == "weekly" or ativo == "weekly":
        return _turno_semana(root, intent, message, now, pending)
    return None


def texto_revisao_semanal():
    from .privacidade import modo_privado_ativo

    if modo_privado_ativo():
        return ""
    return FALA_DOMINGO


def foco_da_semana(now):
    dados = ultimo_foco()
    if dados["semana"] != semana_iso(_data(now)):
        return ""
    return dados["texto"]


def ultimo_foco():
    """Foco da última revisão semanal, sem o corpo da nota."""
    dados = _ler_foco()
    if not isinstance(dados, dict):
        return {"semana": "", "texto": ""}
    semana = str(dados.get("semana") or "")
    if not _ISO.match(semana):
        return {"semana": "", "texto": ""}
    texto = _limpo(dados.get("foco") or "", 180)
    if not texto or _recusado(texto):
        return {"semana": semana, "texto": ""}
    return {"semana": semana, "texto": texto}


def semana_iso(dia):
    iso = dia.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def nome_revisao(dia):
    return "revisao-semanal-" + semana_iso(dia) + ".md"


def proxima_semana(dia):
    return semana_iso(dia + timedelta(days=7))


def montar_contexto(root, now):
    dia = _data(now)
    inicio, fim = _intervalo(dia)
    tz = now.tzinfo if isinstance(now, datetime) else None
    notas = _notas_do_tema(root, "")
    criadas = []
    fins = []
    for nota in notas:
        nome = Path(nota["caminho"]).name
        if _SEMANA_ARQ.match(nome):
            continue
        fim_nome = _FIM.match(nome)
        if fim_nome:
            try:
                quando = datetime.strptime(fim_nome.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if inicio <= quando <= fim:
                fins.append(nota)
            continue
        modificado = _mtime_date(nota, tz)
        if modificado is not None and inicio <= modificado <= fim:
            criadas.append(nota)
    criadas.sort(key=lambda item: item["caminho"])
    fins.sort(key=lambda item: item["caminho"])
    from .review import scan_cards

    stats = _stats(scan_cards(root), fim)
    metas = _progresso_metas(root, fim)
    pacote = _empacotar_contexto(criadas[:8], stats, metas[:4], fins[:4])
    from .sessao import resumo as resumo_estudo

    estudo = resumo_estudo(now)
    minutos = int(estudo.get("minutos_semana") or 0)
    if minutos <= 0:
        pacote["frases"].append("Não houve sessão de estudo nesta semana.")
        pacote["linhas"].append("- Estudo: nenhuma sessão.")
        return pacote
    pacote["frases"].append("As sessões de estudo somam " + str(minutos) + " minutos.")
    detalhes = []
    for item in (estudo.get("temas") or [])[:4]:
        detalhes.append(str(item.get("tema") or "") + " " + str(int(item.get("minutos") or 0)) + " min")
    linha = "- Estudo: " + str(minutos) + " minutos"
    if detalhes:
        linha += " (" + ", ".join(detalhes) + ")"
    pacote["linhas"].append(linha + ".")
    return pacote


def _turno_feynman(root, intent, message, now, pending, cerebro):
    del now
    kind = getattr(intent, "kind", "")
    if kind == "dismiss":
        return ("reply", "Encerrei a explicação, senhor.", None)
    if kind == "feynman" or not isinstance(pending, dict):
        return _comecar_feynman(root, getattr(intent, "query", "") or "")
    fase = pending.get("phase")
    if fase == "confirmar":
        return _confirmar_rascunhos(message, pending)
    explicacao = _resposta_usuario(message)
    if len(_tokens(explicacao)) < 3:
        return (
            "reply",
            "Explique com um pouco mais de detalhe, senhor. Pode ser por voz ou por texto.",
            pending,
        )
    tema = pending.get("tema") or ""
    notas = _notas_do_tema(root, tema)
    if not notas:
        return (
            "reply",
            "Não encontrei nota pública sobre " + tema + ", senhor.",
            None,
        )
    resultado = _comparar(tema, explicacao, notas, cerebro)
    fala = _fala_comparacao(tema, resultado, _contar_privadas(root, tema))
    rascunhos = resultado.get("rascunhos") or []
    if not rascunhos:
        return ("reply", fala, None)
    novo = {
        "kind": "feynman",
        "phase": "confirmar",
        "tema": tema,
        "rascunhos": rascunhos[:3],
    }
    return ("reply", fala, novo)


def _turno_socratico(root, intent, message, now, pending):
    del now
    kind = getattr(intent, "kind", "")
    if kind == "dismiss":
        return ("reply", "Encerrei as perguntas, senhor.", None)
    if kind == "socratic" or not isinstance(pending, dict):
        return _comecar_socratico(root, getattr(intent, "query", "") or "")
    resposta = _resposta_usuario(message)
    if _recusado(resposta):
        return (
            "reply",
            "Não usei essa frase, senhor. Responda com as suas palavras.",
            pending,
        )
    if len(_tokens(resposta)) < 1:
        return ("reply", "Preciso de uma frase, senhor.", pending)
    return _ouvir_socratico(root, pending, resposta)


def _turno_semana(root, intent, message, now, pending):
    kind = getattr(intent, "kind", "")
    if kind == "dismiss":
        return ("reply", "Encerrei a revisão semanal, senhor.", None)
    if kind == "weekly" or not isinstance(pending, dict):
        return _comecar_semana(root, now)
    if pending.get("phase") == "confirmar":
        return _confirmar_semana(message, pending)
    resposta = _resposta_usuario(message)
    if _recusado(resposta):
        return (
            "reply",
            "Não guardei essa frase, senhor. Ela tem cara de pedido ou de segredo.",
            pending,
        )
    if len(resposta) < 2:
        return ("reply", "Preciso de uma frase, senhor.", pending)
    respostas = list(pending.get("respostas") or [])
    indice = int(pending.get("indice") or 0)
    while len(respostas) < 4:
        respostas.append("")
    if indice < 0 or indice > 3:
        indice = 0
    respostas[indice] = resposta
    indice += 1
    if indice < 4:
        novo = {
            "kind": "weekly",
            "phase": "perguntar",
            "indice": indice,
            "respostas": respostas,
        }
        return ("reply", "Anotei. " + _PERGUNTAS[indice], novo)
    novo = {
        "kind": "weekly",
        "phase": "confirmar",
        "indice": 4,
        "respostas": respostas,
    }
    return (
        "reply",
        "Posso gravar a revisão semanal, senhor? Diga sim para gravar ou não para deixar.",
        novo,
    )


def _comecar_feynman(root, tema):
    assunto = _tema_limpo(tema)
    if not _tokens(assunto):
        return ("reply", "Sobre o que você quer explicar, senhor?", None)
    if _recusado(assunto):
        return ("reply", "Não comecei a explicação, senhor. O tema não serve.", None)
    notas = _notas_do_tema(root, assunto)
    if not notas:
        fala = "Não encontrei nota pública sobre " + assunto + ", senhor."
        privadas = _contar_privadas(root, assunto)
        if privadas:
            fala += " " + _fala_privadas(privadas)
        return ("reply", fala, None)
    _limpar_sessao()
    pending = {"kind": "feynman", "phase": "explicar", "tema": assunto}
    return (
        "reply",
        "Pode explicar "
        + assunto
        + " com palavras simples, senhor. Pode ser por voz ou por texto.",
        pending,
    )


def _comecar_socratico(root, tema):
    assunto = _tema_limpo(tema)
    if not _tokens(assunto):
        return ("reply", "Sobre o que devo perguntar, senhor?", None)
    if _recusado(assunto):
        return ("reply", "Não comecei as perguntas, senhor. O tema não serve.", None)
    notas = _notas_do_tema(root, assunto)
    if not notas:
        fala = "Não encontrei nota pública sobre " + assunto + ", senhor."
        privadas = _contar_privadas(root, assunto)
        if privadas:
            fala += " " + _fala_privadas(privadas)
        return ("reply", fala, None)
    plano = _plano(assunto, notas)
    if not plano:
        return (
            "reply",
            "Não encontrei ponto público para perguntar sobre " + assunto + ", senhor.",
            None,
        )
    _limpar_sessao()
    meta = _meta_que_casa(assunto)
    pending = {
        "kind": "socratic",
        "phase": "ouvir",
        "tema": assunto,
        "meta": meta,
        "indice": 0,
        "plano": plano,
        "fracos": [],
    }
    aviso = ""
    privadas = _contar_privadas(root, assunto)
    if privadas:
        aviso = _fala_privadas(privadas) + " "
    return ("reply", aviso + _anunciar(pending, 0), pending)


def _comecar_semana(root, now):
    _limpar_sessao()
    contexto = montar_contexto(root, now)
    pending = {
        "kind": "weekly",
        "phase": "perguntar",
        "indice": 0,
        "respostas": ["", "", "", ""],
    }
    semana = semana_iso(_data(now))
    fala = (
        "Revisão semanal de "
        + semana
        + ", senhor. "
        + " ".join(contexto["frases"])
        + " "
        + _PERGUNTAS[0]
    )
    return ("reply", " ".join(fala.split()), pending)


def _confirmar_rascunhos(message, pending):
    texto = fold(normalize_phrase(message or ""))
    if texto in NO_WORDS:
        return ("reply", "Tudo bem, senhor. Não criei rascunho.", None)
    if texto in YES_WORDS:
        itens = pending.get("rascunhos") if isinstance(pending.get("rascunhos"), list) else []
        return ("write_rascunhos", itens)
    return (
        "reply",
        "Diga sim para criar os rascunhos ou não para deixar, senhor.",
        pending,
    )


def _confirmar_semana(message, pending):
    texto = fold(normalize_phrase(message or ""))
    if texto in NO_WORDS:
        return ("reply", "Tudo bem, senhor. Não gravei a revisão semanal.", None)
    if texto in YES_WORDS:
        respostas = pending.get("respostas") if isinstance(pending.get("respostas"), list) else []
        return ("write_semana", respostas)
    return (
        "reply",
        "Diga sim para gravar ou não para deixar, senhor.",
        pending,
    )


def _ouvir_socratico(root, pending, resposta):
    plano = pending.get("plano") if isinstance(pending.get("plano"), list) else []
    indice = int(pending.get("indice") or 0)
    if indice < 0 or indice >= len(plano):
        return _fechar_socratico(pending)
    item = plano[indice]
    feedback, fraco = _feedback(root, item, resposta)
    fracos = [texto for texto in (pending.get("fracos") or []) if texto]
    if fraco:
        rotulo = _limpo(item.get("rotulo") or "", 80)
        if rotulo and rotulo not in fracos:
            fracos.append(rotulo)
    indice += 1
    novo = {
        "kind": "socratic",
        "phase": "ouvir",
        "tema": pending.get("tema") or "",
        "meta": pending.get("meta") or "",
        "indice": indice,
        "plano": plano,
        "fracos": fracos,
    }
    if indice >= len(plano):
        return ("reply", feedback + " " + _resumo_socratico(novo), None)
    return ("reply", feedback + " " + _anunciar(novo, indice), novo)


def _fechar_socratico(pending):
    return ("reply", _resumo_socratico(pending), None)


def _resumo_socratico(pending):
    fracos = [texto for texto in (pending.get("fracos") or []) if texto]
    meta = _limpo(pending.get("meta") or "", 80)
    if fracos:
        fala = "Pontos fracos: " + _join_pt(fracos) + "."
        if meta:
            fala += " Isso pesa na meta " + meta + ", senhor."
        return fala
    if meta:
        return "Não marquei ponto fraco, senhor. Nada disso pesa na meta " + meta + "."
    return "Não marquei ponto fraco, senhor."


def _anunciar(pending, indice):
    plano = pending.get("plano") or []
    total = len(plano)
    item = plano[indice]
    return f"Pergunta {indice + 1} de {total}. " + item.get("rotulo", "")


def _feedback(root, item, resposta):
    esperado = _esperado(root, item)
    if esperado is None:
        return "Não achei mais o ponto na nota, senhor.", False
    if esperado == "":
        return "O ponto ficou em nota privada, senhor.", False
    tokens = list(dict.fromkeys(_tokens(esperado)))
    falado = set(_tokens(resposta))
    if not tokens:
        return "Anotei, senhor.", False
    acertos = sum(1 for token in tokens if token in falado)
    if acertos >= max(1, (len(tokens) + 1) // 2):
        return "Isso cobre o ponto, senhor.", False
    return "Ficou fraco, senhor. O ponto era " + _limpo(esperado, 80) + ".", True


def _esperado(root, item):
    from .privacidade import nota_sigilosa

    caminho = str(item.get("caminho") or "").replace("\\", "/")
    path = _destino_nota(root, caminho)
    if path is None or not path.is_file():
        return None
    try:
        texto = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if nota_sigilosa(root, caminho, texto):
        return ""
    chave = item.get("chave") or ""
    tipo = item.get("tipo") or ""
    for ponto in _pontos_da_nota(_nota_dict(caminho, texto)):
        if ponto["tipo"] == tipo and ponto["chave"] == chave:
            return ponto["esperado"]
    return None


def _comparar(tema, explicacao, notas, cerebro):
    if callable(cerebro):
        try:
            bruto = cerebro(_prompt_explicacao(tema, explicacao, notas))
        except Exception:
            LOG.info("cerebro da explicacao indisponivel")
            bruto = ""
        lido = _parse_cerebro(bruto, notas)
        if lido is not None:
            LOG.info(
                "explicacao comparada pelo cerebro lacunas=%s",
                len(lido.get("lacunas") or []),
            )
            return lido
    local = _comparar_local(explicacao, notas)
    LOG.info("explicacao comparada lacunas=%s", len(local.get("lacunas") or []))
    return local


def _comparar_local(explicacao, notas):
    falado = set(_tokens(explicacao))
    lacunas = []
    erros = []
    rascunhos = []
    for nota in notas:
        for ponto in _pontos_da_nota(nota):
            chave = _tokens(ponto["nome"])
            esperado = _tokens(ponto["esperado"])
            cobre_nome = _cobre(chave, falado)
            cobre_esperado = _cobre(esperado, falado)
            if cobre_nome and esperado and not cobre_esperado:
                if len(erros) < 2:
                    erros.append("a nota diz " + _limpo(ponto["esperado"], 80))
                continue
            if cobre_nome or cobre_esperado:
                continue
            if len(lacunas) >= 3:
                continue
            lacunas.append(ponto["nome"])
            par = _par_cartao(_pergunta_lacuna(ponto), ponto["esperado"])
            if par is None:
                continue
            rascunhos.append(
                {"caminho": nota["caminho"], "pergunta": par[0], "resposta": par[1]}
            )
    return {
        "lacunas": lacunas,
        "erros": erros,
        "jargoes": _jargoes(explicacao, notas),
        "rascunhos": rascunhos[:3],
    }


def _fala_comparacao(tema, resultado, privadas):
    partes = ["Comparei sua explicação com as notas públicas sobre " + tema + ", senhor."]
    lacunas = resultado.get("lacunas") or []
    erros = resultado.get("erros") or []
    jargoes = resultado.get("jargoes") or []
    rascunhos = resultado.get("rascunhos") or []
    if lacunas:
        partes.append("Lacunas: " + _join_pt(lacunas) + ".")
    if erros:
        partes.append("Erros: " + _join_pt(erros) + ".")
    if jargoes:
        partes.append("Jargão: " + _join_pt(jargoes) + ".")
    if not lacunas and not erros and not jargoes:
        partes.append("Não vi lacuna, erro nem jargão.")
    if rascunhos:
        total = len(rascunhos)
        if total == 1:
            partes.append(
                "Posso criar 1 cartão em rascunho para a lacuna. "
                "Diga sim para gravar. Depois, diga revisa rascunhos."
            )
        else:
            partes.append(
                f"Posso criar {total} cartões em rascunho para as lacunas. "
                "Diga sim para gravar. Depois, diga revisa rascunhos."
            )
    elif lacunas:
        partes.append("Não há cartão válido para essa lacuna.")
    if privadas:
        partes.append(_fala_privadas(privadas))
    return " ".join(partes)


def _pergunta_lacuna(ponto):
    nome = _limpo(ponto.get("nome") or "", 80)
    if ponto.get("tipo") == "cartao" and nome.endswith("?"):
        return nome
    return "O que é " + nome + "?"


def _jargoes(explicacao, notas):
    hay = fold("\n".join(nota.get("texto") or "" for nota in notas))
    falado = fold(explicacao)
    vistos = []
    for token in _TOKEN.findall(falado):
        if len(token) < 9 or token in _PARADA or token in vistos:
            continue
        if not re.search(r"\b" + re.escape(token) + r"\b", hay):
            continue
        indice = falado.find(token)
        trecho = falado[indice : indice + len(token) + 40]
        if any(marca in trecho for marca in _GLOSA):
            continue
        vistos.append(token)
        if len(vistos) == 3:
            break
    return vistos


def _parse_cerebro(bruto, notas):
    if not str(bruto or "").strip() or not notas:
        return None
    lacunas = []
    erros = []
    jargoes = []
    rascunhos = []
    for tipo, corpo in _MARCA.findall(str(bruto)):
        tipo = fold(tipo)
        if tipo in {"jargao", "jargon"}:
            termo = _limpo(corpo, 40)
            if termo and not _recusado(termo) and termo not in jargoes:
                jargoes.append(termo)
            continue
        if tipo == "lacuna":
            nome = _limpo(corpo, 80)
            if nome and not _recusado(nome) and nome not in lacunas:
                lacunas.append(nome)
            continue
        if tipo == "erro":
            texto = _limpo(corpo, 120)
            if texto and not _recusado(texto) and len(erros) < 2:
                erros.append(texto)
            continue
        if tipo in {"cartao", "cartão"}:
            if ":::" not in corpo:
                continue
            pergunta, resposta = corpo.split(":::", 1)
            par = _par_cartao(pergunta, resposta)
            if par is None or len(rascunhos) >= 3:
                continue
            nota = _nota_melhor(notas, par[0] + " " + par[1])
            if nota is None:
                continue
            rascunhos.append(
                {"caminho": nota["caminho"], "pergunta": par[0], "resposta": par[1]}
            )
    if not lacunas and not erros and not jargoes and not rascunhos:
        return None
    return {
        "lacunas": lacunas[:3],
        "erros": erros[:2],
        "jargoes": jargoes[:3],
        "rascunhos": rascunhos[:3],
    }


def _prompt_explicacao(tema, explicacao, notas):
    from .privacidade import destino_atual, prompt_do_turno

    fontes = [
        {
            "origem": "fala",
            "texto": _limpo(explicacao, 1200),
            "sigiloso": False,
        }
    ]
    for nota in notas[:4]:
        fontes.append(
            {
                "origem": "nota",
                "texto": _limpo(nota["titulo"] + "\n" + (nota.get("texto") or ""), 700),
                "sigiloso": False,
            }
        )
    pedido = (
        "Compare a explicação com as notas do tema "
        + _limpo(tema, 80)
        + ". Aponte lacunas, erros e jargão. "
        "Responda só com linhas LACUNA:, ERRO:, JARGÃO: e CARTAO: pergunta ::: resposta. "
        "Não grave nota, não publique e não envie mensagem."
    )
    return prompt_do_turno(pedido, fontes, destino_atual())


def _plano(tema, notas):
    pontos = []
    for nota in notas:
        for ponto in _pontos_da_nota(nota):
            pontos.append(ponto)
            if len(pontos) == 6:
                break
        if len(pontos) == 6:
            break
    if not pontos:
        return []
    plano = []
    for indice in range(3):
        ponto = pontos[indice % len(pontos)]
        nivel = _NIVEIS[indice]
        plano.append(
            {
                "nivel": nivel,
                "caminho": ponto["caminho"],
                "tipo": ponto["tipo"],
                "chave": ponto["chave"],
                "rotulo": _rotulo(nivel, tema, ponto),
            }
        )
    return plano


def _rotulo(nivel, tema, ponto):
    nome = _limpo(ponto.get("nome") or "", 80)
    assunto = _limpo(tema, 80)
    if nivel == "o que" and ponto.get("tipo") == "cartao" and nome.endswith("?"):
        return nome
    if nivel == "o que":
        return "O que é " + nome + " em " + assunto + ", senhor?"
    if nivel == "por que":
        return "Por que " + nome + " importa em " + assunto + ", senhor?"
    return "Como " + nome + " funciona em " + assunto + ", senhor?"


def _pontos_da_nota(nota):
    from .review import parse_card_line

    pontos = []
    linhas = (nota.get("texto") or "").splitlines()
    for linha in linhas:
        par = parse_card_line(linha, nota.get("caminho") or "")
        if par is None:
            continue
        pergunta, resposta = par
        if _recusado(pergunta) or _recusado(resposta):
            continue
        pontos.append(_ponto("cartao", nota, pergunta, resposta))
    indice = 0
    while indice < len(linhas):
        match = re.match(r"^#{2,3}\s+(.+?)\s*$", linhas[indice].strip())
        indice += 1
        if not match:
            continue
        nome = " ".join(match.group(1).replace("[", "").replace("]", "").split())
        if not nome or fold(nome) in _GERADAS:
            continue
        frase = ""
        while indice < len(linhas):
            bruta = linhas[indice].strip()
            if bruta.startswith("#"):
                break
            indice += 1
            if not bruta or bruta.startswith("---") or ":::" in bruta:
                continue
            if bruta.startswith("- "):
                bruta = bruta[2:].strip()
            frase = bruta
            break
        if not frase or _recusado(nome) or _recusado(frase):
            continue
        pontos.append(_ponto("titulo", nota, nome, frase))
    return pontos


def _ponto(tipo, nota, nome, esperado):
    return {
        "tipo": tipo,
        "caminho": nota["caminho"],
        "nome": _limpo(nome, 80),
        "esperado": _limpo(esperado, 160),
        "chave": fold(nome)[:80],
    }


def aplicar_rascunhos(root, itens):
    from .guardas import FALA_BLOQUEIO, GuardError, escrever
    from .leitura import ler_texto
    from .privacidade import nota_sigilosa
    from .trava import fila_escrita

    preparados = []
    for item in itens or []:
        if not isinstance(item, dict):
            continue
        caminho = str(item.get("caminho") or "").replace("\\", "/")
        par = _par_cartao(item.get("pergunta"), item.get("resposta"))
        if not caminho or par is None:
            continue
        path = _destino_nota(root, caminho)
        if path is None:
            continue
        preparados.append((path, caminho, par))
    if not preparados:
        return "Não gravei rascunho, senhor. Não havia lacuna válida."
    gravados = 0
    try:
        with fila_escrita():
            grupos = {}
            ordem = []
            for path, caminho, par in preparados:
                if not path.is_file():
                    continue
                try:
                    atual = ler_texto(path)
                except (OSError, UnicodeError):
                    continue
                if nota_sigilosa(root, caminho, atual):
                    continue
                chave = path.as_posix()
                if chave not in grupos:
                    grupos[chave] = [path, atual, []]
                    ordem.append(chave)
                linha = "- [rascunho] " + par[0] + " ::: " + par[1]
                if linha not in grupos[chave][2] and linha not in grupos[chave][1]:
                    grupos[chave][2].append(linha)
            if not ordem:
                return "Não gravei rascunho, senhor. Não havia lacuna válida."
            for chave in ordem:
                path, atual, linhas = grupos[chave]
                if not linhas:
                    continue
                novo = _acrescentar(atual, linhas)
                escrever(path, novo, checar="\n".join(linhas), raiz=root)
                gravados += len(linhas)
    except GuardError:
        return FALA_BLOQUEIO
    if gravados == 0:
        return "Não gravei rascunho, senhor. Não havia lacuna válida."
    LOG.info("rascunhos de explicacao gravados: %s", gravados)
    if gravados == 1:
        fala = "Gravei 1 cartão em rascunho, senhor."
    else:
        fala = f"Gravei {gravados} cartões em rascunho, senhor."
    return fala + " Diga revisa rascunhos para conferir."


def gravar_revisao(root, respostas, now):
    from .guardas import FALA_BLOQUEIO, GuardError, escrever
    from .trava import fila_escrita

    dia = _data(now)
    path = caminho_revisao(root, dia)
    if path is None:
        return "Não gravei a revisão, senhor. O destino ficou fora do vault."
    limpas = [_limpo(item, 400) for item in (respostas or [])]
    while len(limpas) < 4:
        limpas.append("")
    if any(_recusado(item) for item in limpas if item):
        return "Não gravei a revisão, senhor. Uma frase tem cara de segredo."
    contexto = montar_contexto(root, now)
    corpo = render_revisao(semana_iso(dia), contexto, limpas[:4])
    existia = path.is_file()
    try:
        with fila_escrita():
            escrever(path, corpo, checar=corpo, raiz=root)
    except GuardError:
        return FALA_BLOQUEIO
    guardar_foco(proxima_semana(dia), limpas[3])
    LOG.info("revisao semanal gravada")
    if existia:
        return "Atualizei a revisão semanal, senhor. O foco entra na próxima semana."
    return "Gravei a revisão semanal, senhor. O foco entra na próxima semana."


def render_revisao(semana, contexto, respostas):
    linhas = ["# Revisão semanal " + semana, "", "## Contexto", ""]
    linhas.extend(contexto.get("linhas") or ["- Sem contexto público."])
    for titulo, resposta in zip(_TITULOS, respostas):
        linhas.extend(["", "## " + titulo, "", resposta or ""])
    linhas.append("")
    return "\n".join(linhas)


def caminho_revisao(root, dia):
    from . import config

    pasta = config.revisao_semanal_pasta().strip("/")
    return _destino_nota(root, pasta + "/" + nome_revisao(dia))


def guardar_foco(semana, texto):
    from . import config
    from .trava import gravar_atomico, trava_arquivo

    if not _ISO.match(str(semana or "")):
        return False
    limpo = _limpo(texto, 180)
    if not limpo or _recusado(limpo):
        return False
    path = config.jarvis_home() / "foco-semana.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    bruto = json.dumps(
        {"versao": 1, "semana": semana, "foco": limpo},
        ensure_ascii=False,
        indent=2,
    )
    with trava_arquivo(path.with_name(path.name + ".lock"), mensagem="foco ocupado"):
        gravar_atomico(path, bruto + "\n", mode=0o600)
    LOG.info("foco da semana guardado")
    return True


def _empacotar_contexto(criadas, stats, metas, fins):
    frases = []
    linhas = []
    if criadas:
        nomes = _join_pt([nota["titulo"] for nota in criadas])
        frases.append("Nesta semana entrou " + _contagem(len(criadas), "nota", "notas") + ": " + nomes + ".")
        linhas.append(
            "- Notas da semana: "
            + _join_pt([nota["titulo"] + " (" + nota["caminho"] + ")" for nota in criadas])
        )
    else:
        frases.append("Nesta semana não entrou nota pública.")
        linhas.append("- Notas da semana: nenhuma nota pública.")
    frases.append(_frase_stats(stats))
    linhas.append("- Revisão: " + _linha_stats(stats))
    if metas:
        frases.append(_join_pt([item["fala"] for item in metas]) + ".")
        linhas.append("- Metas: " + _join_pt([item["linha"] for item in metas]))
    else:
        frases.append("Não há meta de estudo guardada.")
        linhas.append("- Metas: nenhuma.")
    if fins:
        for nota in fins:
            balas = _anotacoes(nota.get("texto") or "")
            dia = _FIM.match(Path(nota["caminho"]).name).group(1)
            if balas:
                frases.append("Fim do dia " + dia + ": " + _join_pt(balas) + ".")
                linhas.append("- Fim do dia " + dia + ": " + _join_pt(balas))
            else:
                frases.append("Há fechamento de fim do dia em " + dia + ".")
                linhas.append("- Fim do dia " + dia + ": sem anotação pública.")
    else:
        frases.append("Não há fechamento de fim do dia nesta semana.")
        linhas.append("- Fim do dia: nenhum.")
    return {"frases": frases, "linhas": linhas}


def _frase_stats(stats):
    return (
        "Na revisão espaçada há "
        + _contagem(stats["total"], "cartão", "cartões")
        + ", "
        + str(stats["revisados"])
        + " já "
        + ("passou" if stats["revisados"] == 1 else "passaram")
        + ", "
        + _contagem(stats["lapsos"], "lapso", "lapsos")
        + " e "
        + str(stats["vencem"])
        + " na fila até domingo."
    )


def _linha_stats(stats):
    return (
        str(stats["total"])
        + " cartões, "
        + str(stats["revisados"])
        + " já passaram, "
        + str(stats["lapsos"])
        + " lapsos, "
        + str(stats["vencem"])
        + " na fila até domingo"
    )


def _progresso_metas(root, fim):
    from .review import scan_cards

    cartoes = scan_cards(root)
    saida = []
    for tema in _listar_temas():
        ligados = [cartao for cartao in cartoes if _casa_cartao(cartao, tema)]
        if not ligados:
            saida.append(
                {
                    "fala": "Meta " + tema + ": ainda não há cartão ligado ao tema",
                    "linha": tema + ", sem cartão ligado",
                }
            )
            continue
        stats = _stats(ligados, fim)
        saida.append(
            {
                "fala": (
                    "Meta "
                    + tema
                    + ": "
                    + _contagem(stats["total"], "cartão", "cartões")
                    + ", "
                    + str(stats["revisados"])
                    + " já "
                    + ("passou" if stats["revisados"] == 1 else "passaram")
                    + ", "
                    + _contagem(stats["lapsos"], "lapso", "lapsos")
                ),
                "linha": (
                    tema
                    + ", "
                    + str(stats["total"])
                    + " cartões, "
                    + str(stats["revisados"])
                    + " já passaram, "
                    + str(stats["lapsos"])
                    + " lapsos"
                ),
            }
        )
    return saida


def _stats(cartoes, limite):
    from .review import load_state

    estado = load_state()
    registros = estado.get("cards") if isinstance(estado.get("cards"), dict) else {}
    revisados = 0
    lapsos = 0
    vencem = 0
    teto = limite.isoformat()
    for cartao in cartoes:
        registro = registros.get(cartao["id"]) if isinstance(registros.get(cartao["id"]), dict) else {}
        reps = _inteiro(registro.get("reps"))
        lapsos += _inteiro(registro.get("lapses"))
        if reps > 0:
            revisados += 1
        due = str(registro.get("due") or "")
        if not due or due <= teto:
            vencem += 1
    return {
        "total": len(cartoes),
        "revisados": revisados,
        "lapsos": lapsos,
        "vencem": vencem,
    }


def _anotacoes(texto):
    dentro = False
    achados = []
    for linha in (texto or "").splitlines():
        if linha.startswith("#"):
            nome = fold(linha).lstrip("#").strip()
            dentro = nome.startswith("anotac")
            continue
        if not dentro:
            continue
        match = re.match(r"^\s*-\s+(.+)$", linha)
        if not match:
            continue
        bala = _limpo(match.group(1), 80)
        if not bala or _recusado(bala):
            continue
        achados.append(bala)
        if len(achados) == 3:
            break
    return achados


def _notas_do_tema(root, tema):
    from .conhecimento import _notas_publicas

    notas = []
    for nota in _notas_publicas(root):
        if tema and not _casa_nota(nota, tema):
            continue
        notas.append(
            {
                "caminho": str(nota["caminho"]).replace("\\", "/"),
                "titulo": nota["titulo"],
                "texto": nota.get("texto") or "",
                "mtime": nota.get("mtime") or 0,
            }
        )
    return notas


def _contar_privadas(root, tema):
    from .catalogo import obter
    from .privacidade import nota_sigilosa

    try:
        catalogo = obter(root)
    except Exception:
        return 0
    total = 0
    for nota in catalogo.notas.values():
        if not nota.util:
            continue
        caminho = str(nota.relative or "").replace("\\", "/")
        if not nota_sigilosa(root, caminho, nota.texto):
            continue
        if tema and not _casa_bruto(nota.titulo or "", caminho, nota.texto or "", tema):
            continue
        total += 1
    return total


def _casa_nota(nota, tema):
    return _casa_bruto(nota.get("titulo") or "", nota.get("caminho") or "", nota.get("texto") or "", tema)


def _casa_bruto(titulo, caminho, texto, tema):
    tokens = _tokens(tema)
    if not tokens:
        return False
    hay = fold(titulo + "\n" + caminho + "\n" + (texto or "")[:4000])
    return all(token in hay for token in tokens)


def _casa_cartao(cartao, tema):
    tokens = _tokens(tema)
    if not tokens:
        return False
    hay = fold(
        (cartao.get("question") or "")
        + " "
        + (cartao.get("path") or "")
        + " "
        + " ".join(cartao.get("tags") or [])
    )
    return all(token in hay for token in tokens)


def _nota_melhor(notas, texto):
    tokens = _tokens(texto)
    melhor = None
    pontuacao = -1
    for nota in notas:
        hay = set(_tokens((nota.get("titulo") or "") + " " + (nota.get("texto") or "")[:1500]))
        score = sum(1 for token in tokens if token in hay)
        if score > pontuacao:
            pontuacao = score
            melhor = nota
    if melhor is not None:
        return melhor
    return notas[0] if notas else None


def _nota_dict(caminho, texto):
    return {
        "caminho": caminho,
        "titulo": Path(caminho).stem,
        "texto": texto,
    }


def _listar_temas():
    from . import config
    from .conhecimento import _ler_json

    dados = _ler_json(config.jarvis_home() / "metas.json")
    metas = dados.get("metas") if isinstance(dados.get("metas"), dict) else {}
    vistos = []
    for item in metas.values():
        if not isinstance(item, dict):
            continue
        tema = _limpo(item.get("tema") or "", 80)
        if not tema or _recusado(tema) or tema in vistos:
            continue
        vistos.append(tema)
    return vistos


def _meta_que_casa(tema):
    tokens = _tokens(tema)
    if not tokens:
        return ""
    melhor = ""
    extra = 999
    for meta in _listar_temas():
        outros = _tokens(meta)
        if not outros:
            continue
        if not (all(token in outros for token in tokens) or all(token in tokens for token in outros)):
            continue
        sobra = abs(len(outros) - len(tokens))
        if sobra < extra:
            extra = sobra
            melhor = meta
    return melhor


def _ler_foco():
    from . import config

    path = config.jarvis_home() / "foco-semana.json"
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _acrescentar(texto, linhas):
    corpo = texto or ""
    if corpo and not corpo.endswith("\n"):
        corpo += "\n"
    if "## Cartões" not in corpo and "## Cartoes" not in corpo:
        corpo += "\n## Cartões\n"
    if not corpo.endswith("\n"):
        corpo += "\n"
    for linha in linhas:
        corpo += linha + "\n"
    return corpo


def _destino_nota(root, relativa):
    from .guardas import caminho_bloqueado, caminho_dentro
    from .paths import caminho_relativo

    safe = caminho_relativo(relativa, exigir_md=True)
    if not safe:
        return None
    path = Path(root) / safe
    if caminho_bloqueado(path) or not caminho_dentro(root, path):
        return None
    return path


def _intervalo(dia):
    iso = dia.isocalendar()
    inicio = date.fromisocalendar(iso.year, iso.week, 1)
    fim = date.fromisocalendar(iso.year, iso.week, 7)
    return inicio, fim


def _data(now):
    if isinstance(now, datetime):
        return now.date()
    return now


def _mtime_date(nota, tz):
    try:
        bruto = float(nota.get("mtime") or 0)
    except (TypeError, ValueError):
        return None
    if bruto <= 0:
        return None
    try:
        if tz is None:
            return datetime.fromtimestamp(bruto).date()
        return datetime.fromtimestamp(bruto, tz).date()
    except (OverflowError, OSError, ValueError):
        return None


def _cobre(tokens, falado):
    unicos = list(dict.fromkeys(tokens))
    if not unicos:
        return False
    acertos = sum(1 for token in unicos if token in falado)
    return acertos >= max(1, (len(unicos) + 1) // 2)


def _tokens(texto):
    return [token for token in _TOKEN.findall(fold(texto)) if token not in _PARADA]


def _tema_limpo(tema):
    return _limpo(tema, 80)


def _resposta_usuario(message):
    texto = normalize_phrase(message or "")
    return _limpo(texto, 400)


def _limpo(valor, limite):
    texto = str(valor or "").replace("\u2014", " ").replace("\u2013", " ")
    texto = " ".join(texto.split())
    return texto[:limite].strip()


def _recusado(texto):
    from .guardas import texto_secreto

    bruto = str(texto or "")
    if not bruto.strip():
        return False
    return bool(_RUIM.search(bruto) or texto_secreto(bruto))


def _par_cartao(pergunta, resposta):
    pergunta = _limpo(pergunta, 120)
    resposta = _limpo(resposta, 180)
    if not pergunta or not resposta:
        return None
    if ":::" in pergunta or ":::" in resposta:
        return None
    if _recusado(pergunta) or _recusado(resposta):
        return None
    return pergunta, resposta


def _contagem(total, um, varios):
    if total == 1:
        return "1 " + um
    return str(total) + " " + varios


def _fala_privadas(total):
    if total == 1:
        return "Deixei de fora 1 nota privada."
    return f"Deixei de fora {total} notas privadas."


def _inteiro(valor):
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _limpar_sessao():
    try:
        from .review import _write_session

        _write_session(None)
    except Exception:
        LOG.info("sessao de estudo nao limpa")
