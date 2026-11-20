"""Sessão de estudo com pausa, recap e registro local.

O arquivo em ~/.jarvis guarda tema, duração e horários. Não guarda
o que você aprendeu nem texto de nota. A nota só muda depois do sim,
na fila única de escrita. Nota com #sigiloso, inclusive com BOM ou
quebra do Windows, e pasta privada não são alteradas.
"""

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config
from .log import LOG
from .modos import FALA_PRAZO, expirado
from .routines import NO_WORDS, YES_WORDS, fold, normalize_phrase

_ZONA = ZoneInfo("America/Sao_Paulo")
_LIMITE_HISTORICO = 400
_FASES_ATIVAS = {"estudo", "pausa", "intervalo"}
_COMANDOS = {"sessao_falta", "sessao_pausa", "sessao_continua", "sessao_encerrar"}
_RUIM = re.compile(
    r"(?i)(git\s+push|enviar\s+e-?mail|envie\s+um\s+e-?mail|sendmessage|"
    r"ignore\s+as\s+instru|dado-nao-confiavel|</?dado)"
)
_ENVIO = None


def registrar_envio(funcao):
    """Guarda quem manda o aviso curto no Telegram. O texto da nota não entra."""
    global _ENVIO
    _ENVIO = funcao


def como_dado(texto):
    """O que você aprendeu entra no cérebro só como dado, nunca como pedido."""
    from .privacidade import embrulhar, pedido_limpo

    limpo = _sanear(pedido_limpo(texto or ""))
    return embrulhar("aprendizado", limpo)


def adiar_proativo(now=None):
    """True enquanto a sessão corre e o silêncio está ligado."""
    if not config.sessao_silencio():
        return False
    estado = _carregar()
    if not estado:
        return False
    return estado.get("fase") in _FASES_ATIVAS


def tem_sessao():
    return _carregar() is not None


def resumo(now):
    """Minutos por dia, semana, tema e meta. Sem texto de nota."""
    momento = _momento(now)
    dia = momento.date()
    inicio, fim = _semana(dia)
    hoje = 0
    semana = 0
    por_tema = {}
    por_dia = {}
    for item in _historico():
        quando = _dia_item(item)
        minutos = _minutos_de(item.get("segundos"))
        if quando is None or minutos <= 0:
            continue
        if quando == dia:
            hoje += minutos
        if inicio <= quando <= fim:
            semana += minutos
            tema = item.get("tema") or ""
            por_tema[tema] = por_tema.get(tema, 0) + minutos
            chave = quando.isoformat()
            por_dia[chave] = por_dia.get(chave, 0) + minutos
    temas = [
        {"tema": tema, "minutos": minutos}
        for tema, minutos in sorted(por_tema.items(), key=lambda par: (-par[1], par[0]))
    ]
    dias = [{"dia": chave, "minutos": por_dia[chave]} for chave in sorted(por_dia)]
    return {
        "minutos_hoje": hoje,
        "minutos_semana": semana,
        "temas": temas,
        "por_dia": dias,
    }


def dias_com_estudo():
    """Datas com sessão contada, para a sequência. Sem texto de nota."""
    achados = set()
    for item in _historico():
        quando = _dia_item(item)
        if quando is None or _minutos_de(item.get("segundos")) <= 0:
            continue
        achados.add(quando.isoformat())
    return sorted(achados)


def minutos_da_meta(tema, now):
    total = 0
    for item in resumo(now)["temas"]:
        if _casa(item.get("tema") or "", tema):
            total += int(item.get("minutos") or 0)
    return total


def concluir_vencidas(now):
    """Fecha o que já venceu. Devolve falas e o modo seguinte. Não repete."""
    momento = _momento(now)
    with _trava_estado():
        estado = _ler_estado()
        if not estado:
            return []
        avisos, novo = _avancar(estado, momento)
        if novo is None:
            _apagar_estado()
        else:
            _salvar_estado(novo)
    for aviso in avisos:
        _efeitos(aviso)
    return avisos


