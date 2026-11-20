"""Progresso do estudo: contagens e títulos, sem corpo de nota.

Nota com #sigiloso ou em pasta privada fica de fora do painel, da fala
e da exportação. O arquivo do Anki sai de ~/.jarvis e não vai para o vault.
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .log import LOG
from .paths import caminho_relativo, windows_drive
from .routines import fold

SEM_VAULT = (
    "O vault não está configurado, senhor. Sem ele eu não leio as notas. "
    "Rode python -m jarvis.setup."
)
_ZONA = ZoneInfo("America/Sao_Paulo")
_SEMANAS = 6
_TITULOS = 12
_EXTENSOES = {".txt", ".tsv"}
_RESERVADOS = {
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
}


def montar(root, now=None):
    """Números e títulos do estudo. Não devolve corpo de nota nem cartão."""
    momento = now or _agora(root)
    hoje = _hoje(root, momento)
    inicio, fim, rotulo = _semana_de(hoje)
    from .review import cards_until, load_state, streak_length

    estado = load_state()
    cartoes = _cartoes_publicos(root)
    vencidos_hoje = len(cards_until(cartoes, estado, hoje, hoje))
    vencidos_semana = len(cards_until(cartoes, estado, hoje, fim))
    diario = estado.get("diario") if isinstance(estado.get("diario"), list) else []
    days = [str(item) for item in (estado.get("days") or [])]
    daily = estado.get("daily") if isinstance(estado.get("daily"), dict) else {}
    feitos_hoje = 0
    if daily.get("date") == hoje.isoformat():
        feitos_hoje = _inteiro(daily.get("count"))
    revisou_hoje = hoje.isoformat() in days or feitos_hoje > 0
    semanas = _janela(inicio)
    notas = _notas_por_semana(root, momento, semanas)
    acertos = _acertos_por_semana(diario, semanas)
    atual = _da_semana(acertos, rotulo)
    certos = atual["certos"]
    erros = atual["erros"]
    total_acerto = certos + erros
    acerto = None if total_acerto <= 0 else int(round(100 * certos / total_acerto))
    notas_atual = _da_semana_notas(notas, rotulo)
    from .reflexao import _listar_temas, _stats, ultimo_foco

    metas = []
    for tema in _listar_temas():
        ligados = [card for card in cartoes if _casa(card, tema)]
        stats = _stats(ligados, fim)
        total = int(stats["total"])
        revisados = int(stats["revisados"])
        metas.append(
            {
                "tema": tema,
                "cartoes": total,
                "revisados": revisados,
                "lapsos": int(stats["lapsos"]),
                "vencem": int(stats["vencem"]),
                "percentual": 0 if total <= 0 else int(round(100 * revisados / total)),
            }
        )
    foco = ultimo_foco()
    from .__version__ import __version__
    from .sessao import dias_com_estudo, minutos_da_meta, resumo as resumo_estudo

    estudo = resumo_estudo(momento)
    dias_estudo = set(dias_com_estudo())
    juntos = sorted({str(item) for item in days} | dias_estudo)
    for meta in metas:
        meta["minutos"] = minutos_da_meta(meta.get("tema") or "", momento)

    return {
        "versao": __version__,
        "hoje": hoje.isoformat(),
        "semana": rotulo,
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "vencidos_hoje": vencidos_hoje,
        "vencidos_semana": vencidos_semana,
        "feitos_hoje": feitos_hoje,
        "feitos_semana": certos + erros,
        "dias_semana": sum(1 for item in days if _na_semana(item, inicio, fim)),
        "sequencia": streak_length(juntos, hoje),
        "revisou_hoje": revisou_hoje,
        "estudou_hoje": hoje.isoformat() in dias_estudo,
        "minutos_hoje": int(estudo.get("minutos_hoje") or 0),
        "minutos_semana": int(estudo.get("minutos_semana") or 0),
        "temas_estudo": list(estudo.get("temas") or []),
        "dias_estudo": list(estudo.get("por_dia") or []),
        "acerto_semana": acerto,
        "acertos": acertos,
        "notas": notas,
        "notas_semana": notas_atual["total"],
        "titulos_semana": list(notas_atual["titulos"][:3]),
        "metas": metas,
        "foco": {"semana": foco.get("semana") or "", "texto": foco.get("texto") or ""},
    }


def falar_semana(root, now=None):
    if root is None:
        return SEM_VAULT
    dados = montar(root, now)
    partes = [
        "Nesta semana, senhor, há "
        + _n(dados["vencidos_hoje"], "cartão para hoje", "cartões para hoje")
        + " e "
        + _n(dados["vencidos_semana"], "cartão até domingo", "cartões até domingo")
        + "."
    ]
    feitos = dados["feitos_semana"]
    dias = dados["dias_semana"]
    if feitos <= 0 and dias <= 0:
        partes.append("Ainda não houve revisão nesta semana.")
    elif feitos <= 0:
        partes.append("Houve revisão em " + _n(dias, "dia", "dias") + ".")
    else:
        frase = "Você revisou " + _n(feitos, "cartão", "cartões")
        if dias:
            frase += " em " + _n(dias, "dia", "dias")
        partes.append(frase + ".")
        if dados["acerto_semana"] is not None:
            partes.append("O acerto da semana está em " + str(dados["acerto_semana"]) + "%.")
    notas = dados["notas_semana"]
    if notas <= 0:
        partes.append("Não entrou nota pública nesta semana.")
    else:
        mostrados = dados["titulos_semana"]
        frase = "Entrou " + _n(notas, "nota", "notas")
        if mostrados:
            frase += ": " + ", ".join(mostrados)
        extra = notas - len(mostrados)
        if extra > 0:
            frase += " e mais " + str(extra)
        partes.append(frase + ".")
    partes.append(_frase_estudo(dados))
    partes.append("A sequência está em " + _n(dados["sequencia"], "dia", "dias") + ".")
    foco = (dados.get("foco") or {}).get("texto") or ""
    if foco:
        partes.append("O foco da última revisão semanal é " + foco + ".")
    return " ".join(partes)


def falar_sequencia(root, now=None):
    dados = montar(root, now)
    total = dados["sequencia"]
    if total <= 0:
        return (
            "A sequência está em zero, senhor. "
            "Uma revisão ou uma sessão de estudo hoje começa de novo."
        )
    unidade = "dia" if total == 1 else "dias"
    if dados["revisou_hoje"] and dados.get("estudou_hoje"):
        extra = "A revisão e o estudo de hoje já entraram."
    elif dados["revisou_hoje"]:
        extra = "A revisão de hoje já entrou."
    elif dados.get("estudou_hoje"):
        extra = "O estudo de hoje já entrou."
    else:
        extra = "A revisão de hoje ainda não foi feita."
    return "A sequência está em " + str(total) + " " + unidade + ", senhor. " + extra


def preparar_anki(root, tema, now=None):
    assunto = _tema(tema)
    if assunto is None:
        return "Não exportei, senhor. O tema não serve.", None
    if root is None:
        return SEM_VAULT, None
    total = len(_filtrar(_cartoes_publicos(root), assunto))
    if total <= 0:
        if assunto:
            return "Não há cartão público sobre " + assunto + ", senhor.", None
        return "Não há cartão público para exportar, senhor.", None
    frase = (
        "Posso exportar "
        + _n(total, "cartão público", "cartões públicos")
        + (" sobre " + assunto if assunto else "")
        + " para a pasta de exportações, senhor. "
        + "O arquivo fica fora do vault. Diga sim para gravar. Diga não para cancelar."
    )
    return frase, {"kind": "anki", "tema": assunto}


def concluir_anki(root, pending, now=None):
    assunto = _tema((pending or {}).get("tema") or "")
    if assunto is None:
        return "Não exportei, senhor. O tema não serve."
    if root is None:
        return SEM_VAULT
    try:
        resultado = exportar(root, tema=assunto, saida="", gravar=True, now=now)
    except Exception:
        LOG.info("exportacao anki falhou")
        return "Não consegui exportar os cartões, senhor."
    if resultado.get("erro") == "vault":
        return SEM_VAULT
    if resultado.get("erro") == "caminho":
        return "Não exportei, senhor. O arquivo ficaria dentro do vault."
    if resultado.get("erro"):
        return "Não consegui exportar os cartões, senhor."
    total = int(resultado.get("total") or 0)
    if total <= 0 or not resultado.get("gravou"):
        return "Não havia cartão público para exportar, senhor."
    LOG.info("exportacao anki: %s cartoes", total)
    return (
        "Exportei "
        + _n(total, "cartão", "cartões")
        + ", senhor. O arquivo ficou na pasta de exportações."
    )


def exportar(root, tema="", saida="", gravar=False, now=None):
    """Conta os cartões públicos. Grava o texto só quando gravar é verdadeiro."""
    if root is None:
        return {"erro": "vault", "total": 0, "gravou": False, "caminho": ""}
    assunto = _tema(tema)
    if assunto is None:
        return {"erro": "tema", "total": 0, "gravou": False, "caminho": ""}
    cartoes = _filtrar(_cartoes_publicos(root), assunto)
    total = len(cartoes)
    if not gravar or total <= 0:
        return {"erro": "", "total": total, "gravou": False, "caminho": ""}
    caminho = destino_arquivo(saida, root, now or _agora(root), assunto)
    if caminho is None:
        return {"erro": "caminho", "total": total, "gravou": False, "caminho": ""}
    from .trava import gravar_atomico, trava_arquivo

    corpo = render_tsv(cartoes)
    trava = caminho.with_name(caminho.name + ".lock")
    with trava_arquivo(trava, mensagem="exportacao ocupada"):
        gravar_atomico(caminho, corpo, mode=0o600)
    LOG.info("exportacao anki: %s cartoes", total)
    return {"erro": "", "total": total, "gravou": True, "caminho": str(caminho)}


def destino_arquivo(pedido, root, now, tema=""):
    """Caminho fora do vault. Relativo cai em ~/.jarvis/exportacoes."""
    from . import config

    base = (config.jarvis_home() / "exportacoes").resolve()
    texto = str(pedido or "").strip().strip("\"'")
    if not texto:
        if not _fora(base, root):
            return None
        return _novo_nome(base, now, tema, root)
    if _texto_recusado(texto):
        return None
    if windows_drive(texto) or Path(texto).expanduser().is_absolute():
        if windows_drive(texto) and os.name != "nt":
            return None
        return _absoluto(Path(texto).expanduser(), root)
    relativo = caminho_relativo(texto)
    if not relativo or _texto_recusado(relativo):
        return None
    alvo = base / _com_extensao(relativo)
    if alvo.exists() and alvo.is_dir():
        return None
    if not _caminho_seguro(alvo, root, base):
        return None
    return alvo


def render_tsv(cartoes):
    linhas = []
    for card in cartoes or []:
        frente = _campo(card.get("question"))
        verso = _campo(card.get("answer"))
        if not frente or not verso:
            continue
        linhas.append(frente + "\t" + verso + "\t" + _etiquetas(card.get("tags")))
    if not linhas:
        return ""
    return "\n".join(linhas) + "\n"


def texto_toque(root, now):
    """Aviso da noite. Vazio no modo privado. None quando a revisão do dia já foi feita."""
    from .privacidade import modo_privado_ativo

    if modo_privado_ativo() or root is None:
        return ""
    dados = montar(root, now)
    if dados["revisou_hoje"] or dados.get("estudou_hoje"):
        return None
    total = dados["sequencia"]
    if total <= 0:
        return "Boa noite, senhor. Ainda não houve revisão hoje."
    unidade = "dia" if total == 1 else "dias"
    return (
        "Boa noite, senhor. Ainda não houve revisão hoje. "
        + "A sequência está em "
        + str(total)
        + " "
        + unidade
        + "."
    )


def render_progresso(payload, token):
    dados = payload if isinstance(payload, dict) else {}
    foco = dados.get("foco") if isinstance(dados.get("foco"), dict) else {}
    foco_texto = foco.get("texto") or ""
    if foco_texto:
        foco_html = _esc(foco_texto)
        if foco.get("semana"):
            foco_html += " <span class=\"semana\">(" + _esc(foco["semana"]) + ")</span>"
    else:
        foco_html = "Nenhuma revisão semanal registrada."
    return """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Progresso do estudo</title>
