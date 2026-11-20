"""Registro único dos pedidos de voz e de texto.

Cada comando tem nome, exemplos, descrição, tratador e a frase da ajuda.
A classificação percorre a lista na ordem e fica com o primeiro casamento.
"""

import importlib
import re

_ARTIGO = re.compile(r"(?i)^(?:o|a|os|as|um|uma)\s+")
_CAPTURA_VAZIA = re.compile(r"(?i)anota(?:r)?(?:\s+(?:que|isto|isso))?")
_CEREBRO = {"new_chat", "save_last", "dismiss", "chat"}


class Comando:
    def __init__(self, nome, categoria, rotulo, descricao, exemplos, fala, extrair, modulo, funcao):
        self.nome = nome
        self.categoria = categoria
        self.rotulo = rotulo
        self.descricao = descricao
        self.exemplos = tuple(exemplos)
        self.fala = fala
        self.extrair = extrair
        self.modulo = modulo
        self.funcao = funcao


def _novo(text, folded):
    from .routines import _NEW_CHAT

    if folded in _NEW_CHAT:
        return {}
    return None


def _salvar(text, folded):
    from .routines import _SAVE_LAST

    if _SAVE_LAST.fullmatch(folded):
        return {}
    return None


def _dispensar(text, folded):
    from .routines import DISMISS_RE

    if DISMISS_RE.match(text):
        return {}
    return None


def _feito(text, folded):
    from .routines import DONE_RE

    done = DONE_RE.match(text)
    if not done:
        return None
    return {"text": done.group("body").strip(" \t.?!")}


_VIDEO_RE = re.compile(
    r"(?i)^(?:salva|salve|salvar|guarda|guarde|guardar)\s+"
    r"(?:esse|este|o)\s+v[ií]deo(?:\s+(?P<url>\S+))?\s*$"
)
_ARTIGO_RE = re.compile(
    r"(?i)^(?:salva|salve|salvar|guarda|guarde|guardar)\s+"
    r"(?:esse|este|o)\s+artigo(?:\s+(?P<url>\S+))?\s*$"
)
_PODCAST_RE = re.compile(
    r"(?i)^(?:salva|salve|salvar|guarda|guarde|guardar)\s+"
    r"(?:esse|este|o)\s+podcast(?:\s+(?P<body>.+))?\s*$"
)
_RASCUNHOS_RE = re.compile(r"(?i)^revisa(?:r)?\s+(?:os\s+)?rascunhos?\s*$")
_ACEITA_RE = re.compile(
    r"(?i)^(?:aceita|aceitar|aceite)(?:\s+(?:o|a|esse|este))?\s+"
    r"rascunho(?:\s+(?P<num>\d{1,3}))?\s*$"
)
_DESCARTA_RE = re.compile(
    r"(?i)^(?:descarta|descartar|descarte)(?:\s+(?:o|a|esse|este))?\s+"
    r"rascunho(?:\s+(?P<num>\d{1,3}))?\s*$"
)
_EDITA_RE = re.compile(
    r"(?i)^(?:edita|editar|edite)(?:\s+(?:o|a|esse|este))?\s+"
    r"rascunho\s+(?P<body>.+)$"
)


def _video(text, folded):
    del folded
    match = _VIDEO_RE.match(text)
    if not match:
        return None
    return {"text": (match.group("url") or "").strip()}


def _artigo(text, folded):
    del folded
    match = _ARTIGO_RE.match(text)
    if not match:
        return None
    return {"text": (match.group("url") or "").strip()}


def _podcast(text, folded):
    del folded
    match = _PODCAST_RE.match(text)
    if not match:
        return None
    return {"text": (match.group("body") or "").strip()}


_ESTUDO_VIDEO_RE = re.compile(
    r"(?i)^(?:resume|resumir|resuma)\s+(?:esse|este|o)\s+v[ií]deo(?:\s+(?P<url>\S+))?\s*$"
)
_ESTUDO_AUDIO_RE = re.compile(
    r"(?i)^(?:resume|resumir|resuma)\s+(?:esse|este|o)\s+[aá]udio(?:\s+(?P<body>.+))?\s*$"
)
_FILA_MIDIA_RE = re.compile(
    r"(?i)^(?:processa|processe|processar)\s+(?:a\s+)?(?:minha\s+)?fila\s+de\s+m[ií]dia\s*$"
)


def _estudo_video(text, folded):
    del folded
    match = _ESTUDO_VIDEO_RE.match(text)
    if not match:
        return None
    return {"text": (match.group("url") or "").strip()}


def _estudo_audio(text, folded):
    del folded
    match = _ESTUDO_AUDIO_RE.match(text)
    if not match:
        return None
    return {"text": (match.group("body") or "").strip()}


def _fila_midia(text, folded):
    del folded
    if _FILA_MIDIA_RE.match(text):
        return {}
    return None


def _rascunhos(text, folded):
    del folded
    if _RASCUNHOS_RE.match(text):
        return {}
    return None


def _aceita_rascunho(text, folded):
    del folded
    match = _ACEITA_RE.match(text)
    if not match:
        return None
    return {"query": (match.group("num") or "").strip()}


def _descarta_rascunho(text, folded):
    del folded
    match = _DESCARTA_RE.match(text)
    if not match:
        return None
    return {"query": (match.group("num") or "").strip()}


def _edita_rascunho(text, folded):
    del folded
    match = _EDITA_RE.match(text)
    if not match:
        return None
    return {"text": match.group("body").strip()}


def _anotar(text, folded):
    from .routines import CAPTURE_RE, _SAVE_LAST, _split_capture

    if _SAVE_LAST.fullmatch(folded):
        return None
    if _CAPTURA_VAZIA.fullmatch(text):
        return {"text": ""}
    capture = CAPTURE_RE.match(text)
    if not capture:
        return None
    body, place, where = _split_capture(capture.group("body").strip())
    return {"text": body, "query": where, "place": place}