def cancelar_modo(now):
    """cancela e para encerram. Não perguntam o que você aprendeu."""
    momento = _momento(now)
    with _trava_estado():
        estado = _ler_estado()
        if not estado:
            return "Não há sessão de estudo em andamento, senhor."
        if estado.get("fase") in {"estudo", "pausa"} and not estado.get("registrada"):
            _registrar(estado, momento, antecipada=True)
        _apagar_estado()
    LOG.info("sessao de estudo encerrada pelo pedido")
    return "Encerrei a sessão de estudo, senhor."


def abandonar(now):
    """nova conversa encerra a sessão sem uma frase extra."""
    momento = _momento(now)
    with _trava_estado():
        estado = _ler_estado()
        if not estado:
            return
        if estado.get("fase") in {"estudo", "pausa"} and not estado.get("registrada"):
            _registrar(estado, momento, antecipada=True)
        _apagar_estado()
    LOG.info("sessao de estudo encerrada com a conversa")


def descartar_recap():
    """O prazo do modo acabou. A frase seguinte não vira resposta."""
    with _trava_estado():
        estado = _ler_estado()
        if not estado:
            return
        if estado.get("fase") == "intervalo":
            estado["esperando"] = ""
            _salvar_estado(estado)
            return
        _apagar_estado()
    LOG.info("recap da sessao encerrado pelo prazo")


def turno(root, intent, message, now, pending):
    momento = _momento(now)
    kind = getattr(intent, "kind", "") or ""
    if _modo_alheio(pending) and kind not in _COMANDOS and kind != "sessao_iniciar":
        _ceder_recap(kind)
        return None
    avisos = concluir_vencidas(momento)
    if avisos:
        return ("reply", _juntar(avisos), _pending_de(avisos))
    estado = _carregar()
    if kind == "sessao_iniciar":
        return _iniciar(intent, momento, estado)
    if estado is None:
        if kind in _COMANDOS:
            return ("reply", "Não há sessão de estudo em andamento, senhor.", pending)
        return None
    _ceder_recap(kind)
    estado = _carregar() or estado
    if _recap_venceu(estado, momento):
        descartar_recap()
        return ("reply", FALA_PRAZO, None)
    if kind == "sessao_falta":
        return _com_pending(("reply", _fala_falta(estado, momento), _modo(estado)), pending)
    if kind == "sessao_pausa":
        return _com_pending(_pausar(estado, momento), pending)
    if kind == "sessao_continua":
        return _com_pending(_continuar(estado, momento), pending)
    if kind == "sessao_encerrar":
        return _encerrar(estado, momento)
    if estado.get("esperando") in {"aprender", "confirmar"} and kind == "chat":
        return _ouvir(estado, message, pending)
    if estado.get("fase") in {"estudo", "pausa"} and kind == "chat":
        return ("reply", _FALA_QUIETO, _modo(estado))
    return None


def _modo_alheio(pending):
    """Outro modo de vários turnos está com a palavra. A sessão não toma a frase."""
    if not isinstance(pending, dict):
        return False
    ativo = str(pending.get("kind") or "")
    return bool(ativo) and ativo != "sessao"


def _ceder_recap(kind):
    """Um modo novo encerra a pergunta do recap. O histórico de minutos fica."""
    from .modos import modo_de

    novo = modo_de(kind)
    if not novo or novo == "sessao":
        return
    with _trava_estado():
        estado = _ler_estado()
        if not estado or not estado.get("esperando"):
            return
        estado["esperando"] = ""
        estado.pop("texto", None)
        _salvar_estado(estado)


def _com_pending(resposta, pending):
    if not _modo_alheio(pending) or not isinstance(resposta, tuple) or len(resposta) < 3:
        return resposta
    if resposta[0] != "reply":
        return resposta
    return (resposta[0], resposta[1], pending)


def gravar_aprendizado(root, payload, now):
    """Anexa o recap confirmado. O registro local não recebe esse texto."""
    momento = _momento(now)
    dados = payload if isinstance(payload, dict) else {}
    tema = _tema(dados.get("tema") or "")
    texto = _texto_aprendido(dados.get("texto") or "")
    if not tema or not texto:
        _soltar_espera()
        return "Não gravei, senhor. A frase não serve."
    if root is None:
        _soltar_espera()
        return (
            "O vault não está configurado, senhor. Sem ele eu não gravo a nota. "
            "Rode python -m jarvis.setup."
        )
    destino = dados.get("destino") if dados.get("destino") in {"meta", "diario"} else "meta"
    minutos = int(dados.get("minutos") or 0)
    try:
        fala = _anexar_nota(root, tema, texto, destino, minutos, momento)
    except Exception:
        LOG.info("nota da sessao nao gravada")
        _soltar_espera()
        return "Não gravei a nota da sessão, senhor."
    _soltar_espera()
    return fala