<style>
body {{ margin: 0; background: #061120; color: #cfe9f7; font: 15px/1.5 Menlo, Consolas, monospace; }}
main {{ max-width: 760px; margin: 0 auto; padding: 28px 20px 48px; }}
a {{ color: #8ae6ff; }}
h1 {{ font-weight: 600; letter-spacing: 0.14em; font-size: 20px; }}
h2 {{ font-size: 16px; font-weight: 600; margin: 0 0 10px; }}
section {{ border: 1px solid rgba(80, 180, 235, 0.2); padding: 16px 18px; margin-top: 18px; }}
dl {{ display: grid; grid-template-columns: 12em 1fr; gap: 6px 12px; margin: 0; }}
dt {{ color: #5f8aa6; }}
dd {{ margin: 0; }}
ul {{ margin: 8px 0 0; padding-left: 18px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid rgba(80, 180, 235, 0.16); }}
.trilho {{ height: 8px; background: rgba(80, 180, 235, 0.16); margin-top: 6px; }}
.trilho span {{ display: block; height: 8px; background: #8ae6ff; }}
.semana {{ color: #5f8aa6; }}
.vazio {{ color: #5f8aa6; }}
</style>
</head>
<body>
<main>
<p><a href="{voltar}">Voltar ao painel</a></p>
<h1>Progresso</h1>
<p>Versão {versao}. Semana {semana}, de {inicio} a {fim}.</p>
<section>
<h2>Tempo de estudo</h2>
<dl>
<dt>Hoje</dt><dd>{minutos_hoje}</dd>
<dt>Nesta semana</dt><dd>{minutos_semana}</dd>
</dl>
{temas_estudo}
</section>
<section>
<h2>Revisão</h2>
<dl>
<dt>Para hoje</dt><dd>{hoje}</dd>
<dt>Até domingo</dt><dd>{ate}</dd>
<dt>Feitos hoje</dt><dd>{feitos_hoje}</dd>
<dt>Nesta semana</dt><dd>{feitos}</dd>
<dt>Dias com revisão</dt><dd>{dias}</dd>
<dt>Sequência</dt><dd>{sequencia}</dd>
<dt>Acerto da semana</dt><dd>{acerto}</dd>
</dl>
</section>
<section>
<h2>Tendência de acerto</h2>
{tendencia}
</section>
<section>
<h2>Notas por semana</h2>
{notas}
</section>
<section>
<h2>Metas</h2>
{metas}
</section>
<section>
<h2>Foco da última revisão semanal</h2>
<p>{foco}</p>
</section>
</main>
</body>
</html>
""".format(
        voltar="/?t=" + _esc(token),
        versao=_esc(dados.get("versao") or ""),
        semana=_esc(dados.get("semana") or ""),
        inicio=_esc(dados.get("inicio") or ""),
        fim=_esc(dados.get("fim") or ""),
        hoje=int(dados.get("vencidos_hoje") or 0),
        ate=int(dados.get("vencidos_semana") or 0),
        feitos_hoje=int(dados.get("feitos_hoje") or 0),
        feitos=int(dados.get("feitos_semana") or 0),
        dias=int(dados.get("dias_semana") or 0),
        minutos_hoje=_esc(_rotulo_minutos(int(dados.get("minutos_hoje") or 0))),
        minutos_semana=_esc(_rotulo_minutos(int(dados.get("minutos_semana") or 0))),
        temas_estudo=_lista_temas_estudo(dados.get("temas_estudo") or []),
        sequencia=_esc(_rotulo_dias(int(dados.get("sequencia") or 0))),
        acerto=_esc(_rotulo_acerto(dados.get("acerto_semana"))),
        tendencia=_tabela_acertos(dados.get("acertos") or []),
        notas=_lista_notas(dados.get("notas") or []),
        metas=_lista_metas(dados.get("metas") or []),
        foco=foco_html,
    )


def _tabela_acertos(linhas):
    if not linhas:
        return "<p class=\"vazio\">Sem revisão registrada.</p>"
    corpo = []
    for item in linhas:
        certos = int(item.get("certos") or 0)
        erros = int(item.get("erros") or 0)
        total = certos + erros
        if total <= 0:
            marca = "sem dados"
            barra = _barra(0)
        else:
            percentual = int(round(100 * certos / total))
            marca = str(percentual) + "%"
            barra = _barra(percentual)
        corpo.append(
            "<tr><td>"
            + _esc(item.get("semana"))
            + "</td><td>"
            + str(certos)
            + "</td><td>"
            + str(erros)
            + "</td><td>"
            + marca
            + barra
            + "</td></tr>"
        )
    return (
        "<table><thead><tr><th>Semana</th><th>Acertos</th><th>Erros</th>"
        "<th>Percentual</th></tr></thead><tbody>"
        + "".join(corpo)
        + "</tbody></table>"
        + "<p class=\"semana\">Acertos contam difícil, bom, fácil e acertei. Errei conta como erro.</p>"
    )


def _lista_notas(linhas):
    if not linhas:
        return "<p class=\"vazio\">Nenhuma nota pública.</p>"
    blocos = []
    for item in linhas:
        total = int(item.get("total") or 0)
        titulos = item.get("titulos") or []
        if total <= 0:
            detalhe = "<p class=\"vazio\">Nenhuma nota pública.</p>"
        else:
            itens = "".join("<li>" + _esc(titulo) + "</li>" for titulo in titulos)
            extra = total - len(titulos)
            if extra > 0:
                itens += "<li>e mais " + str(extra) + "</li>"
            detalhe = "<ul>" + itens + "</ul>"
        blocos.append(
            "<h3>"
            + _esc(item.get("semana"))
            + " <span class=\"semana\">"
            + _n(total, "nota", "notas")
            + "</span></h3>"
            + detalhe
        )
    return "".join(blocos)


def _lista_metas(metas):
    if not metas:
        return "<p class=\"vazio\">Nenhuma meta de estudo.</p>"
    blocos = []
    for item in metas:
        total = int(item.get("cartoes") or 0)
        percentual = int(item.get("percentual") or 0)
        if total <= 0:
            detalhe = (
                "Sem cartão ligado. "
                + _rotulo_minutos(int(item.get("minutos") or 0))
                + " de sessão nesta semana."
            )
        else:
            detalhe = (
                str(int(item.get("revisados") or 0))
                + " de "
                + str(total)
                + " já passaram. "
                + _n(int(item.get("lapsos") or 0), "lapso", "lapsos")
                + ". "
                + _n(int(item.get("vencem") or 0), "vence até domingo", "vencem até domingo")
                + ". "
                + _rotulo_minutos(int(item.get("minutos") or 0))
                + " de sessão nesta semana."
            )
        blocos.append(
            "<h3>"
            + _esc(item.get("tema"))
            + "</h3><p>"
            + detalhe
            + "</p>"
            + _barra(percentual)
        )
    return "".join(blocos)


def _frase_estudo(dados):
    minutos = int(dados.get("minutos_semana") or 0)
    if minutos <= 0:
        return "Ainda não houve sessão de estudo nesta semana."
    frase = "As sessões de estudo somam " + _n(minutos, "minuto", "minutos")
    temas = dados.get("temas_estudo") or []
    if temas:
        pedacos = []
        for item in temas[:3]:
            pedacos.append(
                str(item.get("tema") or "") + " " + str(int(item.get("minutos") or 0))
            )
        frase += ". Por tema: " + ", ".join(pedacos)
    return frase + "."


def _lista_temas_estudo(temas):
    if not temas:
        return "<p class=\"vazio\">Nenhuma sessão nesta semana.</p>"
    itens = []
    for item in temas:
        itens.append(
            "<li>"
            + _esc(item.get("tema") or "")
            + " "
            + _esc(_rotulo_minutos(int(item.get("minutos") or 0)))
            + "</li>"
        )
    return "<ul>" + "".join(itens) + "</ul>"


def _rotulo_minutos(total):
    if int(total) == 1:
        return "1 minuto"
    return str(int(total)) + " minutos"


def _barra(percentual):
    valor = max(0, min(100, int(percentual or 0)))
    return '<div class="trilho"><span style="width:' + str(valor) + '%"></span></div>'


def _cartoes_publicos(root):
    if root is None:
        return []
    from .privacidade import pode_enviar
    from .review import scan_cards

    saida = []
    for card in scan_cards(root):
        caminho = str(card.get("path") or "").replace("\\", "/")
        if not caminho or caminho.startswith(".") or "/." in ("/" + caminho):
            continue
        if _obsidian(caminho):
            continue
        if not pode_enviar(root, caminho, "painel"):
            continue
        saida.append(card)
    return saida


def _filtrar(cartoes, tema):
    if not tema:
        return list(cartoes or [])
    return [card for card in cartoes or [] if _casa(card, tema)]


def _casa(card, tema):
    tokens = [token for token in fold(tema).split() if len(token) >= 3]
    if not tokens:
        tokens = [token for token in fold(tema).split() if token]
    if not tokens:
        return False
    hay = fold(
        (card.get("question") or "")
        + " "
        + (card.get("path") or "")
        + " "
        + " ".join(card.get("tags") or [])
    )
    return all(token in hay for token in tokens)


def _notas_por_semana(root, momento, semanas):
    grupos = {item["semana"]: [] for item in semanas}
    if root is None:
        return [_pacote_notas(item, []) for item in semanas]
    from .catalogo import obter
    from .privacidade import pode_enviar

    try:
        catalogo = obter(root)
    except Exception:
        catalogo = None
    notas = []
    if catalogo is not None:
        notas = list(catalogo.notas.values())
    zona = momento.tzinfo if isinstance(momento, datetime) else _ZONA
    for nota in notas:
        if not getattr(nota, "util", False):
            continue
        caminho = str(getattr(nota, "relative", "") or "").replace("\\", "/")
        if not caminho or caminho.startswith(".") or "/." in ("/" + caminho):
            continue
        if _obsidian(caminho):
            continue
        texto = getattr(nota, "texto", None)
        if not pode_enviar(root, caminho, "painel", texto):
            continue
        dia = _dia_mtime(getattr(nota, "mtime_ns", 0), zona)
        if dia is None:
            continue
        _inicio, _fim, rotulo = _semana_de(dia)
        if rotulo not in grupos:
            continue
        titulo = " ".join(str(getattr(nota, "titulo", "") or Path(caminho).stem).split())[:120]
        if titulo:
            grupos[rotulo].append(titulo)
    return [_pacote_notas(item, grupos[item["semana"]]) for item in semanas]


def _pacote_notas(semana, titulos):
    ordenados = sorted(titulos, key=fold)
    return {
        "semana": semana["semana"],
        "inicio": semana["inicio"],
        "fim": semana["fim"],
        "total": len(ordenados),
        "titulos": ordenados[:_TITULOS],
    }


def _acertos_por_semana(diario, semanas):
    grupos = {item["semana"]: {"certos": 0, "erros": 0} for item in semanas}
    for item in diario or []:
        if not isinstance(item, dict):
            continue
        try:
            dia = date.fromisoformat(str(item.get("data") or ""))
        except ValueError:
            continue
        _inicio, _fim, rotulo = _semana_de(dia)
        if rotulo not in grupos:
            continue
        grupos[rotulo]["certos"] += _inteiro(item.get("certos"))
        grupos[rotulo]["erros"] += _inteiro(item.get("erros"))
    saida = []
    for semana in semanas:
        conta = grupos[semana["semana"]]
        saida.append(
            {
                "semana": semana["semana"],
                "inicio": semana["inicio"],
                "fim": semana["fim"],
                "certos": conta["certos"],
                "erros": conta["erros"],
            }
        )
    return saida


def _janela(inicio_atual):
    saida = []
    for indice in range(_SEMANAS - 1, -1, -1):
        segunda = inicio_atual - timedelta(days=7 * indice)
        inicio, fim, rotulo = _semana_de(segunda)
        saida.append(
            {"semana": rotulo, "inicio": inicio.isoformat(), "fim": fim.isoformat()}
        )
    return saida


def _da_semana(linhas, rotulo):
    for item in linhas:
        if item.get("semana") == rotulo:
            return item
    return {"certos": 0, "erros": 0}


def _da_semana_notas(linhas, rotulo):
    for item in linhas:
        if item.get("semana") == rotulo:
            return item
    return {"total": 0, "titulos": []}


def _novo_nome(base, now, tema, root):
    nome = "cartoes-" + _data(now).isoformat()
    if tema:
        from .conhecimento import _slug

        nome += "-" + _slug(tema)
    nome += ".txt"
    alvo = base / nome
    if alvo.exists():
        hora = _data(now).strftime("%H%M%S") if isinstance(now, datetime) else "extra"
        alvo = base / (Path(nome).stem + "-" + hora + ".txt")
    if not _caminho_seguro(alvo, root, base):
        return None
    return alvo


def _absoluto(caminho, root):
    try:
        alvo = _com_extensao_path(Path(caminho))
    except OSError:
        return None
    if alvo.exists() and alvo.is_dir():
        return None
    if not _caminho_seguro(alvo, root, None):
        return None
    return alvo


def _texto_recusado(texto):
    if any(ord(char) < 32 or ord(char) == 127 for char in str(texto or "")):
        return True
    return False


def _nome_recusado(nome):
    if not nome or nome in {".", ".."}:
        return True
    if nome.endswith((" ", ".")):
        return True
    if len(nome) > 180:
        return True
    if _texto_recusado(nome):
        return True
    base = nome.split(".", 1)[0].casefold()
    return base in _RESERVADOS


def _partes_nome(alvo):
    partes = []
    for parte in Path(alvo).parts:
        if parte in {Path(alvo).anchor, Path(alvo).drive}:
            continue
        partes.append(parte)
    return partes


def _caminho_seguro(alvo, root, base):
    """Recusa atalho, nome de dispositivo, saída do vault e saída da pasta base."""
    if _obsidian(alvo):
        return False
    if any(_nome_recusado(parte) for parte in _partes_nome(alvo)):
        return False
    try:
        if alvo.exists() and alvo.is_symlink():
            return False
        resolvido = alvo.resolve()
    except OSError:
        return False
    if _obsidian(resolvido) or not _fora(resolvido, root):
        return False
    if base is None:
        return True
    if not _filho(resolvido, base):
        return False
    cursor = Path(alvo)
    try:
        base_resolvida = Path(base).resolve()
    except OSError:
        return False
    while True:
        try:
            if cursor.exists() and cursor.is_symlink():
                return False
            atual = cursor.resolve()
        except OSError:
            return False
        if atual == base_resolvida:
            break
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return True


def _com_extensao(nome):
    sufixo = Path(nome).suffix.casefold()
    if sufixo in _EXTENSOES:
        return nome
    return nome + ".txt"


def _com_extensao_path(caminho):
    if caminho.suffix.casefold() in _EXTENSOES:
        return caminho
    return caminho.with_name(caminho.name + ".txt")


def _filho(caminho, base):
    try:
        caminho.resolve().relative_to(base.resolve())
    except (OSError, ValueError):
        return False
    return True


def _fora(caminho, root):
    if root is None:
        return True
    try:
        Path(caminho).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return not _obsidian(caminho)
    except OSError:
        return False
    return False


def _obsidian(caminho):
    return any(parte.casefold() == ".obsidian" for parte in Path(caminho).parts)


def _etiquetas(tags):
    from .privacidade import tag_sigilosa

    proibida = fold(tag_sigilosa() or "sigiloso")
    saida = []
    for tag in tags or []:
        token = str(tag or "").strip().lstrip("#")
        token = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in token)
        token = token.strip("_")[:40]
        if not token or fold(token) == proibida or token in saida:
            continue
        saida.append(token)
    return " ".join(saida)


def _campo(texto):
    limpo = str(texto or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")
    limpo = limpo.replace("\u2014", " ").replace("\u2013", " ")
    return " ".join(limpo.split())


def _tema(tema):
    from .reflexao import _recusado

    texto = " ".join(str(tema or "").split())[:80]
    if not texto:
        return ""
    if _recusado(texto):
        return None
    return texto


def _semana_de(dia):
    iso = dia.isocalendar()
    inicio = date.fromisocalendar(iso.year, iso.week, 1)
    fim = date.fromisocalendar(iso.year, iso.week, 7)
    return inicio, fim, f"{iso.year:04d}-W{iso.week:02d}"


def _na_semana(texto, inicio, fim):
    try:
        dia = date.fromisoformat(texto)
    except ValueError:
        return False
    return inicio <= dia <= fim


def _dia_mtime(mtime_ns, zona):
    try:
        bruto = int(mtime_ns) / 1_000_000_000
    except (TypeError, ValueError):
        return None
    if bruto <= 0:
        return None
    try:
        if zona is None:
            return datetime.fromtimestamp(bruto).date()
        return datetime.fromtimestamp(bruto, zona).date()
    except (OverflowError, OSError, ValueError):
        return None


def _hoje(root, now):
    from .review import _today

    if isinstance(now, datetime):
        return _today(root, now)
    if isinstance(now, date):
        return now
    return _today(root, _agora(root))


def _agora(root):
    from .resumo import current_moment

    return current_moment(root)


def _data(now):
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return date.today()


def _inteiro(valor):
    try:
        numero = int(valor or 0)
    except (TypeError, ValueError):
        return 0
    return numero if numero > 0 else 0


def _n(total, um, varios):
    if int(total) == 1:
        return "1 " + um
    return str(int(total)) + " " + varios


def _rotulo_dias(total):
    if total == 1:
        return "1 dia"
    return str(total) + " dias"


def _rotulo_acerto(valor):
    if valor is None:
        return "sem dados"
    return str(int(valor)) + "%"


def _esc(value):
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