def _perfil(text, folded):
    from .routines import PROFILE_RE

    profile = PROFILE_RE.match(text)
    if not profile:
        return None
    return {"text": profile.group("body").strip(" \t.?!")}


def _adiar(text, folded):
    from .routines import SNOOZE_RE

    snooze = SNOOZE_RE.match(text)
    if not snooze:
        return None
    return {"text": (snooze.group("body") or "").strip(" \t.?!")}


def _cancelar(text, folded):
    from .routines import CANCEL_RE

    cancel = CANCEL_RE.match(text)
    if not cancel:
        return None
    return {"text": (cancel.group("body") or "").strip(" \t.?!")}


def _lembrar(text, folded):
    from .routines import RECURRING_HEAD_RE, RECURRING_TAIL_RE, REMINDER_RE

    if (
        RECURRING_HEAD_RE.match(text)
        or RECURRING_TAIL_RE.match(text)
        or REMINDER_RE.match(text)
    ):
        return {"text": text}
    return None


_NOTAS_DIZEM = re.compile(
    r"(?i)^o que (?:as|minhas) notas dizem sobre\s+(?P<query>.+?)\s*$"
)


def _notas_dizem(text, folded):
    del folded
    match = _NOTAS_DIZEM.match(text or "")
    if not match:
        return None
    query = match.group("query").strip(" \t.!?")
    if len(query) < 2:
        return None
    return {"query": query}


def _buscar(text, folded):
    from .routines import SEARCH_RE

    found = SEARCH_RE.match(text)
    if not found:
        return None
    query = _ARTIGO.sub("", found.group("query").strip()).strip()
    return {"query": query}


def _briefing(text, folded):
    from .routines import BRIEFING_RE

    if BRIEFING_RE.match(text):
        return {}
    return None


def _agenda(text, folded):
    from .routines import AGENDA_RE, BRIEFING_RE, fold

    if BRIEFING_RE.match(text):
        return None
    agenda = AGENDA_RE.match(text)
    if not agenda:
        return None
    day = agenda.group("day") or agenda.group("day_agenda") or agenda.group("day2") or "hoje"
    return {"query": fold(day)}


def _semana(text, folded):
    from .routines import WEEK_RE

    if WEEK_RE.match(text):
        return {}
    return None


def _dia(text, folded):
    from .routines import DAY_CLOSE_RE

    if DAY_CLOSE_RE.match(text):
        return {}
    return None


def _readwise(text, folded):
    from .routines import READWISE_RE

    if READWISE_RE.match(folded):
        return {}
    return None


def _destaques(text, folded):
    from .routines import DESTAQUES_RE

    achado = DESTAQUES_RE.match(folded)
    if not achado:
        return None
    return {"query": (achado.group("fonte") or "").strip()}


def _aprendi(text, folded):
    from .routines import LEARNED_RE

    if LEARNED_RE.match(folded):
        return {}
    return None


def _persona(text, folded):
    from .routines import PERSONA_RE

    if PERSONA_RE.match(folded):
        return {}
    return None


def _fontes(text, folded):
    from .routines import SOURCES_RE

    if SOURCES_RE.match(folded):
        return {}
    return None


def _sobre_mim(text, folded):
    from .routines import ABOUT_RE

    if ABOUT_RE.match(folded):
        return {}
    return None


def _esquecer(text, folded):
    from .routines import FORGET_RE

    forgotten = FORGET_RE.match(text)
    if not forgotten:
        return None
    return {"text": (forgotten.group("body") or "").strip(" \t.?!")}


def _historico(text, folded):
    from .routines import HISTORY_RE

    history = HISTORY_RE.match(folded)
    if not history:
        return None
    return {"query": history.group(1) or "ontem"}


def _foco(text, folded):
    from .routines import FOCUS_RE

    if FOCUS_RE.match(folded):
        return {}
    return None


def _ajuda(text, folded):
    from .routines import HELP_RE

    if HELP_RE.match(folded):
        return {}
    return None


def _jira(text, folded):
    from .routines import JIRA_RE

    if JIRA_RE.match(folded):
        return {}
    return None


def _github(text, folded):
    from .routines import GITHUB_RE

    if GITHUB_RE.match(folded):
        return {}
    return None


def _email(text, folded):
    from .routines import MAIL_RE

    if MAIL_RE.match(folded):
        return {}
    return None


def _resumo_recados(text, folded):
    from .routines import INBOX_SUMMARY_RE

    if INBOX_SUMMARY_RE.match(folded):
        return {}
    return None


def _recados(text, folded):
    from .routines import INBOX_RE

    if INBOX_RE.match(folded):
        return {}
    return None


def _pedido(text, folded):
    from .routines import OUTBOX_RE

    outbox = OUTBOX_RE.match(text)
    if not outbox:
        return None
    return {
        "text": outbox.group("body").strip(" \t.?!"),
        "query": outbox.group("name").strip(),
    }


def _estudo(text, folded):
    from .routines import STUDY_RE

    study = STUDY_RE.match(text)
    if not study:
        return None
    return {"query": (study.group("query") or "").strip(" \t.!?")}


def _relacionadas(text, folded):
    from .routines import RELATED_RE

    related = RELATED_RE.match(text)
    if not related:
        return None
    return {"query": related.group("query").strip(" \t.!?")}


def _revisao(text, folded):
    from .routines import REVIEW_DAY_RE

    if REVIEW_DAY_RE.match(folded):
        return {}
    return None


def _livro(text, folded):
    from .routines import REVIEW_BOOK_RE

    book = REVIEW_BOOK_RE.match(folded)
    if not book:
        return None
    return {"query": (book.group(1) or "").strip(" .")}