_FALA_QUIETO = (
    "Estou na sessão de estudo, senhor. "
    "Diga quanto falta, pausa ou encerra a sessão."
)


def _iniciar(intent, now, estado):
    if estado is not None:
        return (
            "reply",
            "Já há uma sessão sobre " + (estado.get("tema") or "o tema") + ", senhor. "
            "Diga encerra a sessão para fechar.",
            _modo(estado),
        )
    bruto = str(getattr(intent, "text", "") or "").strip()
    if bruto:
        try:
            minutos = int(bruto)
        except ValueError:
            minutos = 0
        if minutos < 1 or minutos > 180:
            return (
                "reply",
                "A sessão fica entre 1 e 180 minutos, senhor.",
                None,
            )
    else:
        minutos = int(config.sessao_minutos())
    tema = _tema(getattr(intent, "query", "") or "")
    if not tema:
        return ("reply", "Sobre o que é a sessão, senhor?", None)
    pausa = int(config.sessao_pausa())
    destino = config.sessao_nota()
    fim = now + timedelta(minutes=minutos)
    novo = {
        "versao": 1,
        "fase": "estudo",
        "tema": tema,
        "planejado": minutos * 60,
        "pausa_segundos": pausa * 60,
        "inicio": _iso(now),
        "inicio_trecho": _iso(now),
        "fim": _iso(fim),
        "estudado": 0,
        "esperando": "",
        "destino": destino,
        "registrada": False,
        "minutos": 0,
        "encerrada": "",
        "perguntado": "",
    }
    with _trava_estado():
        _salvar_estado(novo)
    LOG.info("sessao de estudo iniciada: %s min", minutos)
    unidade = "minuto" if minutos == 1 else "minutos"
    fala = "Comecei uma sessão de " + str(minutos) + " " + unidade + " sobre " + tema + ", senhor."
    if pausa > 0:
        fala += " A pausa será de " + _rotulo_minutos(pausa) + "."
    fala += " Durante a sessão eu fico quieto. Diga quanto falta, pausa ou encerra a sessão."
    return ("reply", fala, _modo(novo))


def _pausar(estado, now):
    fase = estado.get("fase")
    if fase == "pausa":
        return (
            "reply",
            "A sessão já está pausada, senhor. Diga continua a sessão para retomar.",
            _modo(estado),
        )
    if fase != "estudo":
        return (
            "reply",
            "A pausa já está valendo, senhor. Diga quanto falta.",
            _modo(estado),
        )
    with _trava_estado():
        atual = _ler_estado() or estado
        if atual.get("fase") != "estudo":
            return (
                "reply",
                "A pausa já está valendo, senhor. Diga quanto falta.",
                _modo(atual),
            )
        atual["estudado"] = _ativos(atual, now)
        atual["fase"] = "pausa"
        atual["pausada_em"] = _iso(now)
        _salvar_estado(atual)
    LOG.info("sessao de estudo pausada")
    return (
        "reply",
        "Pausei a sessão, senhor. " + _fala_falta(atual, now),
        _modo(atual),
    )


def _continuar(estado, now):
    if estado.get("fase") != "pausa":
        if estado.get("fase") == "intervalo":
            fala = "A pausa ainda está valendo, senhor. " + _fala_falta(estado, now)
        else:
            fala = "A sessão já está em andamento, senhor. " + _fala_falta(estado, now)
        return ("reply", fala, _modo(estado))
    with _trava_estado():
        atual = _ler_estado() or estado
        if atual.get("fase") != "pausa":
            return (
                "reply",
                "A sessão já está em andamento, senhor. " + _fala_falta(atual, now),
                _modo(atual),
            )
        restante = max(1, int(atual.get("planejado") or 0) - int(atual.get("estudado") or 0))
        atual["fase"] = "estudo"
        atual["inicio_trecho"] = _iso(now)
        atual["fim"] = _iso(now + timedelta(seconds=restante))
        atual.pop("pausada_em", None)
        _salvar_estado(atual)
    LOG.info("sessao de estudo retomada")
    return ("reply", "Retomei a sessão, senhor. " + _fala_falta(atual, now), _modo(atual))


def _encerrar(estado, now):
    if estado.get("fase") not in {"estudo", "pausa"}:
        return (
            "reply",
            "A sessão já encerrou, senhor. O que você aprendeu?",
            _modo(estado),
        )
    with _trava_estado():
        atual = _ler_estado() or estado
        if atual.get("fase") in {"estudo", "pausa"} and not atual.get("registrada"):
            _registrar(atual, now, antecipada=True)
        avisos, novo = _abrir_recap(atual, now)
        if novo is None:
            _apagar_estado()
        else:
            _salvar_estado(novo)
    for aviso in avisos:
        _efeitos(aviso)
    LOG.info("sessao de estudo encerrada")
    if not avisos:
        return ("reply", "Encerrei a sessão, senhor.", None)
    return ("reply", _juntar(avisos), _pending_de(avisos))


def _ouvir(estado, message, pending):
    fase_espera = estado.get("esperando") or ""
    guardado = pending if isinstance(pending, dict) else {}
    if fase_espera == "confirmar" or guardado.get("phase") == "confirmar":
        if _texto_aprendido(guardado.get("texto") or ""):
            return _confirmar(message, guardado, estado)
        return _recap_sem_frase(message, estado)
    texto = _texto_aprendido(message)
    if not texto:
        return (
            "reply",
            "Não guardei essa frase, senhor. Ela tem cara de pedido ou de segredo.",
            _modo(estado),
        )
    if len(texto) < 8 or len(texto.split()) < 2:
        return (
            "reply",
            "Conte com um pouco mais de detalhe, senhor. O que você aprendeu?",
            _modo(estado),
        )
    novo = _modo(estado, "confirmar")
    novo["texto"] = texto
    with _trava_estado():
        atual = _ler_estado() or estado
        atual["esperando"] = "confirmar"
        _salvar_estado(atual)
    if (atual.get("destino") or estado.get("destino")) == "diario":
        onde = "na nota do dia"
    else:
        onde = "na nota de " + (estado.get("tema") or "o tema")
    return (
        "reply",
        "Posso gravar isso " + onde + ", senhor? Diga sim para gravar ou não para deixar.",
        novo,
    )


def _recap_sem_frase(message, estado):
    """O sim ficou sem a frase, em geral porque o processo reiniciou."""
    texto = fold(normalize_phrase(message or ""))
    if texto in NO_WORDS:
        _soltar_espera()
        return ("reply", "Tudo bem, senhor. Não gravei.", None)
    with _trava_estado():
        atual = _ler_estado() or dict(estado)
        atual["esperando"] = "aprender"
        atual.pop("texto", None)
        _salvar_estado(atual)
    if texto in YES_WORDS:
        return (
            "reply",
            "A frase se perdeu quando o Jarvis reiniciou, senhor. O que você aprendeu?",
            _modo(atual, "aprender"),
        )
    return _ouvir(atual, message, None)


def _confirmar(message, pending, estado):
    texto = fold(normalize_phrase(message or ""))
    if texto in NO_WORDS:
        _soltar_espera()
        return ("reply", "Tudo bem, senhor. Não gravei.", None)
    if texto in YES_WORDS:
        corpo = _texto_aprendido((pending or {}).get("texto") or "")
        if not corpo:
            _soltar_espera()
            return ("reply", "Não gravei, senhor. A frase não serve.", None)
        return (
            "write",
            {
                "tema": estado.get("tema") or "",
                "texto": corpo,
                "destino": estado.get("destino") or "meta",
                "minutos": int(estado.get("minutos") or 0),
            },
        )
    return (
        "reply",
        "Diga sim para gravar ou não para deixar, senhor.",
        pending if pending.get("phase") == "confirmar" else _modo(estado, "confirmar"),
    )