def _pausa_revisao(text, folded):
    from .routines import REVIEW_PAUSE_RE

    if REVIEW_PAUSE_RE.match(folded):
        return {}
    return None


def _retoma_revisao(text, folded):
    from .routines import REVIEW_RESUME_RE

    if REVIEW_RESUME_RE.match(folded):
        return {}
    return None


def _nota_revisao(text, folded):
    from .routines import REVIEW_GRADE_RE

    grade = REVIEW_GRADE_RE.match(folded)
    if not grade:
        return None
    return {"query": grade.group(1)}


_REMOTO_OFF_RE = re.compile(
    r"(?i)^(?:desliga|desligar|desligue|encerra|encerrar|sai|sair)"
    r"(?:\s+(?:o|do))?\s+(?:telegram|remoto)"
    r"(?:\s+(?:hoje|por hoje|ate amanha|até amanhã))?\s*$"
)


def _remoto_off(text, folded):
    del folded
    if _REMOTO_OFF_RE.match(text or ""):
        return {}
    return None


def _silencio_hoje(text, folded):
    from .routines import MUTE_TODAY_RE

    if MUTE_TODAY_RE.match(folded):
        return {}
    return None


def _silencio_sempre(text, folded):
    from .routines import MUTE_ALWAYS_RE

    if MUTE_ALWAYS_RE.match(folded):
        return {}
    return None


def _pausa_alertas(text, folded):
    from .routines import PAUSE_ALERTS_RE

    if PAUSE_ALERTS_RE.match(folded):
        return {}
    return None


def _privado_on(text, folded):
    from .routines import MODO_PRIVADO_ON

    if folded in MODO_PRIVADO_ON:
        return {}
    return None


def _privado_off(text, folded):
    from .routines import MODO_PRIVADO_OFF

    if folded in MODO_PRIVADO_OFF:
        return {}
    return None


def _conversa(text, folded):
    if folded.rstrip("?").strip() == "o que tenho no laboratorio":
        return {"text": text}
    return None


_PRIMEIRO_RE = re.compile(r"(?i)^primeiro uso\s*$")
_VERSAO_RE = re.compile(
    r"^(?:"
    r"qual(?: e| eh)? (?:a |o )?sua versao|"
    r"qual(?: e| eh)? a versao|"
    r"que versao voce (?:e|tem|usa)|"
    r"versao do jarvis"
    r")$"
)
_ATUALIZAR_RE = re.compile(
    r"^(?:"
    r"se atualiza(?: agora)?|"
    r"se atualize(?: agora)?|"
    r"atualiza(?:-se| se)|"
    r"atualize(?:-se| se)|"
    r"pode se atualizar"
    r")$"
)


def _primeiro_uso(text, folded):
    del folded
    if _PRIMEIRO_RE.match(text or ""):
        return {}
    return None


def _versao(text, folded):
    del text
    if _VERSAO_RE.match(folded or ""):
        return {}
    return None


def _atualizar(text, folded):
    del text
    if _ATUALIZAR_RE.match(folded or ""):
        return {}
    return None


_CONECTA_RE = re.compile(
    r"(?i)^conecta(?:r)?\s+(?:as\s+)?ideias(?:\s+(?:sobre|de)\s+(?P<tema>.+))?$"
)
_LEMBRETE_NOTA_RE = re.compile(
    r"(?i)^(?:me\s+)?lembra(?:r)?\s+(?:de\s+)?(?:algo|alguma\s+coisa)$"
)
_APRENDER_RE = re.compile(r"(?i)^(?:eu\s+)?quero\s+aprender\s+(?P<tema>.+)$")
_PROGRESSO_RE = re.compile(
    r"(?i)^como\s+(?:eu\s+)?estou\s+(?:em|no|na|com|sobre)\s+(?P<tema>.+)$"
)


def _conecta(text, folded):
    del folded
    match = _CONECTA_RE.match(text or "")
    if not match:
        return None
    return {"query": (match.group("tema") or "").strip(" \t.!?")}


def _lembrete_nota(text, folded):
    del folded
    if _LEMBRETE_NOTA_RE.match(text or ""):
        return {}
    return None


def _aprender(text, folded):
    del folded
    match = _APRENDER_RE.match(text or "")
    if not match:
        return None
    return {"query": match.group("tema").strip(" \t.!?")}


def _progresso_tema(text, folded):
    del folded
    match = _PROGRESSO_RE.match(text or "")
    if not match:
        return None
    return {"query": match.group("tema").strip(" \t.!?")}


_FEYNMAN_RE = re.compile(
    r"(?i)^(?:me\s+deixa|deixa\s+eu)\s+explicar(?:\s+(?P<tema>.+))?$"
)
_SOCRATICO_RE = re.compile(
    r"(?i)^(?:me\s+)?(?:pergunta|pergunte)\s+sobre(?:\s+(?P<tema>.+))?$"
)
_LIVRO_TEMA_RE = re.compile(r"(?i)^(?:o\s+|a\s+)?livr")
_SEMANA_RE = re.compile(r"^(?:faz |abre |vamos fazer )?(?:a )?revisao semanal$")


def _feynman(text, folded):
    del folded
    match = _FEYNMAN_RE.match(text or "")
    if not match:
        return None
    return {"query": (match.group("tema") or "").strip(" \t.!?")}


def _socratico(text, folded):
    del folded
    match = _SOCRATICO_RE.match(text or "")
    if not match:
        return None
    tema = (match.group("tema") or "").strip(" \t.!?")
    if tema and _LIVRO_TEMA_RE.match(tema):
        return None
    return {"query": tema}


def _revisao_semanal(text, folded):
    del text
    if _SEMANA_RE.match(folded or ""):
        return {}
    return None