def _avancar(estado, now):
    fase = estado.get("fase")
    if fase in {"estudo", "pausa"} and _estudo_venceu(estado, now):
        if not estado.get("registrada"):
            _registrar(estado, now, antecipada=False)
        return _abrir_recap(estado, now)
    if fase == "intervalo" and _instante_passou(estado.get("fim"), now):
        aviso = _aviso_pausa()
        if estado.get("esperando"):
            estado["fase"] = "recap"
            if not estado.get("perguntado"):
                estado["perguntado"] = _iso(now)
            return [aviso], estado
        return [aviso], None
    return [], estado


def _abrir_recap(estado, now):
    pausa = int(estado.get("pausa_segundos") or 0)
    encerrada = _instante(estado.get("encerrada")) or now
    if estado.get("fase") == "estudo" and not _estudo_antecipado(estado, now):
        previsto = _instante(estado.get("fim"))
        if previsto is not None:
            encerrada = previsto
    estado["encerrada"] = _iso(encerrada)
    if "registrado" in estado:
        estado["minutos"] = _minutos_de(estado.get("registrado"))
    else:
        estado["minutos"] = _minutos_de(estado.get("planejado"))
    estado["esperando"] = "aprender"
    estado["perguntado"] = _iso(now)
    if pausa > 0:
        fim_pausa = encerrada + timedelta(seconds=pausa)
        if now >= fim_pausa:
            estado["fase"] = "recap"
        else:
            estado["fase"] = "intervalo"
            estado["fim"] = _iso(fim_pausa)
    else:
        estado["fase"] = "recap"
    aviso = _aviso_fim(estado)
    aviso["pending"] = _modo(estado)
    if estado.get("fase") == "recap" and pausa > 0 and now >= encerrada + timedelta(seconds=pausa):
        pausa_aviso = _aviso_pausa()
        pausa_aviso["pending"] = _modo(estado)
        return [aviso, pausa_aviso], estado
    return [aviso], estado


def _estudo_venceu(estado, now):
    if estado.get("fase") == "pausa":
        return False
    return _instante_passou(estado.get("fim"), now)


def _estudo_antecipado(estado, now):
    fim = _instante(estado.get("fim"))
    if fim is None:
        return True
    return now < fim


def _registrar(estado, now, antecipada):
    if antecipada:
        segundos = _ativos(estado, now)
        fim = now
    else:
        segundos = int(estado.get("planejado") or 0)
        fim = _instante(estado.get("fim")) or now
    segundos = max(0, min(int(segundos), int(estado.get("planejado") or segundos or 0)))
    estado["registrada"] = True
    estado["registrado"] = segundos
    if segundos < 1:
        return
    inicio = estado.get("inicio") or _iso(now)
    item = {
        "tema": estado.get("tema") or "",
        "inicio": inicio,
        "fim": _iso(fim),
        "segundos": segundos,
    }
    _anexar_historico(item)
    LOG.info("sessao de estudo registrada: %s s", segundos)


def _anexar_nota(root, tema, texto, destino, minutos, now):
    from .guardas import FALA_BLOQUEIO, GuardError, caminho_bloqueado, caminho_dentro, escrever
    from .leitura import ler_texto
    from .privacidade import nota_sigilosa
    from .trava import fila_escrita

    caminho, relativa = _destino(root, tema, destino, now)
    if caminho is None or not relativa:
        return "Não gravei, senhor. O destino ficou fora do vault."
    if caminho_bloqueado(caminho) or not caminho_dentro(root, caminho):
        return "Não gravei, senhor. O destino ficou fora do vault."
    if nota_sigilosa(root, relativa, ""):
        LOG.info("nota da sessao recusada: sigilo")
        return "Não gravei, senhor. A nota é sigilosa."
    linhas = _linhas(now, minutos, tema, texto)
    try:
        with fila_escrita():
            if caminho.is_file():
                try:
                    atual = ler_texto(caminho)
                except (OSError, UnicodeError):
                    LOG.info("nota da sessao ilegivel")
                    return "Não gravei, senhor. Não consegui ler a nota."
            else:
                atual = ""
            if nota_sigilosa(root, relativa, atual):
                LOG.info("nota da sessao recusada: sigilo")
                return "Não gravei, senhor. A nota é sigilosa."
            nl = "\r\n" if "\r\n" in (atual or "") else "\n"
            novo = _juntar_nota(atual, linhas, nl, tema)
            escrever(caminho, novo, checar=nl.join(linhas), raiz=root)
    except GuardError:
        return FALA_BLOQUEIO
    LOG.info("nota da sessao gravada")
    if destino == "diario":
        onde = "na nota do dia"
    else:
        onde = "na nota de " + tema
    return "Gravei " + onde + ", senhor. Diga revisa rascunhos para ver o cartão."