_ESTUDEI_RE = re.compile(
    r"^(?:o\s+)?quanto(?:\s+eu)?\s+estudei(?:\s+(?:nesta|nessa|esta|essa)\s+semana)$"
)
_SEQUENCIA_RE = re.compile(r"^qual(?:\s+(?:e|eh))?\s+(?:a\s+)?minha\s+sequencia$")
_EXPORTA_RE = re.compile(
    r"^(?:exporta|exporte|exportar)\s+(?:os\s+meus|meus|os)\s+cartoes"
    r"(?:\s+(?:de|do|da|sobre)\s+(?P<tema>.+))?$"
)


def _estudei(text, folded):
    del text
    if _ESTUDEI_RE.match(folded or ""):
        return {}
    return None


_SESSAO_RE = re.compile(
    r"^(?:comeca|comece|iniciar|inicia)(?: uma)? sessao de estudo"
    r"(?: de (?P<min>\d{1,3}) minutos?)?"
    r"(?: sobre (?P<tema>.+))?$"
)
_FALTA_RE = re.compile(r"^quanto falta$")
_PAUSA_SESSAO_RE = re.compile(r"^(?:pausa|pausar)(?: a sessao)?$")
_CONTINUA_SESSAO_RE = re.compile(r"^(?:continua|continuar|retoma|retomar) a sessao$")
_ENCERRA_SESSAO_RE = re.compile(r"^encerr(?:a|ar) a sessao$")


def _sessao_iniciar(text, folded):
    del text
    match = _SESSAO_RE.match(folded or "")
    if not match:
        return None
    return {
        "text": (match.group("min") or "").strip(),
        "query": (match.group("tema") or "").strip(" \t.!?"),
    }


def _sessao_falta(text, folded):
    del text
    if _FALTA_RE.match(folded or ""):
        return {}
    return None


def _sessao_pausa(text, folded):
    del text
    if _PAUSA_SESSAO_RE.match(folded or ""):
        return {}
    return None


def _sessao_continua(text, folded):
    del text
    if _CONTINUA_SESSAO_RE.match(folded or ""):
        return {}
    return None


def _sessao_encerrar(text, folded):
    del text
    if _ENCERRA_SESSAO_RE.match(folded or ""):
        return {}
    return None


def _sequencia(text, folded):
    del text
    if _SEQUENCIA_RE.match(folded or ""):
        return {}
    return None


def _exportar_cartoes(text, folded):
    del text
    match = _EXPORTA_RE.match(folded or "")
    if not match:
        return None
    return {"query": (match.group("tema") or "").strip(" \t.!?")}