def _destino(root, tema, destino, now):
    from pathlib import Path

    from .conhecimento import _slug
    from .paths import caminho_relativo
    from .routines import daily_note_path, load_places

    if destino == "diario":
        caminho = daily_note_path(root, load_places(root), now.date())
        try:
            relativa = Path(caminho).resolve().relative_to(Path(root).resolve()).as_posix()
        except (OSError, ValueError):
            return None, ""
        if not caminho_relativo(relativa, exigir_md=True):
            return None, ""
        return Path(root) / relativa, relativa
    slug = _slug(tema)
    meta = config.metas_pasta().strip("/") + "/" + slug + ".md"
    segura = caminho_relativo(meta, exigir_md=True)
    if segura and (Path(root) / segura).is_file():
        return Path(root) / segura, segura
    pasta = config.sessao_pasta().strip("/") + "/" + slug + ".md"
    segura = caminho_relativo(pasta, exigir_md=True)
    if not segura:
        return None, ""
    return Path(root) / segura, segura


def _linhas(now, minutos, tema, texto):
    marca = now.strftime("%Y-%m-%d %H:%M")
    duracao = _rotulo_minutos(minutos) if minutos > 0 else "menos de um minuto"
    aprendizado = texto.replace(":::", " : ")
    return [
        "- " + marca + ", " + duracao + ": " + aprendizado,
        "- [rascunho] O que você aprendeu sobre " + tema + "? ::: " + aprendizado,
    ]


def _juntar_nota(atual, linhas, nl, tema):
    corpo = atual or ""
    if not corpo.strip():
        corpo = "# " + tema + nl + nl
    elif not corpo.endswith(("\n", "\r")):
        corpo += nl
    if "## Estudo" not in corpo:
        if not corpo.endswith(nl):
            corpo += nl
        corpo += "## Estudo" + nl + nl
    for linha in linhas:
        if linha not in corpo:
            corpo += linha + nl
    if corpo.startswith("\ufeff"):
        return corpo
    return corpo


def _soltar_espera():
    with _trava_estado():
        estado = _ler_estado()
        if not estado:
            return
        if estado.get("fase") == "intervalo":
            estado["esperando"] = ""
            _salvar_estado(estado)
            return
        _apagar_estado()


def _fala_falta(estado, now):
    fase = estado.get("fase")
    if fase == "pausa":
        restante = max(0, int(estado.get("planejado") or 0) - int(estado.get("estudado") or 0))
        return (
            "A sessão está pausada, senhor. Faltam "
            + _rotulo_segundos(restante)
            + ". Diga continua a sessão para retomar."
        )
    if fase == "intervalo":
        return "Faltam " + _rotulo_restante(estado.get("fim"), now) + " de pausa, senhor."
    if fase == "recap" or estado.get("esperando"):
        return "A sessão já encerrou, senhor. O que você aprendeu?"
    return "Faltam " + _rotulo_restante(estado.get("fim"), now) + ", senhor."


def _aviso_fim(estado):
    tema = estado.get("tema") or "o tema"
    minutos = int(estado.get("minutos") or 0)
    if minutos <= 0:
        minutos = _minutos_de(estado.get("registrado") or estado.get("planejado"))
    pausa = int(estado.get("pausa_segundos") or 0) // 60
    unidade = "minuto" if minutos == 1 else "minutos"
    voz = "Sessão de " + str(minutos) + " " + unidade + " sobre " + tema + " encerrada, senhor."
    if pausa > 0:
        voz += " Pausa de " + _rotulo_minutos(pausa) + "."
    voz += " O que você aprendeu?"
    curto = str(minutos) + " " + unidade + " sobre " + tema + "."
    return {
        "voz": voz,
        "bandeja": {"titulo": "Sessão encerrada", "corpo": curto},
        "telegram": "Sessão de estudo encerrada, senhor. " + curto,
        "pending": _modo(estado),
    }


def _aviso_pausa():
    return {
        "voz": "A pausa acabou, senhor.",
        "bandeja": {"titulo": "Pausa encerrada", "corpo": "A pausa da sessão acabou."},
        "telegram": "",
        "pending": None,
    }


def _efeitos(aviso):
    bandeja = aviso.get("bandeja") or {}
    if bandeja.get("titulo"):
        from .bandeja import avisar

        avisar(bandeja.get("titulo") or "", bandeja.get("corpo") or "")
    telegram = aviso.get("telegram") or ""
    if telegram:
        _ping(telegram)


def _ping(texto):
    from .privacidade import modo_privado_ativo

    if not texto or not config.sessao_telegram() or modo_privado_ativo():
        return
    envio = _ENVIO
    if envio is None:
        return
    try:
        envio(texto)
    except Exception:
        LOG.info("aviso de sessao no telegram falhou")


def _modo(estado, phase=None):
    if phase:
        escolhida = phase
    elif estado.get("esperando") == "confirmar":
        escolhida = "confirmar"
    elif estado.get("esperando") == "aprender" and estado.get("fase") != "intervalo":
        escolhida = "aprender"
    else:
        escolhida = estado.get("fase") or "estudo"
    if escolhida not in {"estudo", "pausa", "intervalo", "aprender", "confirmar", "recap"}:
        escolhida = "estudo"
    if escolhida == "recap":
        escolhida = "aprender"
    return {"kind": "sessao", "phase": escolhida, "tema": estado.get("tema") or ""}


def _pending_de(avisos):
    achado = None
    for item in avisos:
        if item.get("pending"):
            achado = item["pending"]
    return achado


def _recap_venceu(estado, now):
    esperando = estado.get("esperando")
    if esperando not in {"aprender", "confirmar"}:
        return False
    if estado.get("fase") == "intervalo" and esperando != "confirmar":
        return False
    return expirado(estado.get("perguntado"), now, config.modo_prazo())


def _ativos(estado, now):
    base = int(estado.get("estudado") or 0)
    if estado.get("fase") == "estudo":
        inicio = _instante(estado.get("inicio_trecho"))
        if inicio is not None:
            base += max(0, int((now - inicio).total_seconds()))
    planejado = int(estado.get("planejado") or 0)
    if planejado > 0:
        return min(base, planejado)
    return max(0, base)


def _juntar(avisos):
    return " ".join(item.get("voz") or "" for item in avisos if item.get("voz")).strip()


def _anexar_historico(item):
    from .trava import gravar_atomico, trava_arquivo

    path = _caminho_historico()
    path.parent.mkdir(parents=True, exist_ok=True)
    with trava_arquivo(path.with_name(path.name + ".lock"), mensagem="sessao ocupada"):
        atual = _ler_json(path)
        linhas = atual.get("sessoes") if isinstance(atual.get("sessoes"), list) else []
        linhas = [linha for linha in linhas if _item_valido(linha)]
        linhas.append(item)
        if len(linhas) > _LIMITE_HISTORICO:
            linhas = linhas[-_LIMITE_HISTORICO:]
        bruto = json.dumps({"versao": 1, "sessoes": linhas}, ensure_ascii=False, indent=2)
        gravar_atomico(path, bruto + "\n", mode=0o600)


def _historico():
    dados = _ler_json(_caminho_historico())
    linhas = dados.get("sessoes") if isinstance(dados.get("sessoes"), list) else []
    return [linha for linha in linhas if _item_valido(linha)]


def _item_valido(item):
    if not isinstance(item, dict):
        return False
    if not _tema(item.get("tema") or ""):
        return False
    if _instante(item.get("inicio")) is None or _instante(item.get("fim")) is None:
        return False
    try:
        segundos = int(item.get("segundos"))
    except (TypeError, ValueError):
        return False
    return segundos >= 0


def _carregar():
    with _trava_estado():
        return _ler_estado()