COMANDOS = (
    Comando(
        "new_chat",
        "Conversa",
        "nova conversa",
        "Apaga o contexto da conversa atual e encerra modo ou confirmação.",
        ("nova conversa", "limpar a conversa", "começar de novo"),
        "Nova conversa apaga o contexto e encerra o modo em andamento.",
        _novo,
        "jarvis.brain",
        "_dispatch",
    ),
    Comando(
        "save_last",
        "Notas",
        "salvar resposta",
        "Guarda a última resposta numa nota.",
        ("salva isso", "anota isso", "guarda isto"),
        "Salva isso guarda a última resposta.",
        _salvar,
        "jarvis.brain",
        "_dispatch",
    ),
    Comando(
        "dismiss",
        "Conversa",
        "encerrar",
        "Encerra o assunto. cancela ou para interrompe explicação, teste ou confirmação.",
        ("Valeu, Jarvis",),
        "Valeu, Jarvis encerra. cancela ou para interrompe o modo em andamento.",
        _dispensar,
        "jarvis.brain",
        "_dispatch",
    ),
    Comando(
        "done",
        "Agenda",
        "feito",
        "Marca uma tarefa da agenda como feita.",
        ("marca como feito pagar a conta de luz",),
        "Marca como feito conclui a tarefa.",
        _feito,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "capture",
        "Notas",
        "anotação",
        "Anota um fato no diário ou numa pasta do vault.",
        ("anota que comprar pão", "Anota na pasta IA que a revisao ficou para sexta"),
        "Anota que grava um fato.",
        _anotar,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "capture_video",
        "Notas",
        "vídeo",
        "Busca a transcrição de um vídeo do YouTube, com o pacote opcional youtube-transcript-api, em português e depois em inglês, e grava resumo, pontos e cartões em rascunho.",
        ("salva esse vídeo https://www.youtube.com/watch?v=Abcdefghijk",),
        "Salva esse vídeo grava a transcrição resumida.",
        _video,
        "jarvis.midia",
        "capturar_turno",
    ),
    Comando(
        "capture_article",
        "Notas",
        "artigo",
        "Busca o texto de um artigo, com o pacote opcional trafilatura, e grava resumo, pontos e cartões em rascunho.",
        ("salva esse artigo https://exemplo.test/nota",),
        "Salva esse artigo grava o texto resumido.",
        _artigo,
        "jarvis.midia",
        "capturar_turno",
    ),
    Comando(
        "capture_podcast",
        "Notas",
        "podcast",
        "Grava o resumo de um episódio a partir de um endereço ou de um arquivo de transcrição.",
        ("salva esse podcast https://exemplo.test/episodio.txt",),
        "Salva esse podcast grava a transcrição que você indicar.",
        _podcast,
        "jarvis.midia",
        "capturar_turno",
    ),
    Comando(
        "study_video",
        "Notas",
        "nota de estudo de vídeo",
        "Busca a transcrição de um vídeo do YouTube, em português e depois em inglês, e grava uma nota de estudo com resumo, ideias com tempo, citações e perguntas. Uma nota por vídeo.",
        ("resume esse vídeo https://www.youtube.com/watch?v=Abcdefghijk",),
        "Resume esse vídeo grava uma nota de estudo com o tempo de cada ideia.",
        _estudo_video,
        "jarvis.estudo_midia",
        "turno_video",
    ),
    Comando(
        "study_audio",
        "Notas",
        "nota de estudo de áudio",
        "Transcreve um áudio local com o Whisper desta máquina, em trechos, e grava a mesma nota de estudo. O áudio não sai da máquina.",
        ("resume esse áudio episodio-sintetico.mp3",),
        "Resume esse áudio transcreve o arquivo nesta máquina e grava a nota.",
        _estudo_audio,
        "jarvis.estudo_midia",
        "turno_audio",
    ),
    Comando(
        "media_queue",
        "Notas",
        "fila de mídia",
        "Processa áudios e links.txt da pasta de entrada, com confirmação, e grava uma nota de estudo por item.",
        ("processa minha fila de mídia",),
        "Processa minha fila de mídia pede confirmação antes de gravar as notas.",
        _fila_midia,
        "jarvis.estudo_midia",
        "turno_fila",
    ),
    Comando(
        "profile",
        "Memória",
        "perfil",
        "Guarda um fato estável sobre você.",
        ("lembra que eu gosto de café sem açúcar",),
        "Lembra que eu guarda um fato.",
        _perfil,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "snooze",
        "Agenda",
        "adiar lembrete",
        "Adia um lembrete já gravado.",
        ("adia o lembrete de pagar o boleto para amanhã às 10",),
        "Adia o lembrete muda a hora.",
        _adiar,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "cancel",
        "Agenda",
        "cancelar lembrete",
        "Cancela um lembrete.",
        ("cancela o lembrete de pagar o boleto",),
        "Cancela o lembrete apaga o aviso.",
        _cancelar,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "reminder",
        "Agenda",
        "lembrete",
        "Cria um lembrete com dia, hora ou repetição.",
        ("Me lembra de pagar o boleto amanha as 9",),
        "Diga me lembra para criar um aviso.",
        _lembrar,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "search",
        "Notas",
        "busca",
        "Procura nas notas, nos livros, nos vídeos e nos cursos.",
        ("o que eu escrevi sobre o farol?",),
        "Busca o que anotei sobre, nos livros, nos vídeos e nos cursos.",
        _buscar,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "notes_say",
        "Notas",
        "o que as notas dizem",
        "Responde o que as notas cobrem sobre uma pergunta, só com trechos recuperados, e cita o título.",
        ("o que minhas notas dizem sobre o farol?",),
        "O que minhas notas dizem sobre um tema responde só com o que está nas notas.",
        _notas_dizem,
        "jarvis.significado",
        "responder",
    ),
    Comando(
        "briefing",
        "Agenda",
        "bom dia",
        "Resume o dia: agenda, lembretes e tarefas.",
        ("bom dia", "o que tenho para hoje", "resumo do dia"),
        "Diga bom dia ou o que tenho para hoje para abrir o resumo do dia.",
        _briefing,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "agenda",
        "Agenda",
        "agenda",
        "Lista a agenda de hoje, de amanhã ou de depois de amanhã.",
        ("o que tenho hoje", "o que tenho amanhã?"),
        "O que tenho hoje e o que tenho amanhã leem a agenda.",
        _agenda,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "week",
        "Agenda",
        "semana",
        "Resume a semana que passou.",
        ("como foi minha semana?",),
        "Como foi minha semana fecha a semana.",
        _semana,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "day",
        "Agenda",
        "fim do dia",
        "Resume o dia e oferece gravar.",
        ("como foi meu dia", "resumo do fim do dia"),
        "Como foi meu dia fecha o dia.",
        _dia,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "readwise",
        "Estudo",
        "importar destaques",
        "Importa destaques do Readwise para o vault.",
        ("importa meus destaques",),
        "Pede importa meus destaques e traz o Readwise.",
        _readwise,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "destaques",
        "Estudo",
        "importar leituras",
        "Importa destaques do Kindle, de PDF ou do KOReader para uma nota por livro. Pede confirmação e não repete destaque.",
        ("importa destaques do kindle", "importa destaques"),
        "Pede importa destaques e traz Kindle, PDF ou KOReader da pasta de entrada, com confirmação.",
        _destaques,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "learned",
        "Estudo",
        "aprendizado",
        "Conta o que entrou nas notas nesta semana.",
        ("o que aprendi esta semana?", "o que aprendi"),
        "Diga o que aprendi esta semana para listar o estudo.",
        _aprendi,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "persona",
        "Memória",
        "persona",
        "Lê a nota da persona, sem mandar o texto para a nuvem.",
        ("Mostra sua persona.",),
        "Diga mostra sua persona para ler a nota local.",
        _persona,
        "jarvis.persona",
        "persona_speech",
    ),
    Comando(
        "sources",
        "Memória",
        "fontes",
        "Lista as fontes declaradas na persona.",
        ("Quais fontes tenho?",),
        "Diga quais fontes tenho para listar a persona.",
        _fontes,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "about",
        "Memória",
        "memória",
        "Diz o que está guardado sobre você.",
        ("o que você sabe sobre mim?",),
        "Diga o que você sabe sobre mim para ler a memória local.",
        _sobre_mim,
        "jarvis.memoria",
        "about_speech",
    ),
    Comando(
        "forget",
        "Memória",
        "esquecer",
        "Apaga um fato da memória, com confirmação.",
        ("Esquece que eu gosto de café",),
        "Diga esquece para apagar um fato, com confirmação.",
        _esquecer,
        "jarvis.memoria",
        "prepare_forget",
    ),
    Comando(
        "history",
        "Conversa",
        "histórico",
        "Repete o que você pediu hoje, ontem ou anteontem.",
        ("o que eu te pedi ontem?",),
        "O que eu te pedi ontem lê o histórico local.",
        _historico,
        "jarvis.journal",
        "history_speech",
    ),
    Comando(
        "focus",
        "Agenda",
        "foco",
        "Diz as prioridades do dia.",
        ("quais minhas prioridades hoje?",),
        "Quais minhas prioridades hoje traz o foco.",
        _foco,
        "jarvis.routines",
        "focus_speech",
    ),
    Comando(
        "help",
        "Conversa",
        "ajuda",
        "Lista estes pedidos.",
        ("ajuda", "o que você sabe"),
        "Ajuda lista os pedidos.",
        _ajuda,
        "jarvis.comandos",
        "texto_ajuda",
    ),
    Comando(
        "jira",
        "Integrações",
        "jira",
        "Lê issues do Jira. Não altera nada.",
        ("o que tenho no Jira?",),
        "O que tenho no Jira só lê.",
        _jira,
        "jarvis.external",
        "handle",
    ),
    Comando(
        "github",
        "Integrações",
        "pull requests",
        "Lê pull requests. Não comenta nem faz merge.",
        ("como estão meus PRs?",),
        "Como estão meus PRs só lê.",
        _github,
        "jarvis.external",
        "handle",
    ),
    Comando(
        "mail",
        "Integrações",
        "e-mail",
        "Lê e-mail importante. O Jarvis não envia e-mail.",
        ("tenho e-mail importante?",),
        "Tenho e-mail importante só lê a caixa.",
        _email,
        "jarvis.external",
        "handle",
    ),
    Comando(
        "inbox_summary",
        "Assistentes",
        "resumo dos recados",
        "Resume os recados dos outros assistentes.",
        ("resume os recados",),
        "Resume os recados junta a caixa.",
        _resumo_recados,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "inbox",
        "Assistentes",
        "recados",
        "Lê o que os assistentes mandaram.",
        ("o que os assistentes mandaram?",),
        "O que os assistentes mandaram lê a caixa.",
        _recados,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "outbox",
        "Assistentes",
        "pedido a outro assistente",
        "Deixa um pedido para outro assistente.",
        ("pede pro Codex revisar o PR",),
        "Pede pro Codex deixa um pedido.",
        _pedido,
        "jarvis.routines",
        "run_routine",
    ),
    Comando(
        "study",
        "Estudo",
        "teste",
        "Me testa sobre um tema dos livros, vídeos ou cursos.",
        ("Me testa sobre a fita nos livros.", "me testa"),
        "Diga me testa sobre um tema para um teste curto.",
        _estudo,
        "jarvis.estudo",
        "study_turn",
    ),
    Comando(
        "related",
        "Estudo",
        "notas relacionadas",
        "Lista notas ligadas a um tema, com título e caminho.",
        ("Notas relacionadas ao farol.",),
        "Diga notas relacionadas a uma nota para listar títulos e caminhos.",
        _relacionadas,
        "jarvis.relacionadas",
        "related_speech",
    ),
    Comando(
        "connect",
        "Estudo",
        "conectar ideias",
        "Acha notas de fontes diferentes sobre o mesmo assunto e sugere um mapa. Gravar ou ligar pede confirmação.",
        ("conecta ideias", "conecta ideias sobre farol"),
        "Conecta ideias sugere um mapa com títulos de fontes diferentes. Gravar pede confirmação.",
        _conecta,
        "jarvis.conhecimento",
        "propor_conexoes",
    ),
    Comando(
        "resurface",
        "Estudo",
        "lembrar uma nota",
        "Traz o título de uma nota antiga e um ponto que você escreveu. Nota privada fica de fora.",
        ("me lembra algo",),
        "Me lembra algo traz um título antigo e um ponto que você escreveu.",
        _lembrete_nota,
        "jarvis.conhecimento",
        "fala_lembrete",
    ),
    Comando(
        "learn",
        "Estudo",
        "quero aprender",
        "Guarda uma meta, mostra o que o vault já tem e sugere um plano da semana.",
        ("quero aprender farol",),
        "Quero aprender guarda uma meta e monta um plano com o que já está no vault.",
        _aprender,
        "jarvis.conhecimento",
        "preparar_meta",
    ),
    Comando(
        "progress",
        "Estudo",
        "progresso do tema",
        "Conta a revisão espaçada dos cartões ligados a um tema.",
        ("como estou em farol?",),
        "Como estou em um tema conta a revisão dos cartões ligados a ele.",
        _progresso_tema,
        "jarvis.conhecimento",
        "falar_progresso",
    ),
    Comando(
        "week_stats",
        "Estudo",
        "estudo da semana",
        "Conta a revisão, as sessões de estudo, o acerto e as notas públicas desta semana.",
        ("quanto estudei essa semana?",),
        "Quanto estudei essa semana conta a revisão, as sessões e as notas públicas.",
        _estudei,
        "jarvis.andamento",
        "falar_semana",
    ),
    Comando(
        "sessao_iniciar",
        "Estudo",
        "sessão de estudo",
        "Começa uma sessão de estudo, no estilo Pomodoro, com pausa configurável. O padrão é 25 minutos.",
        ("começa uma sessão de estudo de 25 minutos sobre farol",),
        "Começa uma sessão de estudo anuncia o tempo e fica quieto até o fim.",
        _sessao_iniciar,
        "jarvis.sessao",
        "turno",
    ),
    Comando(
        "sessao_falta",
        "Estudo",
        "tempo da sessão",
        "Diz quanto falta da sessão de estudo ou da pausa.",
        ("quanto falta?",),
        "Quanto falta diz o tempo que resta da sessão.",
        _sessao_falta,
        "jarvis.sessao",
        "turno",
    ),
    Comando(
        "sessao_pausa",
        "Estudo",
        "pausa da sessão",
        "Pausa a sessão de estudo. A palavra para, sozinha, encerra o modo.",
        ("pausa",),
        "Pausa interrompe a sessão de estudo sem encerrar.",
        _sessao_pausa,
        "jarvis.sessao",
        "turno",
    ),
    Comando(
        "sessao_continua",
        "Estudo",
        "retomada da sessão",
        "Retoma a sessão de estudo que estava pausada.",
        ("continua a sessão",),
        "Continua a sessão retoma o tempo pausado.",
        _sessao_continua,
        "jarvis.sessao",
        "turno",
    ),
    Comando(
        "sessao_encerrar",
        "Estudo",
        "fim da sessão",
        "Encerra a sessão, avisa e pergunta o que você aprendeu. cancela ou para só encerra.",
        ("encerra a sessão",),
        "Encerra a sessão pergunta o que você aprendeu e grava depois do sim.",
        _sessao_encerrar,
        "jarvis.sessao",
        "turno",
    ),
    Comando(
        "streak",
        "Estudo",
        "sequência",
        "Diz há quantos dias seguidos houve revisão ou sessão de estudo.",
        ("qual minha sequência?",),
        "Qual minha sequência diz os dias seguidos de revisão ou de sessão de estudo.",
        _sequencia,
        "jarvis.andamento",
        "falar_sequencia",
    ),
    Comando(
        "anki",
        "Estudo",
        "exportar cartões",
        "Pede confirmação e grava os cartões públicos num texto para o Anki, fora do vault.",
        ("exporta meus cartões", "exporta meus cartões de farol"),
        "Exporta meus cartões pede confirmação e grava o arquivo fora do vault.",
        _exportar_cartoes,
        "jarvis.andamento",
        "preparar_anki",
    ),
    Comando(
        "feynman",
        "Estudo",
        "explicar",
        "Pede uma explicação com palavras simples, compara com as notas e oferece cartões em rascunho para as lacunas.",
        ("me deixa explicar farol",),
        "Me deixa explicar compara a explicação com as notas e pode criar rascunho.",
        _feynman,
        "jarvis.reflexao",
        "turno",
    ),
    Comando(
        "socratic",
        "Estudo",
        "perguntas",
        "Faz perguntas de por que e de como, uma por vez, a partir das notas.",
        ("me pergunta sobre farol",),
        "Me pergunta sobre um tema faz perguntas uma por vez.",
        _socratico,
        "jarvis.reflexao",
        "turno",
    ),
    Comando(
        "weekly",
        "Estudo",
        "revisão semanal",
        "Conduz a revisão semanal e, depois da confirmação, grava a nota da semana.",
        ("revisão semanal",),
        "Revisão semanal faz quatro perguntas e grava a nota depois da confirmação.",
        _revisao_semanal,
        "jarvis.reflexao",
        "turno",
    ),
    Comando(
        "review",
        "Estudo",
        "revisão",
        "Abre a revisão do dia, no formato pergunta e resposta.",
        ("revisão do dia",),
        "A revisão do dia lê os cartões.",
        _revisao,
        "jarvis.review",
        "review_turn",
    ),
    Comando(
        "review_book",
        "Estudo",
        "revisão de livro",
        "Limita a revisão a um livro.",
        ("me pergunta sobre o livro foguete",),
        "Me pergunta sobre o livro limita a revisão.",
        _livro,
        "jarvis.review",
        "review_turn",
    ),
    Comando(
        "review_pause",
        "Estudo",
        "pausa da revisão",
        "Interrompe a revisão.",
        ("pausa a revisão",),
        "Pausa a revisão interrompe.",
        _pausa_revisao,
        "jarvis.review",
        "review_turn",
    ),
    Comando(
        "review_resume",
        "Estudo",
        "retomada da revisão",
        "Continua a revisão pausada.",
        ("retoma a revisão",),
        "Retoma a revisão continua os cartões.",
        _retoma_revisao,
        "jarvis.review",
        "review_turn",
    ),
    Comando(
        "review_grade",
        "Estudo",
        "acerto da revisão",
        "Registra acerto ou erro do cartão. Difícil, bom e fácil também entram na revisão.",
        ("acertei", "eu errei", "dificil", "bom", "facil"),
        "Diga acertei ou errei para marcar o cartão. Difícil, bom e fácil também valem.",
        _nota_revisao,
        "jarvis.review",
        "review_turn",
    ),
    Comando(
        "draft_list",
        "Estudo",
        "rascunhos",
        "Lista os cartões em rascunho criados por uma captura, antes da revisão espaçada.",
        ("revisa rascunhos",),
        "Revisa rascunhos lista os cartões ainda não aceitos.",
        _rascunhos,
        "jarvis.rascunhos",
        "draft_turn",
    ),
    Comando(
        "draft_accept",
        "Estudo",
        "aceitar rascunho",
        "Aceita um cartão em rascunho para ele entrar na revisão espaçada.",
        ("aceita o rascunho",),
        "Aceita o rascunho libera o cartão para a revisão.",
        _aceita_rascunho,
        "jarvis.rascunhos",
        "draft_turn",
    ),
    Comando(
        "draft_discard",
        "Estudo",
        "descartar rascunho",
        "Apaga um cartão em rascunho.",
        ("descarta o rascunho",),
        "Descarta o rascunho apaga o cartão.",
        _descarta_rascunho,
        "jarvis.rascunhos",
        "draft_turn",
    ),
    Comando(
        "draft_edit",
        "Estudo",
        "editar rascunho",
        "Troca a pergunta e a resposta de um cartão em rascunho.",
        ("edita o rascunho Qual a cor da fita? ::: azul",),
        "Edita o rascunho troca a pergunta e a resposta.",
        _edita_rascunho,
        "jarvis.rascunhos",
        "draft_turn",
    ),
    Comando(
        "mute_today",
        "Avisos",
        "silenciar hoje",
        "Calar o último aviso até o fim do dia.",
        ("silencia esse aviso hoje",),
        "Silencia esse aviso hoje vale até o fim do dia.",
        _silencio_hoje,
        "jarvis.alerts",
        "silence",
    ),
    Comando(
        "mute_always",
        "Avisos",
        "silenciar sempre",
        "Calar esse tipo de aviso nas próximas vezes.",
        ("silencia sempre",),
        "Silencia sempre vale nas próximas vezes.",
        _silencio_sempre,
        "jarvis.alerts",
        "silence",
    ),
    Comando(
        "pause_alerts",
        "Avisos",
        "pausar alertas",
        "Adia os avisos até amanhã.",
        ("pausa os alertas até amanhã",),
        "Pausa os alertas até amanhã adia os avisos.",
        _pausa_alertas,
        "jarvis.alerts",
        "pause_alerts",
    ),
    Comando(
        "private_on",
        "Privacidade",
        "modo privado",
        "Desliga a nuvem, o Telegram e o log nesta sessão.",
        ("modo privado", "ativa o modo privado"),
        "Modo privado desliga a nuvem, o Telegram e o log.",
        _privado_on,
        "jarvis.privacidade",
        "entrar_modo_privado",
    ),
    Comando(
        "private_off",
        "Privacidade",
        "fim do modo privado",
        "Volta a usar a nuvem, o Telegram e o log.",
        ("sai do modo privado",),
        "Sai do modo privado liga de novo.",
        _privado_off,
        "jarvis.privacidade",
        "sair_modo_privado",
    ),
    Comando(
        "remote_off",
        "Telegram",
        "desligar o remoto",
        "Desliga o Telegram até o fim do dia. No celular, /sair faz o mesmo.",
        ("desliga o telegram hoje",),
        "Desliga o telegram hoje pausa o remoto até amanhã.",
        _remoto_off,
        "jarvis.remoto",
        "desligar_hoje",
    ),
    Comando(
        "primeiro_uso",
        "Conversa",
        "primeiro uso",
        "Explica como apontar o vault na primeira vez.",
        ("primeiro uso",),
        "Diga primeiro uso para ver como apontar o vault.",
        _primeiro_uso,
        "jarvis.primeiro_uso",
        "fala_atalho",
    ),
    Comando(
        "chat",
        "Conversa",
        "conversa",
        "Pergunta livre, respondida pelo cérebro.",
        ("o que tenho no laboratorio?",),
        "O que tenho no laboratorio vai para a conversa.",
        _conversa,
        "jarvis.brain",
        "_dispatch",
    ),
    Comando(
        "version",
        "Manutenção",
        "versão",
        "Diz a versão desta instalação.",
        ("qual sua versão?", "qual a sua versão?"),
        "Qual sua versão diz o número desta instalação.",
        _versao,
        "jarvis.__version__",
        "fala",
    ),
    Comando(
        "atualizar",
        "Manutenção",
        "atualizar",
        "Pede confirmação e atualiza só o código do Jarvis. O vault fica de fora.",
        ("se atualiza", "se atualize"),
        "Se atualiza pede confirmação antes de puxar o código. O vault fica de fora.",
        _atualizar,
        "jarvis.atualizar",
        "perguntar",
    ),
)


def por_nome(nome):
    for comando in COMANDOS:
        if comando.nome == nome:
            return comando
    return None


def rotulo(nome):
    comando = por_nome(nome)
    if comando is None:
        return nome
    return comando.rotulo


def resolver(comando):
    if comando.nome in _CEREBRO:
        from .brain import Brain

        return Brain._dispatch
    module = importlib.import_module(comando.modulo)
    return getattr(module, comando.funcao)


def classificar(message):
    from .routines import Intent, fold, normalize_phrase

    text = normalize_phrase(message)
    if not text:
        return Intent("chat")
    folded = fold(text)
    for comando in COMANDOS:
        dados = comando.extrair(text, folded)
        if dados is not None:
            return Intent(comando.nome, **dados)
    return Intent("chat", text=text)


def casamentos(message):
    from .routines import fold, normalize_phrase

    text = normalize_phrase(message)
    if not text:
        return []
    folded = fold(text)
    return [comando.nome for comando in COMANDOS if comando.extrair(text, folded) is not None]


def texto_ajuda(has_vault=True):
    partes = ["Eu resolvo estes pedidos sem o Claude, senhor."]
    categoria = None
    blocos = []
    for comando in COMANDOS:
        if comando.categoria != categoria:
            if blocos:
                partes.append(" ".join(blocos))
            categoria = comando.categoria
            blocos = [categoria + ": " + comando.fala]
        else:
            blocos.append(comando.fala)
    if blocos:
        partes.append(" ".join(blocos))
    partes.append(
        "Durante a fala, uma tecla ou a palavra de ativação interrompe e volta a ouvir. "
        "E sobre isso continua o assunto anterior."
    )
    speech = " ".join(partes)
    if not has_vault:
        speech += " Notas, agenda e lembretes pedem o vault. Rode python -m jarvis.setup."
    return speech


def texto_chat():
    return (
        "Digite a mensagem e pressione Enter. "
        "/sair encerra. /ajuda mostra este texto. "
        + texto_ajuda(True)
    )


def render_comandos():
    linhas = []
    categorias = []
    for comando in COMANDOS:
        if comando.categoria not in categorias:
            categorias.append(comando.categoria)
    for categoria in categorias:
        linhas.append("")
        linhas.append("### " + categoria)
        linhas.append("")
        for comando in COMANDOS:
            if comando.categoria != categoria:
                continue
            exemplo = comando.exemplos[0]
            linhas.append("- " + comando.descricao + " Exemplo: `" + exemplo + "`.")
    return "\n".join(linhas).strip() + "\n"