def _ler_estado():
    dados = _ler_json(_caminho_estado())
    if not dados or dados.get("versao") != 1:
        return None
    if dados.get("fase") not in {"estudo", "pausa", "intervalo", "recap"}:
        return None
    if not dados.get("tema"):
        return None
    return dados


def _salvar_estado(estado):
    from .trava import gravar_atomico

    path = _caminho_estado()
    path.parent.mkdir(parents=True, exist_ok=True)
    bruto = json.dumps(estado, ensure_ascii=False, indent=2)
    gravar_atomico(path, bruto + "\n", mode=0o600)


def _apagar_estado():
    path = _caminho_estado()
    try:
        path.unlink()
    except OSError:
        return


def _trava_estado():
    from .trava import trava_arquivo

    path = _caminho_estado()
    path.parent.mkdir(parents=True, exist_ok=True)
    return trava_arquivo(path.with_name(path.name + ".lock"), mensagem="sessao ocupada")


def _caminho_estado():
    return config.jarvis_home() / "sessao-estudo.json"


def _caminho_historico():
    return config.jarvis_home() / "sessoes.json"


def _ler_json(path):
    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _tema(tema):
    from .privacidade import pedido_limpo

    limpo = " ".join(pedido_limpo(str(tema or "")).replace("\u2014", " ").replace("\u2013", " ").split())
    limpo = limpo[:80].strip(" \t.!?")
    if len(limpo) < 2 or _RUIM.search(limpo):
        return ""
    if any(char in limpo for char in "\\/"):
        return ""
    from .guardas import texto_secreto

    if texto_secreto(limpo):
        return ""
    return limpo


def _texto_aprendido(texto):
    from .privacidade import pedido_limpo

    bruto = pedido_limpo(str(texto or ""))
    bruto = bruto.replace("\u2014", " ").replace("\u2013", " ")
    bruto = " ".join(bruto.split())
    if _RUIM.search(bruto):
        return ""
    from .guardas import texto_secreto

    if texto_secreto(bruto):
        return ""
    return bruto[:400].strip()


def _sanear(texto):
    return " ".join(str(texto or "").replace("\u2014", " ").replace("\u2013", " ").split())[:400]


def _casa(tema, meta):
    esquerda = fold(tema)
    direita = fold(meta)
    if not esquerda or not direita:
        return False
    if esquerda == direita:
        return True
    tokens_tema = [token for token in esquerda.split() if len(token) >= 3]
    tokens_meta = [token for token in direita.split() if len(token) >= 3]
    if not tokens_tema or not tokens_meta:
        return False
    return all(token in tokens_tema for token in tokens_meta) or all(
        token in tokens_meta for token in tokens_tema
    )


def _minutos_de(segundos):
    try:
        total = int(segundos)
    except (TypeError, ValueError):
        return 0
    if total <= 0:
        return 0
    return (total + 30) // 60


def _dia_item(item):
    momento = _instante(item.get("fim"))
    if momento is None:
        return None
    return momento.date()


def _semana(dia):
    iso = dia.isocalendar()
    from datetime import date

    inicio = date.fromisocalendar(iso.year, iso.week, 1)
    fim = date.fromisocalendar(iso.year, iso.week, 7)
    return inicio, fim


def _rotulo_minutos(minutos):
    total = int(minutos)
    if total == 1:
        return "1 minuto"
    return str(total) + " minutos"


def _rotulo_segundos(segundos):
    total = max(0, int(segundos))
    minutos, resto = divmod(total, 60)
    if minutos <= 0:
        return "menos de um minuto"
    if resto >= 30:
        minutos += 1
    return _rotulo_minutos(minutos)


def _rotulo_restante(fim, now):
    alvo = _instante(fim)
    if alvo is None:
        return "menos de um minuto"
    return _rotulo_segundos(int((alvo - now).total_seconds()))


def _instante_passou(texto, now):
    alvo = _instante(texto)
    if alvo is None:
        return False
    return now >= alvo


def _instante(texto):
    bruto = str(texto or "").strip()
    if not bruto:
        return None
    try:
        momento = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=_ZONA)
    return momento


def _momento(now):
    if now is None:
        return datetime.now(_ZONA)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=_ZONA)
        return now
    return datetime.now(_ZONA)


def _iso(momento):
    return _momento(momento).isoformat(timespec="seconds")
