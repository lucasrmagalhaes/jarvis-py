"""Rotinas do dia a dia sobre o clone do vault.

Pastas e nomes saem do AGENTS.md, do CLAUDE.md e do README.md do clone.
Este módulo não guarda cópia dessas convenções.
"""

import calendar
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from .busca import fold as _fold
from .external import github_briefing, jira_briefing, mail_briefing
from .guardas import FALA_BLOQUEIO, GuardError, caminho_bloqueado

DEFAULT_TIMEZONE = "America/Sao_Paulo"
SKIP_DIRS = {".git", ".obsidian", "node_modules", ".trash"}
ROOT_NAMES = {"agents.md", "claude.md", "readme.md"}
MAX_NOTE_CHARS = 80000
MAX_WALK = 50000

WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

DAY_RE = (
    r"hoje|amanh[ãa]|depois de amanh[ãa]|"
    r"segunda(?:-feira)?|ter[cç]a(?:-feira)?|quarta(?:-feira)?|"
    r"quinta(?:-feira)?|sexta(?:-feira)?|s[aá]bado|domingo|"
    r"dia\s+\d{1,2}(?:\s+de\s+[A-Za-zÀ-ÿ]+)?"
)
TIME_RE = (
    r"(?:(?:às|as|a)\s+\d{1,2}(?:h|:)?\d{0,2}"
    r"(?:\s+da\s+(?:manh[ãa]|tarde|noite))?"
    r"|\d{1,2}h\d{0,2}"
    r"(?:\s+da\s+(?:manh[ãa]|tarde|noite))?)"
)
REPEAT_PHRASE = (
    r"todos\s+os\s+dias|"
    r"todo\s+dia\s+[uú]til|"
    r"(?:nos|em)\s+dias?\s+[uú]teis|"
    r"dias?\s+[uú]teis|"
    r"todo\s+dia|"
    r"cada\s+dia|"
    r"todas\s+as\s+(?:segundas|ter[cç]as|quartas|quintas|sextas|s[aá]bados|domingos)(?:-feiras)?|"
    r"toda\s+(?:segunda|ter[cç]a|quarta|quinta|sexta|s[aá]bado|domingo)(?:-feira)?"
)
REMINDER_RE = re.compile(
    rf"(?i)^(?:me\s+)?(?:lembra|lembre)(?:\s+de)?\s+"
    rf"(?P<body>.+?)\s+(?P<day>{DAY_RE})(?:\s+(?P<time>{TIME_RE}))?\s*$"
)
RECURRING_HEAD_RE = re.compile(
    rf"(?i)^(?:me\s+)?(?:lembra|lembre)(?:\s+de)?\s+"
    rf"(?P<repeat>{REPEAT_PHRASE})(?:\s+(?P<time>{TIME_RE}))?\s+"
    rf"(?:de\s+)?(?P<body>.+?)\s*$"
)
RECURRING_TAIL_RE = re.compile(
    rf"(?i)^(?:me\s+)?(?:lembra|lembre)(?:\s+de)?\s+"
    rf"(?P<body>.+?)\s+(?P<repeat>{REPEAT_PHRASE})"
    rf"(?:\s+(?P<time>{TIME_RE}))?\s*$"
)
CAPTURE_RE = re.compile(
    r"(?i)^anota(?:r)?(?:\s+que|\s+isto|\s+isso)?\s*(?::\s*)?(?P<body>.+)$"
)
SEARCH_RE = re.compile(
    r"(?i)^(?:o que (?:eu )?(?:escrevi|anotei) sobre|onde (?:eu )?anotei)\s+(?P<query>.+?)\s*$"
)
SEARCH_STOP = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "que",
    "para",
    "pra",
    "com",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "por",
    "sobre",
    "um",
    "uma",
    "uns",
    "umas",
    "ao",
    "aos",
    "eu",
    "me",
    "se",
    "ou",
    "as",
    "os",
}
BRIEFING_RE = re.compile(
    r"(?i)^(?:bom dia(?: jarvis)?|briefing(?: da manh[ãa])?|"
    r"resumo do dia|o que tenho (?:pra|para) hoje)\s*$"
)
DISMISS_RE = re.compile(
    r"(?i)^(?:valeu|obrigado|obrigada|tchau|at[eé] logo|at[eé] mais)[, ]+jarvis$"
)
WEEK_RE = re.compile(
    r"(?i)^(?:como foi (?:a |minha )?semana|resumo da semana|revis[aã]o da semana)$"
)
DAY_CLOSE_RE = re.compile(
    r"(?i)^(?:como foi (?:o |meu )?dia|resumo do fim do dia|fechamento do dia)$"
)
FOCUS_RE = re.compile(
    r"^(?:"
    r"quais(?: sao)? minhas prioridades(?: de| para| pra)? hoje|"
    r"minhas prioridades(?: de| para| pra)? hoje|"
    r"prioridades de hoje|"
    r"foco do dia|"
    r"qual(?: e| eh)? o foco do dia|"
    r"o que(?: eu)? priorizo hoje"
    r")$"
)
HELP_RE = re.compile(
    r"^(?:"
    r"ajuda|"
    r"me ajuda|"
    r"o que voce (?:sabe )?faz(?:er)?|"
    r"o que voce sabe|"
    r"quais(?: sao)? os comandos|"
    r"que comandos(?: voce tem)?|"
    r"lista de comandos|"
    r"o que eu posso (?:te )?pedir"
    r")$"
)
READWISE_RE = re.compile(
    r"^(?:importa|importe|importar) (?:"
    r"meus destaques(?: do readwise)?|(?:os )?destaques do readwise"
    r")$"
)
DESTAQUES_RE = re.compile(
    r"^(?:importa|importe|importar)(?: os)? destaques"
    r"(?: do (?P<fonte>kindle|pdf|koreader))?$"
)
OFFLINE_NOISE = {
    "como",
    "esta",
    "estao",
    "qual",
    "quais",
    "onde",
    "quando",
    "porque",
    "explica",
    "explicar",
    "fale",
    "fala",
    "conta",
    "conte",
    "diz",
    "diga",
    "sabe",
    "voce",
    "jarvis",
    "isso",
    "esse",
    "essa",
    "este",
    "isto",
    "algo",
    "algum",
    "alguma",
    "pode",
    "poderia",
    "quero",
    "queria",
    "gostaria",
    "hoje",
    "agora",
    "favor",
    "porfavor",
    "sobre",
    "pro",
    "pra",
}
HISTORY_RE = re.compile(
    r"^(?:o que(?: eu)?(?: te)? pedi|que pedidos eu(?: te)? fiz)"
    r"(?: (hoje|ontem|anteontem))?$"
)
PROFILE_RE = re.compile(
    r"(?i)^(?:me\s+)?(?:lembra|lembre)\s+que\s+eu\s+(?P<body>.+)$"
)
JIRA_RE = re.compile(r"^o que (?:eu )?tenho no jira$")
GITHUB_RE = re.compile(r"^como estao (?:os )?meus (?:prs|pull requests|reviews)$")
MAIL_RE = re.compile(
    r"^tenho (?:e-?mails?|emails?) (?:importante|importantes|nao lidos|nao lido)$"
)
INBOX_RE = re.compile(r"^o que os assistentes mandaram$")
INBOX_SUMMARY_RE = re.compile(
    r"^(?:"
    r"resume os recados(?: dos assistentes)?|"
    r"resume a caixa(?: de entrada)?|"
    r"resume os assistentes|"
    r"resumo dos recados(?: dos assistentes)?|"
    r"resumo da caixa(?: de entrada)?|"
    r"resumo dos assistentes|"
    r"o que ha de novo na caixa|"
    r"tem recado novo|"
    r"que recados chegaram"
    r")$"
)
OUTBOX_RE = re.compile(
    r"(?i)^pede\s+(?:pro|pra|para)(?:\s+(?:o|a))?\s+(?P<name>\S+)\s+(?P<body>.+)$"
)
DONE_RE = re.compile(
    r"(?i)^(?:marca|marque|marcar)(?: como)? "
    r"(?:feito|feita|conclu[ií]do|conclu[ií]da)(?: a tarefa| o item)?\s+(?P<body>.+)$"
)
AGENDA_RE = re.compile(
    r"(?i)^(?:"
    r"o que (?:eu )?tenho(?!\s+(?:pra|para)\s+hoje\b)"
    r"(?:\s+(?:pra|para|em|de))?\s+"
    r"(?P<day>hoje|amanh[ãa]|depois de amanh[ãa])"
    r"|"
    r"o que (?:eu )?tenho na agenda"
    r"(?:\s+(?:de|para|pra))?\s*"
    r"(?P<day_agenda>hoje|amanh[ãa]|depois de amanh[ãa])?"
    r"|"
    r"(?:minha agenda|agenda|compromissos|meus compromissos)"
    r"(?:\s+(?:de|do|da|para|pra))?\s*"
    r"(?P<day2>hoje|amanh[ãa]|depois de amanh[ãa])?"
    r")$"
)
SNOOZE_RE = re.compile(
    r"(?i)^(?:adia(?:r)?|empurra(?:r)?|atrasa(?:r)?)\s+"
    r"(?:o\s+|a\s+)?lembrete"
    r"(?:\s+(?:de|do|da|sobre))?"
    r"(?:\s+(?P<body>.+))?$"
)
CANCEL_RE = re.compile(
    r"(?i)^(?:cancela(?:r)?|cancele|apaga(?:r)?|remove(?:r)?|desmarca(?:r)?)\s+"
    r"(?:o\s+|a\s+)?lembrete"
    r"(?:\s+(?:de|do|da|sobre))?"
    r"(?:\s+(?P<body>.+))?$"
)
STUDY_RE = re.compile(
    r"(?i)^(?:me\s+)?(?:testa|teste|testar)\s+(?:sobre|em)\s+(?P<query>.+?)\s*$"
    r"|^(?:me\s+testa|me\s+teste|me\s+testar)\s*$"
)
RELATED_RE = re.compile(
    r"(?i)^(?:quais\s+(?:s[aã]o\s+)?)?(?:as\s+)?notas\s+relacionadas\s+"
    r"(?:a|ao|à|aos|às|com|de|do|da|sobre)\s+(?P<query>.+?)\s*$"
)
REVIEW_DAY_RE = re.compile(r"^(?:revisao do dia|revisao de hoje)$")
REVIEW_BOOK_RE = re.compile(
    r"^(?:me pergunta|me pergunte|pergunta|pergunte) sobre (?:o |a )?livro(?:\s+(.*))?$"
)
REVIEW_PAUSE_RE = re.compile(r"^(?:pausa|pausar|para) a revisao$")
REVIEW_RESUME_RE = re.compile(
    r"^(?:retoma|retomar|continua|continuar) a revisao$"
)
REVIEW_GRADE_RE = re.compile(r"^(?:eu )?(acertei|errei|dificil|bom|facil)$")
MUTE_TODAY_RE = re.compile(
    r"^(?:silencia|silencie|silenciar) (?:esse|este|o ultimo) aviso hoje$"
)
MUTE_ALWAYS_RE = re.compile(
    r"^(?:silencia|silencie|silenciar) (?:sempre|(?:esse|este|o ultimo) aviso sempre)$"
)
PAUSE_ALERTS_RE = re.compile(
    r"^(?:pausa|pausar|para) os alertas ate amanha$"
)
MODO_PRIVADO_ON = {
    "modo privado",
    "entrar no modo privado",
    "ativa o modo privado",
    "ativar o modo privado",
    "liga o modo privado",
}
MODO_PRIVADO_OFF = {
    "sai do modo privado",
    "sair do modo privado",
    "desativa o modo privado",
    "desativar o modo privado",
    "encerrar o modo privado",
}
ABOUT_RE = re.compile(
    r"^(?:o que voce sabe sobre mim|o que voce sabe de mim|"
    r"o que voce lembra sobre mim|o que voce guardou sobre mim)$"
)
LEARNED_RE = re.compile(
    r"^(?:o que(?: eu)? aprendi(?:"
    r" (?:nesta|esta|essa) semana|"
    r" nos ultimos (?:7|sete) dias"
    r")?)$"
)
PERSONA_RE = re.compile(
    r"^(?:mostra(?:r)? (?:a |sua |a sua )?persona|"
    r"qual(?: e| eh)? (?:a |sua |a sua )?persona)$"
)
SOURCES_RE = re.compile(
    r"^(?:quais fontes (?:eu )?tenho|que fontes (?:eu )?tenho|"
    r"quais sao minhas fontes)$"
)
FORGET_RE = re.compile(
    r"(?i)^(?:esquece|esqueça|esquec[ae]r)(?:\s+que\s+eu)?(?:\s+(?P<body>.+))?$"
)
CAPTURE_HEAD_RE = re.compile(
    r"(?i)^(?:na|no|em)\s+(?:a\s+|o\s+)?(?:(?P<place>pasta|nota)\s+)?"
    r"(?P<where>.+?)\s+que\s+(?P<body>.+)$"
)
CAPTURE_TAIL_RE = re.compile(
    r"(?i)^(?P<body>.+?)\s+(?:na|no|em)\s+(?:a\s+|o\s+)?"
    r"(?P<place>pasta|nota)\s+(?P<where>.+)$"
)
SNOOZE_TAIL_RE = re.compile(
    rf"(?i)^(?P<subject>.*?)"
    rf"(?:"
    rf"(?:^|\s)(?:para|pra)\s+(?P<day>{DAY_RE})(?:\s+(?P<time>{TIME_RE}))?"
    rf"|(?:^|\s)(?P<timeonly>{TIME_RE})"
    rf"|(?:^|\s)em\s+(?P<amount>\d+|uma|um|duas|dois)\s+"
    rf"(?P<unit>hora|horas|minuto|minutos)"
    rf")\s*$"
)
YES_WORDS = {
    "sim",
    "pode",
    "pode gravar",
    "grava",
    "grava sim",
    "isso",
    "confirma",
    "pode sim",
}
NO_WORDS = {"nao", "deixa", "agora nao", "deixa quieto", "nao grava"}
CHOICE_WORDS = {
    "1": 0,
    "primeira": 0,
    "primeiro": 0,
    "a primeira": 0,
    "o primeiro": 0,
    "2": 1,
    "segunda": 1,
    "a segunda": 1,
    "3": 2,
    "terceira": 2,
    "a terceira": 2,
    "4": 3,
    "quarta": 3,
    "a quarta": 3,
}
TASK_RE = re.compile(
    r"^(?P<prefix>\s*- \[(?P<mark>[ xX])\] )"
    r"(?P<body>.*?) @ (?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2})(?P<tail>.*)$"
)
OPEN_TASK_RE = re.compile(r"^\s*- \[ \] (.+?)\s*$")
CAIXA_RE = re.compile(r"^\s*- \[[ xX]\] ")
_CAIXAS = {}
_TETO_CAIXAS = 200000
JANELA_RECENTE_NS = 2_000_000_000
BULLET_RE = re.compile(r"^\s*- (?!\[[ xX]\])(.+?)\s*$")
ZONE_RE = re.compile(
    r"\b((?:America|Europe|Africa|Asia|Pacific|Brazil|UTC)/[A-Za-z0-9_+-]+)\b"
)
LABELS = (
    ("daily", ("nota diaria",)),
    ("agenda", ("agenda profissional",)),
    ("reminders", ("lembretes", "tarefas")),
    ("week", ("revisao semanal", "resumo da semana")),
    ("inbox", ("caixa de entrada", "inbox dos assistentes")),
    ("notes", ("inbox de notas", "caixa de notas")),
    ("outbox", ("caixa de saida",)),
    ("profile", ("nota de perfil", "memoria de longo prazo")),
)


def fold(text):
    return _fold(text)


MONTH_INDEX = {fold(name): index + 1 for index, name in enumerate(MONTHS)}


class Intent:
    def __init__(self, kind, text="", query="", place=""):
        self.kind = kind
        self.text = text
        self.query = query
        self.place = place


class Places:
    def __init__(
        self,
        timezone_name,
        daily="",
        agenda="",
        reminders="",
        week="",
        inbox="",
        outbox="",
        profile="",
        notes="",
    ):
        self.timezone_name = timezone_name
        self.daily = daily
        self.agenda = agenda
        self.reminders = reminders
        self.week = week
        self.inbox = inbox
        self.outbox = outbox
        self.profile = profile
        self.notes = notes

    @property
    def tz(self):
        from zoneinfo import ZoneInfo

        try:
            return ZoneInfo(self.timezone_name)
        except Exception:
            return ZoneInfo(DEFAULT_TIMEZONE)


class Hit:
    def __init__(self, path, title, snippet, relative=""):
        self.path = path
        self.title = title
        self.snippet = snippet
        self.relative = relative


class DueReminder:
    def __init__(self, path, line_index, text, when):
        self.path = path
        self.line_index = line_index
        self.text = text
        self.when = when


def normalize_phrase(message):
    text = " ".join((message or "").split())
    text = re.sub(r"(?i)^(?:hey|ei)[, ]+jarvis[, ]*", "", text).strip()
    return text.strip(" \t.?!")


_NEW_CHAT = {
    "nova conversa",
    "limpar a conversa",
    "limpa a conversa",
    "zerar a conversa",
    "zera a conversa",
    "comecar de novo",
}
_SAVE_LAST = re.compile(
    r"(?:salva|salve|salvar|guarda|guarde|guardar|anota|anote|anotar) (?:isso|isto)"
)
_DEICTIC = {
    "e sobre isso",
    "sobre isso",
    "e isso",
    "e isto",
    "sobre isto",
    "e sobre aquilo",
    "e aquilo",
}


def is_deictic(message):
    text = fold(normalize_phrase(message))
    if text in _DEICTIC:
        return True
    words = text.split()
    return len(words) >= 2 and words[0] == "e" and len(words) <= 6


def classify(message):
    from .comandos import classificar
    return classificar(message)

def offer_choice(message, pending):
    if not pending:
        return None
    text = fold(normalize_phrase(message))
    kind = pending.get("kind")
    if kind in {
        "week",
        "day",
        "atualizar",
        "anki",
        "destaques",
        "destaques_cartoes",
        "estudo_midia",
        "estudo_cartoes",
        "estudo_ligacoes",
        "fontes_notas",
    }:
        if text in YES_WORDS:
            return "yes"
        if text in NO_WORDS:
            return "no"
        return None
    if kind in {"done", "snooze", "cancel", "capture", "forget"}:
        if text in NO_WORDS:
            return "no"
        options = pending.get("options") or []
        if text in YES_WORDS and kind in {"capture", "forget"} and len(options) == 1:
            return "yes"
        index = CHOICE_WORDS.get(text)
        if index is not None and index < len(options):
            return index
        return None
    return None


def load_places(root):
    root = Path(root)
    chunks = []
    for name in ("AGENTS.md", "CLAUDE.md", "README.md"):
        path = root / name
        if path.is_file():
            chunks.append(_read(path))
    blob = "\n".join(chunks)
    found = {key: "" for key, _labels in LABELS}
    for line in blob.splitlines():
        match = re.search(r"`([^`]+)`", line)
        if not match:
            continue
        folded = fold(line)
        for key, labels in LABELS:
            if found[key]:
                continue
            if any(_label_in(folded, label) for label in labels):
                safe = _safe_relative(match.group(1))
                if safe:
                    found[key] = safe
    zone = DEFAULT_TIMEZONE
    zones = ZONE_RE.findall(blob)
    if DEFAULT_TIMEZONE in zones:
        zone = DEFAULT_TIMEZONE
    elif zones:
        zone = zones[0]
    return Places(
        zone,
        found["daily"],
        found["agenda"],
        found["reminders"],
        found.get("week", ""),
        found.get("inbox", ""),
        found.get("outbox", ""),
        found.get("profile", ""),
        found.get("notes", ""),
    )


def daily_note_path(root, places, day):
    root = Path(root)
    if places.daily:
        return root / _apply_date(places.daily, day, root)
    configured = _obsidian_daily(root, day)
    if configured is not None:
        return configured
    parent = _dated_parent(root)
    if parent is not None:
        return parent / f"{day.strftime('%Y-%m-%d')}.md"
    return root / f"{day.strftime('%Y-%m-%d')}.md"


def agenda_path(root, places):
    root = Path(root)
    if places.agenda:
        return root / places.agenda
    for candidate in (root / "Agenda Profissional.md", root / "Agenda Profissional"):
        if candidate.exists():
            return candidate
    return None


def reminder_note_path(root, places, when):
    root = Path(root)
    if places.reminders:
        relative = places.reminders
        if relative.endswith(".md"):
            return root / relative
        return root / relative / f"{when.strftime('%Y-%m-%d')}.md"
    return daily_note_path(root, places, when.date())


def help_speech(has_vault=True):
    from .comandos import texto_ajuda
    return texto_ajuda(has_vault)

def install_hint():
    from . import config

    name = Path(str(config.CLAUDE_BIN or "claude")).name.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name):
        name = "claude"
    return (
        f"Não encontrei o comando {name} no PATH. "
        "Instale o Claude Code, deixe esse comando disponível "
        "e rode ele uma vez para fazer login."
    )


def offline_query(message):
    tokens = []
    for token in fold(normalize_phrase(message)).split():
        if len(token) < 3 or token in SEARCH_STOP or token in OFFLINE_NOISE:
            continue
        tokens.append(token)
    return " ".join(tokens[:8])


def offline_answer(message, root):
    query = offline_query(message)
    if root and query:
        hits = search_notes(root, query)
        if hits:
            return search_speech(root, query) + " " + install_hint()
    return help_speech(root is not None) + " " + install_hint()


def run_routine(root, intent, now, read_only=False, before_write=None, session=None):
    if intent.kind == "help":
        return help_speech(True)
    if intent.kind in {"jira", "github", "mail"}:
        from .external import handle

        return handle(intent.kind)
    root = Path(root)
    places = load_places(root)
    moment = _aware(now, places)
    if intent.kind == "save_last":
        body = " ".join((intent.text or "").split())
        if not body:
            return "Não há resposta anterior para salvar, senhor."
        if read_only:
            return "Não gravei a resposta, senhor. O vault está bloqueado para escrita agora."
        if before_write:
            before_write()
        try:
            append_capture(root, places, body, moment)
        except GuardError:
            return _blocked_speech()
        return "Salvei a resposta anterior na nota de hoje, senhor."
    if intent.kind == "inbox_summary":
        from .bridge import summarize_inbox

        return summarize_inbox(root)
    if intent.kind == "inbox":
        from .bridge import read_inbox

        return read_inbox(root, read_only=read_only, before_write=before_write)
    if intent.kind == "outbox":
        from .bridge import write_outbox

        return write_outbox(
            root,
            places,
            intent.query,
            intent.text,
            moment,
            read_only=read_only,
            before_write=before_write,
        )
    if intent.kind == "profile":
        from .bridge import remember_fact

        return remember_fact(
            root,
            places,
            intent.text,
            moment,
            read_only=read_only,
            before_write=before_write,
        )
    if intent.kind == "week":
        return _week_routine(root, places, moment, read_only, session)
    if intent.kind == "day":
        return _day_routine(root, places, moment, read_only, session)
    if intent.kind == "done":
        return _done_routine(root, intent.text, read_only, before_write, session)
    if intent.kind == "snooze":
        return _snooze_routine(root, intent.text, moment, read_only, before_write, session)
    if intent.kind == "cancel":
        return _cancel_routine(root, intent.text, read_only, before_write, session)
    if intent.kind == "readwise":
        from .readwise import import_speech

        return import_speech(
            root,
            moment,
            read_only=read_only,
            before_write=before_write,
        )
    if intent.kind == "destaques":
        from .destaques import preparar_entrada

        return preparar_entrada(
            root,
            intent.query or "",
            read_only=read_only,
            session=session,
        )
    if intent.kind == "focus":
        return focus_speech(root, moment)
    if intent.kind == "agenda":
        return agenda_speech(root, places, moment, intent.query)
    if intent.kind == "briefing":
        return briefing_speech(root, places, moment)
    if intent.kind == "search":
        return search_speech(root, intent.query)
    if intent.kind == "learned":
        from .aprendizado import learned_speech

        return learned_speech(root, moment)
    if intent.kind == "persona":
        from .persona import persona_speech

        return persona_speech(root)
    if intent.kind == "sources":
        from .fontes import sources_speech

        return sources_speech(root)
    if intent.kind in {"capture_video", "capture_article", "capture_podcast"}:
        from .midia import capturar_turno

        return capturar_turno(
            root,
            intent,
            moment,
            read_only=read_only,
            before_write=before_write,
        )
    if intent.kind in {"study_video", "study_audio", "media_queue"}:
        from .estudo_midia import turno

        return turno(
            root,
            intent,
            moment,
            read_only=read_only,
            before_write=before_write,
            session=session,
        )
    if intent.kind == "capture":
        return _capture_routine(
            root, places, intent, moment, read_only, before_write, session
        )
    if intent.kind == "reminder":
        parsed = parse_reminder(intent.text, moment)
        if parsed is None:
            return "Não entendi o lembrete, senhor."
        when, text, error, repeat = parsed
        if error:
            return error
        if read_only:
            return "Não gravei o lembrete, senhor. O vault está bloqueado para escrita agora."
        if before_write:
            before_write()
        try:
            append_reminder(root, places, text, when, repeat)
        except GuardError:
            return _blocked_speech()
        return _reminder_confirmation(text, when, moment, repeat)
    return ""


def _split_capture(body):
    text = " ".join((body or "").split())
    match = CAPTURE_HEAD_RE.match(text)
    if match and match.group("body").strip():
        place = (match.group("place") or "").casefold()
        where = _clean_where(match.group("where"))
        return match.group("body").strip(), place, where
    match = CAPTURE_TAIL_RE.match(text)
    if match and match.group("body").strip():
        where = _clean_where(match.group("where"))
        return match.group("body").strip(), match.group("place").casefold(), where
    return text, "", ""


def _clean_where(where):
    text = " ".join((where or "").split()).strip(" \t.?!")
    return re.sub(r"(?i)^(da|do|de|das|dos)\s+", "", text).strip()


def _capture_routine(root, places, intent, moment, read_only, before_write, session):
    body = " ".join((intent.text or "").split())
    where = " ".join((intent.query or "").split())
    place = (getattr(intent, "place", "") or "").casefold()
    if not body:
        return "O que devo anotar, senhor?"
    if not where:
        return _write_daily(root, places, body, moment, read_only, before_write)
    decision, options = _capture_decision(root, place, where)
    if decision == "write" and options:
        if read_only:
            return "Não gravei a nota, senhor. O vault está bloqueado para escrita agora."
        if before_write:
            before_write()
        try:
            return _write_capture_option(root, places, options[0], body, moment)
        except GuardError:
            return _blocked_speech()
    if session is not None:
        session["pending"] = {"kind": "capture", "body": body, "options": options}
    return _capture_question(where, options)


def apply_capture_choice(root, pending, choice, now):
    options = (pending or {}).get("options") or []
    if choice == "yes":
        if len(options) != 1:
            return "Diga o número, senhor."
        choice = 0
    if not isinstance(choice, int) or choice < 0 or choice >= len(options):
        return "Não encontrei essa opção, senhor."
    body = " ".join(((pending or {}).get("body") or "").split())
    if not body:
        return "O que devo anotar, senhor?"
    root = Path(root)
    places = load_places(root)
    moment = _aware(now, places)
    try:
        return _write_capture_option(root, places, options[choice], body, moment)
    except GuardError:
        return _blocked_speech()


def _write_daily(root, places, body, moment, read_only, before_write):
    if read_only:
        return "Não gravei a nota, senhor. O vault está bloqueado para escrita agora."
    if before_write:
        before_write()
    try:
        append_capture(root, places, body, moment)
    except GuardError:
        return _blocked_speech()
    return "Anotei na nota de hoje, senhor."


def _capture_question(where, options):
    if len(options) == 1:
        option = options[0]
        if option.get("mode") == "daily":
            nome = where or "esse destino"
            return f"Não achei {nome}, senhor. Anoto na nota de hoje?"
        if option.get("mode") == "create":
            return f"Não há nota nessa pasta, senhor. Crio {option.get('label')}?"
        return f"Anoto em {option.get('label')}, senhor?"
    parts = [f"{index + 1}, {item.get('label')}" for index, item in enumerate(options)]
    return "Encontrei mais de um destino, senhor. Diga o número. " + ". ".join(parts) + "."


def _capture_decision(root, place, where):
    found = _capture_targets(root, where)
    if place == "pasta":
        return _decide_folder(root, where, found)
    if place == "nota":
        return _decide_note(where, found)
    if found["notes_exact"] and not found["folders_exact"]:
        if len(found["notes_exact"]) == 1:
            return "write", found["notes_exact"]
        return "ask", found["notes_exact"][:4]
    if found["folders_exact"]:
        return _decide_folder(root, where, found)
    if len(found["notes_partial"]) == 1 and not found["folders_partial"]:
        return "ask", found["notes_partial"]
    if found["notes_partial"]:
        return "ask", found["notes_partial"][:4]
    if found["folders_partial"]:
        return _decide_folder(root, where, found)
    return "ask", [_daily_option()]


def _decide_note(where, found):
    notes = found["notes_exact"] or found["notes_partial"]
    if len(found["notes_exact"]) == 1:
        return "write", found["notes_exact"]
    if len(notes) > 1:
        return "ask", notes[:4]
    if len(notes) == 1:
        return "ask", notes
    return "ask", [_daily_option()]


def _decide_folder(root, where, found):
    folders = found["folders_exact"] or found["folders_partial"]
    if not folders:
        return "ask", [_daily_option()]
    if len(folders) > 1:
        options = []
        for folder in folders[:4]:
            inside = _notes_in_folder(root, folder["relative"])
            if inside:
                options.extend(inside[:2])
            else:
                options.append(_create_option(folder["relative"]))
        if not options:
            return "ask", [_daily_option()]
        return "ask", options[:4]
    inside = _notes_in_folder(root, folders[0]["relative"])
    if not inside:
        return "ask", [_create_option(folders[0]["relative"])]
    return "ask", inside[:4]


def _daily_option():
    return {"relative": "", "label": "nota de hoje", "mode": "daily"}


def _create_option(folder):
    relative = folder.strip("/") + "/nota.md"
    return {"relative": relative, "label": relative, "mode": "create"}


def _note_option(relative):
    return {"relative": relative, "label": relative, "mode": "append"}


def _capture_targets(root, where):
    folded = fold(where)
    exact_notes = []
    partial_notes = []
    exact_folders = []
    partial_folders = []
    allow_partial = len(folded) >= 3
    root = Path(root)
    if folded:
        for path in iter_notes(root):
            relative = _relative_note(root, path)
            title = _title(path, _read(path))
            stem = path.stem
            bare = relative[:-3] if relative.endswith(".md") else relative
            names = {fold(stem), fold(title), fold(relative), fold(bare)}
            option = _note_option(relative)
            if folded in names:
                exact_notes.append(option)
            elif allow_partial and (
                folded in fold(stem) or folded in fold(title) or folded in fold(relative)
            ):
                partial_notes.append(option)
            if len(exact_notes) + len(partial_notes) > 12:
                break
        if root.is_dir():
            for dirpath, dirnames, _filenames in os.walk(root):
                dirnames[:] = [
                    name
                    for name in dirnames
                    if name not in SKIP_DIRS and not name.startswith(".")
                ]
                current = Path(dirpath)
                try:
                    if current.resolve() == root.resolve():
                        continue
                    relative = current.resolve().relative_to(root.resolve()).as_posix()
                except (OSError, ValueError):
                    continue
                if any(part.startswith(".") or part in SKIP_DIRS for part in Path(relative).parts):
                    continue
                option = {"relative": relative, "label": relative, "mode": "folder"}
                if fold(current.name) == folded or fold(relative) == folded:
                    exact_folders.append(option)
                elif allow_partial and (folded in fold(current.name) or folded in fold(relative)):
                    partial_folders.append(option)
                if len(exact_folders) + len(partial_folders) > 12:
                    break
    exact_notes.sort(key=lambda item: item["relative"])
    partial_notes.sort(key=lambda item: item["relative"])
    exact_folders.sort(key=lambda item: item["relative"])
    partial_folders.sort(key=lambda item: item["relative"])
    return {
        "notes_exact": exact_notes,
        "notes_partial": partial_notes,
        "folders_exact": exact_folders,
        "folders_partial": partial_folders,
    }


def _notes_in_folder(root, folder):
    prefix = folder.strip("/") + "/"
    found = []
    for path in iter_notes(root):
        relative = _relative_note(root, path)
        if relative == prefix[:-1] or relative.startswith(prefix):
            found.append(_note_option(relative))
        if len(found) >= 6:
            break
    found.sort(key=lambda item: item["relative"])
    return found


def _write_capture_option(root, places, option, body, moment):
    mode = option.get("mode")
    if mode == "daily":
        append_capture(root, places, body, moment)
        return "Anotei na nota de hoje, senhor."
    relative = option.get("relative") or ""
    path = _capture_destination(root, relative, create=mode == "create")
    if path is None:
        return "Não gravei, senhor. O caminho ficou fora do vault."
    line = f"- {moment.strftime('%H:%M')} {body}\n"
    if mode == "create":
        path.parent.mkdir(parents=True, exist_ok=True)
        text = f"# {path.stem}\n\n{line}"
        if not _guardar(path, text, checar=text, raiz=root):
            return _blocked_speech()
        return f"Anotei em {relative}, senhor."
    _append_line(root, places, path, moment, line)
    return f"Anotei em {relative}, senhor."


def _capture_destination(root, relative, create):
    text = (relative or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or ".." in text.split("/"):
        return None
    parts = [part for part in text.split("/") if part and part != "."]
    if not parts or any(part.startswith(".") or part in SKIP_DIRS for part in parts):
        return None
    root = Path(root).resolve()
    path = (root / "/".join(parts)).resolve()
    if not _inside(path, root):
        return None
    if path.exists() and not path.is_file():
        return None
    if not create and not path.is_file():
        return None
    return path


def append_capture(root, places, text, now):
    moment = _aware(now, places)
    path = daily_note_path(root, places, moment.date())
    bullet = f"- {moment.strftime('%H:%M')} {' '.join(text.split())}\n"
    _append_line(root, places, path, moment, bullet)
    return path


def append_reminder(root, places, text, when, repeat=""):
    path = reminder_note_path(root, places, when)
    extra = f" @repete {repeat}" if repeat else ""
    line = f"- [ ] {' '.join(text.split())} @ {when.strftime('%Y-%m-%d %H:%M')}{extra}\n"
    _append_line(root, places, path, when, line)
    return path


def week_note_path(root, places, day):
    root = Path(root)
    monday = day - timedelta(days=day.weekday())
    if places.week:
        return root / _apply_date(places.week, monday, root)
    daily = daily_note_path(root, places, monday)
    return daily.parent / f"semana-{monday.strftime('%Y-%m-%d')}.md"


def _blocked_speech():
    return FALA_BLOQUEIO


def _guardar(path, text, checar=None, raiz=None):
    from .guardas import GuardError, escrever

    try:
        escrever(path, text, checar=checar, raiz=raiz)
    except GuardError:
        return False
    return True


def write_summary(path, body, raiz=None):
    path = Path(path)
    if caminho_bloqueado(path):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        current = _read(path)
        if current.startswith("---"):
            end = current.find("\n---", 3)
            if end != -1:
                front = current[: end + 4]
                text = front.rstrip() + "\n\n" + body.lstrip()
                if not _guardar(path, text, checar=body, raiz=raiz):
                    return None
                return path
    text = body if body.endswith("\n") else body + "\n"
    if not _guardar(path, text, checar=body, raiz=raiz):
        return None
    return path


def mark_task(root, relative, text):
    path = _note_file(root, relative)
    if path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    folded = fold(text)
    for index, line in enumerate(lines):
        if "- [ ]" not in line:
            continue
        if folded and folded in fold(line):
            lines[index] = line.replace("- [ ]", "- [x]", 1)
            if not _guardar(path, "".join(lines), checar="", raiz=root):
                return False
            return True
    return False


def _week_routine(root, places, moment, read_only, session):
    monday = moment.date() - timedelta(days=moment.weekday())
    sunday = monday + timedelta(days=6)
    notes, done, pending = _week_items(root, moment, monday, sunday)
    speech = _week_speech(monday, sunday, notes, done, pending)
    if read_only:
        return speech + " Não gravei nada porque o vault está bloqueado para escrita."
    path = week_note_path(root, places, moment.date())
    body = _week_body(monday, sunday, notes, done, pending)
    if session is not None:
        session["pending"] = {
            "kind": "week",
            "relative": path.relative_to(root).as_posix(),
            "body": body,
        }
    return speech + " Quer que eu grave esse resumo, senhor?"


def autosave_week(root, now, read_only=False):
    root = Path(root)
    places = load_places(root)
    moment = _aware(now, places)
    monday = moment.date() - timedelta(days=moment.weekday())
    sunday = monday + timedelta(days=6)
    notes, done, pending = _week_items(root, moment, monday, sunday)
    speech = _week_speech(monday, sunday, notes, done, pending)
    if read_only:
        return speech + " Não gravei nada porque o vault está bloqueado para escrita."
    path = week_note_path(root, places, moment.date())
    if not _inside(path, root):
        return speech + " Não gravei nada porque o destino ficou fora do vault."
    if path.is_file():
        return speech + " O resumo dessa semana já está no vault."
    if write_summary(path, _week_body(monday, sunday, notes, done, pending), raiz=root) is None:
        return speech + " " + _blocked_speech()
    return speech + " Gravei o resumo da semana."


def day_note_path(root, places, day):
    daily = daily_note_path(root, places, day)
    return daily.parent / f"fim-{day.strftime('%Y-%m-%d')}.md"


def day_digest(root, places, moment):
    moment = _aware(moment, places)
    day = moment.date()
    titles, done, pending = _week_items(root, moment, day, day)
    annotated = []
    seen = set()
    for item in _capture_lines(root, places, day) + titles:
        key = fold(item)
        if not key or key in seen or key.startswith("fim do dia"):
            continue
        seen.add(key)
        annotated.append(item)
    finished, cancelled = _reminder_outcomes(root, day)
    skip = {fold(item) for item in finished + cancelled}
    done = [item for item in done if fold(item) not in skip]
    tomorrow = _tomorrow_lines(root, places, moment)
    return annotated, done, pending, finished, tomorrow


def _capture_lines(root, places, day):
    path = daily_note_path(root, places, day)
    if not path.is_file():
        return []
    found = []
    for line in _read(path).splitlines():
        match = re.match(r"^\s*-\s+\d{2}:\d{2}\s+(.+)$", line)
        if not match:
            continue
        text = " ".join(match.group(1).split())
        if text:
            found.append(text)
    return found


def _day_routine(root, places, moment, read_only, session):
    notes, done, pending, finished, tomorrow = day_digest(root, places, moment)
    speech = _day_speech(moment, notes, done, pending, finished, tomorrow)
    if read_only:
        return speech + " Não gravei nada porque o vault está bloqueado para escrita."
    path = day_note_path(root, places, moment.date())
    if not _inside(path, root):
        return speech + " Não gravei nada porque o destino ficou fora do vault."
    body = _day_body(moment.date(), notes, done, pending, finished, tomorrow)
    if session is not None:
        session["pending"] = {
            "kind": "day",
            "relative": path.resolve().relative_to(Path(root).resolve()).as_posix(),
            "body": body,
        }
    return speech + " Quer que eu grave esse resumo, senhor?"


def _day_speech(moment, notes, done, pending, finished, tomorrow):
    parts = [f"Senhor, fechando o dia {_spoken_date(moment)}."]
    parts.append(_list_speech("Anotações", notes))
    parts.append(_list_speech("Tarefas feitas", done))
    parts.append(_list_speech("Lembretes concluídos", finished))
    parts.append(_list_speech("Pendências", pending))
    parts.append(_list_speech("Amanhã", tomorrow))
    return " ".join(parts)


def _day_body(day, notes, done, pending, finished, tomorrow):
    lines = [f"# Fim do dia {day.isoformat()}", ""]
    lines.extend(_section("Anotações", notes, "Nada anotado neste dia."))
    lines.extend(_section("Feitas", done, "Nenhuma tarefa concluída neste dia."))
    lines.extend(
        _section("Lembretes concluídos", finished, "Nenhum lembrete concluído neste dia.")
    )
    lines.extend(_section("Pendentes", pending, "Nenhuma pendência neste dia."))
    lines.extend(_section("Amanhã", tomorrow, "Nada marcado para amanhã."))
    return "\n".join(lines).rstrip() + "\n"


def _reminder_outcomes(root, day):
    finished = []
    cancelled = []
    seen_done = set()
    seen_cancelled = set()
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        if path.name.casefold() in ROOT_NAMES:
            continue
        for _index, line in linhas_de_caixa(path):
            match = TASK_RE.match(line)
            if not match or match.group("mark").lower() != "x":
                continue
            try:
                stamp = datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if stamp.date() != day:
                continue
            body = match.group("body").strip()
            key = fold(body)
            if not key:
                continue
            if "@cancelado" in match.group("tail"):
                if key not in seen_cancelled:
                    seen_cancelled.add(key)
                    cancelled.append(body)
                continue
            if key not in seen_done:
                seen_done.add(key)
                finished.append(body)
    return finished, cancelled


def _tomorrow_lines(root, places, moment):
    day = moment.date() + timedelta(days=1)
    lines = []
    seen = set()
    for item in day_plan(root, places, day):
        text = " ".join((item.text or "").split())
        if not text:
            continue
        if item.timed and item.when is not None:
            label = f"{item.when.strftime('%H:%M')} {text}"
        else:
            label = text
        key = fold(label)
        if not key or key in seen:
            continue
        seen.add(key)
        lines.append(label)
    return lines


def _done_routine(root, text, read_only, before_write, session):
    if not text:
        return "Qual tarefa devo marcar como feita, senhor?"
    if read_only:
        return "Não marquei a tarefa, senhor. O vault está bloqueado para escrita agora."
    hits = _open_tasks(root, text)
    if not hits:
        return "Não encontrei essa tarefa em aberto, senhor."
    if len(hits) == 1:
        if before_write:
            before_write()
        if mark_task(root, hits[0]["relative"], hits[0]["text"]):
            return f"Marquei como feito, senhor: {hits[0]['text']}."
        return "Não encontrei mais essa tarefa, senhor."
    shown = hits[:4]
    if session is not None:
        session["pending"] = {"kind": "done", "options": shown}
    parts = [f"{index + 1}, {item['text']}" for index, item in enumerate(shown)]
    return "Encontrei mais de uma tarefa, senhor. Diga o número. " + ". ".join(parts) + "."


def _snooze_routine(root, body, moment, read_only, before_write, session):
    if read_only:
        return "Não adiei o lembrete, senhor. O vault está bloqueado para escrita agora."
    subject, spec = _split_snooze(body)
    hits = _match_reminders(root, subject)
    if not hits:
        if subject:
            return "Não encontrei esse lembrete em aberto, senhor."
        return "Não há lembrete em aberto, senhor."
    planned = []
    for item in hits:
        try:
            target = _snooze_when(spec, moment, item["when"])
        except ValueError as error:
            if str(error) == "passado":
                return "Esse horário já passou, senhor."
            return "Não entendi o horário, senhor."
        planned.append((item, target))
    if len(planned) > 1:
        shown = planned[:4]
        if session is not None:
            session["pending"] = {
                "kind": "snooze",
                "options": [_snooze_option(item, target, moment) for item, target in shown],
            }
        parts = [f"{index + 1}, {item['text']}" for index, (item, _target) in enumerate(shown)]
        return "Encontrei mais de um lembrete, senhor. Diga o número. " + ". ".join(parts) + "."
    item, target = planned[0]
    if before_write:
        before_write()
    if not reschedule_reminder(root, item["relative"], item["text"], target, item["line"]):
        return "Não encontrei mais esse lembrete, senhor."
    return postpone_speech(item["text"], target, moment)


def _cancel_routine(root, body, read_only, before_write, session):
    if read_only:
        return "Não cancelei o lembrete, senhor. O vault está bloqueado para escrita agora."
    subject = " ".join((body or "").split()).strip(" \t.?!")
    hits = _match_reminders(root, subject)
    if not hits:
        if subject:
            return "Não encontrei esse lembrete em aberto, senhor."
        return "Não há lembrete em aberto, senhor."
    if len(hits) > 1:
        shown = hits[:4]
        if session is not None:
            session["pending"] = {
                "kind": "cancel",
                "options": [
                    {
                        "relative": item["relative"],
                        "text": item["text"],
                        "line": item["line"],
                    }
                    for item in shown
                ],
            }
        parts = [f"{index + 1}, {item['text']}" for index, item in enumerate(shown)]
        return "Encontrei mais de um lembrete, senhor. Diga o número. " + ". ".join(parts) + "."
    item = hits[0]
    if before_write:
        before_write()
    if not cancel_reminder(root, item["relative"], item["text"], item["line"]):
        return "Não encontrei mais esse lembrete, senhor."
    return f"Cancelei o lembrete, senhor: {item['text']}."


def _snooze_option(item, target, moment):
    return {
        "relative": item["relative"],
        "text": item["text"],
        "line": item["line"],
        "when": target.isoformat(),
        "speech": postpone_speech(item["text"], target, moment),
    }


def apply_reminder_choice(root, pending, choice):
    options = pending.get("options") or []
    if not isinstance(choice, int) or choice < 0 or choice >= len(options):
        return "Não encontrei essa opção, senhor."
    option = options[choice]
    if pending.get("kind") == "cancel":
        if cancel_reminder(root, option.get("relative"), option.get("text"), option.get("line")):
            return f"Cancelei o lembrete, senhor: {option.get('text')}."
        return "Não encontrei mais esse lembrete, senhor."
    if pending.get("kind") != "snooze":
        return "Não encontrei essa opção, senhor."
    try:
        when = datetime.fromisoformat(option.get("when") or "")
    except (TypeError, ValueError):
        return "Não entendi o horário, senhor."
    if reschedule_reminder(root, option.get("relative"), option.get("text"), when, option.get("line")):
        return option.get("speech") or postpone_speech(option.get("text") or "", when)
    return "Não encontrei mais esse lembrete, senhor."


def postpone_speech(text, when, now=None):
    clock = str(when.hour) if when.minute == 0 else f"{when.hour}:{when.minute:02d}"
    if now is None:
        day = f"{WEEKDAYS[when.weekday()]}, {when.day} de {MONTHS[when.month - 1]}"
    else:
        day = _day_phrase(when, now)
    return f"Adiei, senhor. {text} fica {day}, às {clock}."


def reschedule_reminder(root, relative, text, when, line_index=None):
    path = _note_file(root, relative)
    if path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = _find_reminder_line(lines, text, line_index)
    if index is None:
        return False
    current = lines[index]
    stamp = when.strftime("%Y-%m-%d %H:%M")
    updated = re.sub(r"@ \d{4}-\d{2}-\d{2} \d{2}:\d{2}", f"@ {stamp}", current, count=1)
    updated = re.sub(r"\s*@avisado\b", "", updated)
    if updated == current:
        return False
    lines[index] = updated
    return _guardar(path, "".join(lines), checar="", raiz=root)


def cancel_reminder(root, relative, text, line_index=None):
    path = _note_file(root, relative)
    if path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = _find_reminder_line(lines, text, line_index)
    if index is None:
        return False
    current = lines[index]
    updated = current.replace("- [ ]", "- [x]", 1)
    if "@cancelado" not in updated:
        if updated.endswith("\n"):
            updated = updated[:-1] + " @cancelado\n"
        else:
            updated += " @cancelado"
    if updated == current:
        return False
    lines[index] = updated
    return _guardar(path, "".join(lines), checar="", raiz=root)


def _split_snooze(body):
    text = " ".join((body or "").split())
    match = SNOOZE_TAIL_RE.match(text)
    if not match:
        return text, None
    subject = (match.group("subject") or "").strip(" \t.?!,")
    spec = {
        "day": match.group("day"),
        "time": match.group("time") or match.group("timeonly"),
        "amount": match.group("amount"),
        "unit": fold(match.group("unit") or ""),
    }
    if not any(spec.values()):
        return text, None
    return subject, spec


def _snooze_when(spec, now, original):
    if spec is None:
        base = original if original > now else now
        return base + timedelta(hours=1)
    if spec.get("amount"):
        amount = _amount(spec["amount"])
        if amount <= 0:
            raise ValueError("horario")
        if spec.get("unit", "").startswith("minuto"):
            return now + timedelta(minutes=amount)
        return now + timedelta(hours=amount)
    hour = original.hour
    minute = original.minute
    if spec.get("time"):
        hour, minute = _clock(spec["time"])
    if spec.get("day"):
        return _shift_day(spec["day"], now, hour, minute)
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if when <= now:
        when = when + timedelta(days=1)
    return when


def _shift_day(day_text, now, hour, minute):
    folded = fold(day_text)
    if folded == "hoje":
        target = now.date()
    elif folded == "amanha":
        target = now.date() + timedelta(days=1)
    elif folded == "depois de amanha":
        target = now.date() + timedelta(days=2)
    elif folded.startswith("dia "):
        target = _day_of_month(folded, now, hour, minute)
    else:
        target = _next_weekday(folded, now, hour, minute)
    when = datetime(target.year, target.month, target.day, hour, minute, tzinfo=now.tzinfo)
    if when <= now:
        raise ValueError("passado")
    return when


def _amount(raw):
    folded = fold(raw)
    words = {"um": 1, "uma": 1, "dois": 2, "duas": 2}
    if folded in words:
        return words[folded]
    return int(raw)


def _match_reminders(root, query):
    items = _open_reminders(root)
    text = " ".join((query or "").split())
    if not text:
        return items
    tokens = [token for token in fold(text).split() if len(token) >= 2]
    if not tokens:
        return items
    folded_query = fold(text)
    hits = []
    for item in items:
        folded = fold(item["text"])
        if folded_query == folded or all(token in folded for token in tokens):
            hits.append(item)
    return hits


def _open_reminders(root):
    places = load_places(root)
    found = []
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        try:
            relative = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            continue
        for index, line in linhas_de_caixa(path):
            match = TASK_RE.match(line)
            if not match or match.group("mark").lower() == "x":
                continue
            if "@cancelado" in match.group("tail"):
                continue
            try:
                when = datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            found.append(
                {
                    "relative": relative,
                    "text": match.group("body").strip(),
                    "line": index,
                    "when": when.replace(tzinfo=places.tz),
                    "repeat": _repeat_token(line),
                }
            )
    found.sort(key=lambda item: item["when"])
    return found


def _find_reminder_line(lines, text, line_index):
    folded = fold(text)
    if not folded:
        return None
    if line_index is not None:
        try:
            index = int(line_index)
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < len(lines) and _line_is_open_reminder(lines[index], folded):
            return index
    for index, line in enumerate(lines):
        if _line_is_open_reminder(line, folded):
            return index
    return None


def _line_is_open_reminder(line, folded_text):
    match = TASK_RE.match(line.strip("\n"))
    if not match or match.group("mark").lower() == "x":
        return False
    if "@cancelado" in match.group("tail"):
        return False
    return fold(match.group("body").strip()) == folded_text


def _note_file(root, relative):
    from .paths import windows_drive

    text = (relative or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or windows_drive(text) or ".." in text.split("/"):
        return None
    root = Path(root).resolve()
    path = (root / text).resolve()
    if not _inside(path, root) or not path.is_file():
        return None
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if any(part == ".obsidian" or part.startswith(".") for part in parts):
        return None
    return path


def _week_items(root, moment, monday, sunday):
    notes = []
    done = []
    pending = []
    seen_notes = set()
    seen_done = set()
    seen_pending = set()
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        if path.name.casefold() in ROOT_NAMES:
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, moment.tzinfo).date()
        except OSError:
            modified = None
        if modified is not None and monday <= modified <= sunday:
            title = _title(path, _read(path))
            key = fold(title)
            if key not in seen_notes:
                seen_notes.add(key)
                notes.append(title)
        for _index, line in linhas_de_caixa(path):
            match = re.match(r"^\s*- \[(?P<mark>[ xX])\] (?P<body>.+)$", line)
            if not match:
                continue
            raw = match.group("body")
            body = re.sub(r"\s@\s+\d{4}-\d{2}-\d{2}.*$", "", raw).strip()
            body = re.sub(r"\s@avisado$", "", body).strip()
            if not body:
                continue
            stamp = re.search(r"@ (\d{4}-\d{2}-\d{2})", raw)
            in_week = False
            if stamp:
                try:
                    day = datetime.strptime(stamp.group(1), "%Y-%m-%d").date()
                except ValueError:
                    day = None
                in_week = day is not None and monday <= day <= sunday
            elif modified is not None and monday <= modified <= sunday:
                in_week = True
            if not in_week:
                continue
            key = fold(body)
            if match.group("mark").lower() == "x":
                if key not in seen_done:
                    seen_done.add(key)
                    done.append(body)
            elif key not in seen_pending:
                seen_pending.add(key)
                pending.append(body)
    return notes, done, pending


def _week_speech(monday, sunday, notes, done, pending):
    parts = [f"Senhor, na semana de {_span(monday, sunday)}."]
    parts.append(_list_speech("Notas", notes))
    parts.append(_list_speech("Tarefas feitas", done))
    parts.append(_list_speech("Pendências", pending))
    return " ".join(parts)


def _list_speech(label, items):
    if not items:
        return f"{label}: nada a registrar."
    shown = items[:3]
    extra = len(items) - len(shown)
    text = _join_pt(shown)
    if extra:
        text += f", e mais {extra}"
    return f"{label}: {text}."


def _week_body(monday, sunday, notes, done, pending):
    lines = [f"# Semana de {monday.isoformat()} a {sunday.isoformat()}", ""]
    lines.extend(_section("Notas", notes, "Nenhuma nota alterada nesta semana."))
    lines.extend(_section("Feitas", done, "Nenhuma tarefa concluída nesta semana."))
    lines.extend(_section("Pendentes", pending, "Nenhuma pendência nesta semana."))
    return "\n".join(lines).rstrip() + "\n"


def _section(title, items, empty):
    lines = [f"## {title}"]
    if items:
        lines.extend(f"- {item}" for item in items[:20])
    else:
        lines.append(f"- {empty}")
    lines.append("")
    return lines


def _span(monday, sunday):
    if monday.month == sunday.month and monday.year == sunday.year:
        return f"{monday.day} a {sunday.day} de {MONTHS[monday.month - 1]}"
    return (
        f"{monday.day} de {MONTHS[monday.month - 1]} a "
        f"{sunday.day} de {MONTHS[sunday.month - 1]}"
    )


def _open_tasks(root, query):
    tokens = [token for token in fold(query).split() if len(token) >= 2]
    if not tokens:
        return []
    hits = []
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        try:
            relative = Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            continue
        for _index, line in linhas_de_caixa(path):
            match = OPEN_TASK_RE.match(line)
            if not match:
                continue
            body = re.sub(r"\s@\s+\d{4}-\d{2}-\d{2}.*$", "", match.group(1)).strip()
            folded = fold(body)
            if not folded:
                continue
            if fold(query) == folded or all(token in folded for token in tokens):
                hits.append({"relative": relative, "text": body})
    return hits


def parse_reminder(message, now):
    text = normalize_phrase(message)
    recurring = RECURRING_HEAD_RE.match(text) or RECURRING_TAIL_RE.match(text)
    if recurring:
        return _parse_recurring(recurring, now)
    match = REMINDER_RE.match(text)
    if not match:
        return None
    places_tz = now.tzinfo
    moment = now
    body = match.group("body").strip(" \t.?!")
    if not body:
        return None, "", "Não entendi o assunto do lembrete, senhor.", ""
    try:
        when = _resolve_when(match.group("day"), match.group("time"), moment, places_tz)
    except ValueError as error:
        if str(error) == "passado":
            return None, "", "Esse horário já passou, senhor.", ""
        return None, "", "Não entendi o horário, senhor.", ""
    return when, body, "", ""


def _parse_recurring(match, now):
    body = match.group("body").strip(" \t.?!")
    body = re.sub(r"(?i)^de\s+", "", body).strip(" \t.?!")
    repeat = _repeat_code(match.group("repeat"))
    if not body or not repeat:
        return None, "", "Não entendi o assunto do lembrete, senhor.", ""
    try:
        when = _first_when(repeat, match.group("time"), now)
    except ValueError:
        return None, "", "Não entendi o horário, senhor.", ""
    return when, body, "", repeat


def _late_reason(when, moment):
    days = (moment.date() - when.date()).days
    if 1 <= days <= 6:
        name = WEEKDAYS[when.weekday()]
        short = name.split("-", 1)[0]
        return f"está atrasado desde {short}"
    return f"está atrasado desde {when.day} de {MONTHS[when.month - 1]}"


def _clock_reason(when, moment):
    clock = str(when.hour) if when.minute == 0 else f"{when.hour}:{when.minute:02d}"
    if when.date() < moment.date():
        return _late_reason(when, moment)
    if when <= moment:
        return "o horário de hoje já passou"
    return f"está marcado para as {clock}"


def focus_speech(root, now, jira_loader=None, github_loader=None):
    moment = now
    places = None
    if root:
        root = Path(root)
        places = load_places(root)
        moment = _aware(now, places)
    items = []
    seen = set()
    order = 0

    def add(band, when_key, label, reason, identity=None):
        nonlocal order
        text = " ".join(
            str(label or "").replace("\u2014", " ").replace("\u2013", " ").split()
        )
        because = " ".join(
            str(reason or "").replace("\u2014", " ").replace("\u2013", " ").split()
        )
        if not text:
            return
        if not because:
            because = "entra no foco de hoje"
        key = fold(identity if identity is not None else text)
        if not key or key in seen:
            return
        seen.add(key)
        items.append((band, when_key, order, text[:180], because))
        order += 1

    if root and places:
        open_items = _open_reminders(root)
        today_names = {
            fold(item["text"])
            for item in open_items
            if item["when"].date() == moment.date()
        }
        for item in open_items:
            if item["when"].date() < moment.date():
                add(
                    0,
                    item["when"].timestamp(),
                    f"lembrete atrasado: {item['text']}",
                    _late_reason(item["when"], moment),
                )
        for appt in day_plan(root, places, moment.date()):
            kind = "lembrete" if fold(appt.text) in today_names else "agenda"
            if appt.timed and appt.when is not None:
                clock = (
                    str(appt.when.hour)
                    if appt.when.minute == 0
                    else f"{appt.when.hour}:{appt.when.minute:02d}"
                )
                label = f"{kind} às {clock}: {appt.text}"
                if appt.when.date() < moment.date():
                    band = 0
                elif appt.when <= moment:
                    band = 1
                else:
                    band = 4
                add(band, appt.when.timestamp(), label, _clock_reason(appt.when, moment))
            else:
                add(6, 0, f"agenda: {appt.text}", "está na agenda de hoje")

    jira_note = ""
    github_note = ""
    jira = (jira_loader or _focus_jira)()
    if jira is False:
        jira_note = " Não consegui consultar o Jira."
    elif jira:
        for index, issue in enumerate(jira):
            label = issue.get("label") or ""
            bucket = issue.get("bucket")
            if bucket == "progress":
                add(3, index, f"no Jira em andamento: {label}", "está em andamento", identity=label)
            elif bucket == "todo":
                add(8, index, f"no Jira a fazer: {label}", "está a fazer", identity=label)
            else:
                add(8, index, f"no Jira: {label}", "está no Jira", identity=label)
    github = (github_loader or _focus_github)()
    if github is False:
        github_note = " Não consegui consultar os PRs."
    elif github:
        for index, label in enumerate(github.get("reviews") or []):
            add(2, index, f"review pendente: {label}", "há review pedido", identity=label)
        for index, label in enumerate(github.get("opened") or []):
            add(7, index, f"PR aberto: {label}", "o pull request está aberto", identity=label)

    foco = _foco_semanal(moment)
    if foco:
        add(5, 0, foco, "você escolheu na revisão semanal", identity="foco-semana")

    items.sort(key=lambda item: (item[0], item[1], item[2]))
    top = [f"{item[3]}, {item[4]}" for item in items[:3]]
    extra = len(items) - len(top)
    if not top:
        body = "Não há prioridade marcada para hoje, senhor."
    elif len(top) == 1:
        body = f"A prioridade de hoje, senhor, é {top[0]}."
    elif len(top) == 2:
        body = (
            "Duas prioridades hoje, senhor. "
            f"Primeira, {top[0]}. Segunda, {top[1]}."
        )
    else:
        body = (
            "Três prioridades hoje, senhor. "
            f"Primeira, {top[0]}. Segunda, {top[1]}. Terceira, {top[2]}."
        )
    if extra and len(top) == 3:
        body += " Há mais além dessas três."
    if foco and foco not in body:
        body += " O foco da semana, que você escolheu na revisão semanal, é " + foco + "."
    if root is None:
        body = "Sem o vault eu não li lembretes nem agenda, senhor. " + body
    return (body + jira_note + github_note).strip()


def _foco_semanal(moment):
    try:
        from .reflexao import foco_da_semana

        return foco_da_semana(moment)
    except Exception:
        return ""


def _focus_jira():
    from .external import jira_issues

    return jira_issues(limit=5)


def _focus_github():
    from .external import github_pulls

    return github_pulls(limit=5)


def briefing_speech(root, places, now):
    moment = _aware(now, places)
    pending = _pending_lines(root, places, moment)
    recent = _recent_titles(root, places, moment)
    plan = day_plan(root, places, moment.date())
    parts = [f"Bom dia, senhor. Hoje é {_spoken_date(moment)}."]
    parts.append(_focus_line(root, moment))
    parts.append(_cards_line(root, moment))
    if plan:
        parts.append("Agenda de hoje: " + _plan_speech(plan) + ".")
    else:
        parts.append("Não há compromisso marcado para hoje.")
    if pending:
        parts.append("Pendências: " + _join_pt(pending[:4]) + ".")
    else:
        parts.append("Não há pendência aberta na agenda profissional.")
    if recent:
        parts.append("Notas recentes: " + _join_pt(recent[:3]) + ".")
    for extra in _briefing_sources():
        if extra:
            parts.append(extra)
    return " ".join(parts)


def _focus_line(root, moment):
    try:
        return focus_speech(root, moment)
    except Exception:
        return "Não consegui montar o foco de hoje."


def _cards_line(root, moment):
    try:
        from .review import cards_due_line

        return cards_due_line(root, moment)
    except Exception:
        return "Não consegui contar os cartões de hoje."


def _briefing_sources():
    found = []
    for loader in (jira_briefing, github_briefing, mail_briefing):
        try:
            extra = loader()
        except Exception:
            extra = "Não consegui consultar uma fonte externa."
        if extra:
            found.append(extra)
    return found


def agenda_speech(root, places, now, day_key):
    moment = _aware(now, places)
    key = fold(day_key or "hoje")
    if key == "amanha":
        day = moment.date() + timedelta(days=1)
        title = "Amanhã"
        empty = "amanhã"
    elif key == "depois de amanha":
        day = moment.date() + timedelta(days=2)
        title = "Depois de amanhã"
        empty = "depois de amanhã"
    else:
        day = moment.date()
        title = "Hoje"
        empty = "hoje"
    spoken = _spoken_date(datetime(day.year, day.month, day.day, tzinfo=moment.tzinfo))
    items = day_plan(root, places, day)
    if not items:
        return f"Não há compromisso {empty}, senhor. {spoken}."
    return f"{title}, {spoken}. {_plan_speech(items)}."


def day_plan(root, places, day):
    items = []
    seen_paths = set()
    agenda = agenda_path(root, places)
    if agenda is not None and agenda.exists():
        files = [agenda] if agenda.is_file() else list(iter_notes(agenda))
        for path in files:
            seen_paths.add(Path(path).resolve())
            items.extend(_appointments_in(path, day, places, allow_untimed=True))
    daily = daily_note_path(root, places, day)
    if daily.is_file():
        try:
            same = daily.resolve() in seen_paths
        except OSError:
            same = False
        if not same:
            items.extend(
                _appointments_in(daily, day, places, allow_untimed=False, hora_solta=False)
            )
    for item in _open_reminders(root):
        if item["when"].date() == day:
            items.append(_Appt(item["when"], item["text"], True))
    return _dedupe_appointments(items)


class _Appt:
    def __init__(self, when, text, timed):
        self.when = when
        self.text = text
        self.timed = timed


def _appointments_in(path, day, places, allow_untimed, hora_solta=True):
    text = _read(path)
    meta, body = _split_meta(text)
    note_day = _note_day(path, meta)
    if note_day is not None and note_day != day:
        return []
    scoped = note_day == day
    timed = []
    dated = []
    for line in body.splitlines():
        item = _line_appointment(line, day, places, scoped and hora_solta)
        if item is None:
            continue
        if item.timed:
            timed.append(item)
        else:
            dated.append(item)
    found = []
    clock = _meta_clock(meta)
    title = _title(path, text)
    if scoped and clock is not None and title and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", title):
        if not timed:
            when = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=places.tz)
            found.append(_Appt(when, title, True))
    found.extend(timed)
    found.extend(dated)
    if scoped and allow_untimed:
        for line in body.splitlines():
            if _line_appointment(line, day, places, True) is not None:
                continue
            task = OPEN_TASK_RE.match(line)
            bullet = BULLET_RE.match(line)
            raw = task.group(1) if task else bullet.group(1) if bullet else ""
            body_text = re.sub(r"\s@\s+\d{4}-\d{2}-\d{2}.*$", "", raw).strip()
            if body_text:
                found.append(_Appt(None, body_text, False))
    return found


def _line_appointment(line, day, places, scoped):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or re.match(r"^-\s+\[[xX]\]", stripped):
        return None
    task = TASK_RE.match(stripped)
    if task:
        if task.group("mark").lower() == "x":
            return None
        try:
            when = datetime.strptime(task.group("stamp"), "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        if when.date() != day:
            return None
        return _Appt(when.replace(tzinfo=places.tz), task.group("body").strip(), True)
    iso = re.match(
        r"^(?:[-*]\s+)?(?:\[[ ]\]\s+)?"
        r"(?P<date>\d{4}-\d{2}-\d{2})"
        r"(?:\s+(?P<clock>\d{1,2}(?::\d{2}|h\d{0,2})))?"
        r"\s+(?P<body>.+)$",
        stripped,
    )
    if iso:
        try:
            stamp = datetime.strptime(iso.group("date"), "%Y-%m-%d").date()
        except ValueError:
            stamp = None
        if stamp != day:
            return None
        text = iso.group("body").strip()
        if not text:
            return None
        clock = _parse_clock_token(iso.group("clock")) if iso.group("clock") else None
        if clock is None:
            return _Appt(None, text, False)
        when = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=places.tz)
        return _Appt(when, text, True)
    if not scoped:
        return None
    timed = re.match(
        r"^(?:[-*]\s+)?(?:\[[ ]\]\s+)?"
        r"(?P<clock>\d{1,2}(?::\d{2}|h\d{0,2}))\s+(?P<body>.+)$",
        stripped,
    )
    if not timed:
        return None
    clock = _parse_clock_token(timed.group("clock"))
    text = timed.group("body").strip()
    if clock is None or not text:
        return None
    when = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=places.tz)
    return _Appt(when, text, True)


def _note_day(path, meta):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", Path(path).stem):
        try:
            return datetime.strptime(Path(path).stem, "%Y-%m-%d").date()
        except ValueError:
            return None
    for key in ("data", "date", "dia"):
        raw = meta.get(key) or ""
        match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(0), "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


def _meta_clock(meta):
    for key in ("hora", "horario"):
        clock = _parse_clock_token(meta.get(key) or "")
        if clock is not None:
            return clock
    return None


def _parse_clock_token(token):
    match = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2})|h(\d{0,2}))\s*", token or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or match.group(3) or 0)
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _split_meta(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[fold(key.strip())] = value.strip().strip("'\"")
    return meta, text[end + 4 :]


def _dedupe_appointments(items):
    unique = []
    seen = set()
    for item in items:
        stamp = item.when.strftime("%H:%M") if item.when is not None else ""
        key = (stamp, fold(item.text))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        unique.append(item)

    def sort_key(item):
        if item.when is None:
            return (1, 99, 99, fold(item.text))
        return (0, item.when.hour, item.when.minute, fold(item.text))

    unique.sort(key=sort_key)
    return unique


def _plan_speech(items):
    shown = list(items[:6])
    parts = []
    for item in shown:
        if item.timed and item.when is not None:
            clock = (
                str(item.when.hour)
                if item.when.minute == 0
                else f"{item.when.hour}:{item.when.minute:02d}"
            )
            parts.append(f"às {clock}, {item.text}")
        else:
            parts.append(item.text)
    text = _join_pt(parts)
    extra = len(items) - len(shown)
    if extra:
        text += f", e mais {extra}"
    if text:
        text = text[0].upper() + text[1:]
    return text


def search_speech(root, query):
    from .semantica import hits_da_busca, modo

    aviso = ""
    if modo() == "palavras":
        hits = hybrid_notes(root, query, embedder=_search_embedder())
    else:
        hits, aviso = hits_da_busca(root, query, modo())
        if aviso and not hits:
            return aviso
    if not hits:
        from .busca import parse_scope

        cleaned, _folder = parse_scope(query)
        subject = cleaned or query or "isso"
        return f"Não encontrei nas notas nada sobre {subject}, senhor."
    bits = []
    for hit in hits[:3]:
        where = hit.relative or hit.title
        bits.append(f"Na nota {hit.title}, caminho {where}: {hit.snippet}.")
    fala = "Encontrei isto, senhor. " + " ".join(bits)
    if aviso:
        return aviso + " " + fala
    return fala


def _search_embedder():
    try:
        from .consult import default_embedder
    except Exception:
        return None
    try:
        return default_embedder()
    except Exception:
        return None


def hybrid_notes(root, query, embedder=None, limit=5):
    from .busca import (
        bm25_ranking,
        bm25_tokens,
        dense_cosine,
        exact_do_texto,
        exact_support,
        fuse_rrf,
        line_bonus,
        line_bonus_pronta,
        model_is_usable,
        needed_count,
        parse_scope,
        spelling_ranking,
    )

    cleaned, folder = parse_scope(query)
    tokens = _query_tokens(cleaned)
    words = [token for token in tokens if len(token) >= 3] or list(tokens)
    if not words:
        return []
    docs, prontos = _docs_do_catalogo(root, folder)
    if not docs:
        return []

    need = needed_count(len(words))
    eligible = []
    tokenized = []
    for item, pronto in zip(docs, prontos):
        if pronto is None:
            blob = item[3] + "\n" + item[1]
            if exact_support(words, blob) < need:
                continue
        elif exact_do_texto(words, pronto.dobrado) < need:
            continue
        eligible.append((item, pronto))
        if pronto is None:
            tokenized.append(None)
        else:
            tokenized.append(pronto.tokens)
    bm25_items = []
    if eligible:
        if any(item is None for item in tokenized):
            blobs = [par[0][3] + "\n" + par[0][1] for par in eligible]
            scores = bm25_ranking(blobs, words)
        else:
            scores = bm25_tokens(tokenized, words)
        for (item, pronto), score in zip(eligible, scores):
            if pronto is None:
                blob = item[3] + "\n" + item[1]
                total = score + line_bonus(blob, words)
            else:
                total = score + line_bonus_pronta(pronto.linhas, pronto.dobrado, words)
            if total <= 0:
                continue
            bm25_items.append((total, item))
        bm25_items.sort(key=lambda pair: (-pair[0], pair[1][2]))

    try:
        from .indice import boosted_docs

        boosted = boosted_docs(root, docs, cleaned)
    except Exception:
        boosted = []
    if boosted:
        bm25_items = _apply_index_boost(bm25_items, boosted)

    model_items = []
    if embedder is not None and len(docs) <= 400:
        model_items = _embed_notes(
            embedder, docs, cleaned, dense_cosine, model_is_usable, root
        )

    spell_items = []
    if not model_items:
        known = {item[2] for _score, item in bm25_items}
        pular = {index for index, item in enumerate(docs) if item[2] in known}
        if len(pular) == len(docs):
            order = []
        elif any(item is None for item in prontos):
            order = spelling_ranking(
                [item[3] + "\n" + item[1] for item in docs],
                words,
                caches=prontos,
                pular=pular,
            )
        else:
            order = spelling_ranking(docs, words, caches=prontos, pular=pular)
        for score, index in order:
            item = docs[index]
            if item[2] in known:
                continue
            spell_items.append((score, item))

    rankings = []
    if bm25_items:
        rankings.append([item for _score, item in bm25_items])
    if spell_items:
        rankings.append([item for _score, item in spell_items])
    if model_items:
        rankings.append([item for _score, item in model_items])
    if not rankings:
        return []
    fused = fuse_rrf(rankings, key=lambda item: item[2])
    hits = []
    for _score, item in fused[:limit]:
        path, text, relative, title = item
        hits.append(Hit(path, title, _snippet(text, words), relative))
    return hits


def _apply_index_boost(bm25_items, boosted):
    weight = {}
    total = len(boosted)
    for index, item in enumerate(boosted):
        weight[item[2]] = 8.0 + (total - index) * 0.01
    found = {item[2] for _score, item in bm25_items}
    adjusted = []
    for score, item in bm25_items:
        adjusted.append((score + weight.get(item[2], 0.0), item))
    for item in boosted:
        if item[2] not in found:
            adjusted.append((weight[item[2]], item))
    adjusted.sort(key=lambda pair: (-pair[0], pair[1][2]))
    return adjusted


def _embed_notes(embedder, docs, query, cosine, usable, root=None):
    texts = [item[3] + "\n" + item[1] for item in docs]
    records = []
    for item, blob in zip(docs, texts):
        try:
            stat = item[0].stat()
            mtime = stat.st_mtime_ns
            size = stat.st_size
        except OSError:
            mtime = 0
            size = len(blob)
        records.append(
            {
                "relative": item[2],
                "mtime_ns": mtime,
                "tamanho": size,
                "texto": blob,
            }
        )
    from .indice_vetor import cache_file, vectors_for

    store = None
    if root is not None and type(embedder).__name__ == "LocalModel":
        store = cache_file(root, embedder)
    rows = vectors_for(records, embedder, store)
    if rows is None:
        try:
            rows = list(embedder.embed(texts) or [])
        except Exception:
            return []
    try:
        query_rows = list(embedder.embed([query]) or [])
    except Exception:
        return []
    if not rows or not query_rows or len(rows) != len(docs):
        return []
    scored = []
    for item, row in zip(docs, rows):
        values = [float(value) for value in list(row)]
        scored.append((cosine(query_rows[0], values), item))
    scored.sort(key=lambda pair: (-pair[0], pair[1][2]))
    if not usable([score for score, _item in scored]):
        return []
    return [pair for pair in scored if pair[0] >= 0.55]


def search_notes(root, query):
    tokens = _query_tokens(query)
    if not tokens:
        return []
    phrase = " ".join(tokens)
    ranked = []
    root = Path(root)
    for path, text, relative, title in _docs_do_catalogo(root, "")[0]:
        if not _expor_nota(root, relative, text):
            continue
        hay_title = fold(title + " " + path.stem)
        hay_body = fold(text)
        if any(token not in hay_title and token not in hay_body for token in tokens):
            continue
        score = _search_score(tokens, phrase, hay_title, text)
        snippet = _snippet(text, tokens)
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0
        ranked.append((score, modified, Hit(path, title, snippet, relative)))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:5]]


def _docs_do_catalogo(root, folder):
    from .busca import in_scope
    from .catalogo import obter

    docs = []
    prontos = []
    raiz = Path(root)
    try:
        catalogo = obter(raiz)
    except Exception:
        return [], []
    for nota in catalogo.notas.values():
        if not nota.util or nota.texto is None:
            continue
        if not in_scope(nota.relative, folder):
            continue
        if not _expor_nota(raiz, nota.relative, nota.texto, sigilosa=nota.sigilosa):
            continue
        docs.append((nota.path, nota.texto, nota.relative, nota.titulo))
        prontos.append(nota.preparo)
    return docs, prontos


def _expor_nota(root, path, text, sigilosa=None):
    try:
        from .privacidade import _LOCAIS, _pasta_casa, destino_atual, pode_enviar
    except Exception:
        return True
    try:
        if sigilosa is not None:
            relativo = str(path or "").replace("\\", "/")
            if sigilosa or _pasta_casa(relativo):
                return destino_atual() in _LOCAIS
            return True
        return pode_enviar(root, path, destino_atual(), text)
    except Exception:
        return True


def _query_tokens(query):
    raw = [token for token in fold(query).split() if len(token) >= 2]
    useful = [token for token in raw if token not in SEARCH_STOP]
    return useful or raw


def _search_score(tokens, phrase, hay_title, text):
    title_hits = sum(1 for token in tokens if token in hay_title)
    body = _without_frontmatter(text)
    folded_body = fold(body)
    best = 0
    total = 0
    for line in body.splitlines():
        folded = fold(line)
        present = sum(1 for token in tokens if token in folded)
        total += present
        if present > best:
            best = present
    score = 1 + title_hits * 5 + best * 4 + min(total, 20)
    if phrase and phrase in folded_body:
        score += 8
    if phrase and phrase in hay_title:
        score += 6
    return score


def _relative_note(root, path):
    try:
        relative = Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return Path(path).name
    text = relative.as_posix()
    if not text or text.startswith(".") or "/." in text:
        return Path(path).name
    return text


def list_due(root, now):
    places = load_places(root)
    moment = _aware(now, places)
    found = []
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        for index, line in linhas_de_caixa(path):
            match = TASK_RE.match(line)
            if not match or match.group("mark").lower() == "x":
                continue
            if "@avisado" in match.group("tail"):
                continue
            try:
                when = datetime.strptime(match.group("stamp"), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            when = when.replace(tzinfo=places.tz)
            if when <= moment:
                found.append(
                    DueReminder(path, index, match.group("body").strip(), when)
                )
    found.sort(key=lambda item: item.when)
    return found


def mark_reminded(items, now=None, raiz=None):
    by_path = {}
    for item in items:
        by_path.setdefault(item.path, []).append(item)
    marked = []
    for path, group in by_path.items():
        lines = _read(path).splitlines(keepends=True)
        changed = False
        pending = []
        for item in group:
            if item.line_index >= len(lines):
                continue
            current = lines[item.line_index].rstrip("\n")
            stamp = f"@ {item.when.strftime('%Y-%m-%d %H:%M')}"
            if "@avisado" in current or stamp not in current:
                continue
            newline = "\n" if lines[item.line_index].endswith("\n") else ""
            repeat = _repeat_token(current)
            if repeat:
                nxt = next_occurrence(item.when, repeat, _moment_for(item.when, now))
                if nxt is None:
                    updated = current + " @avisado"
                else:
                    updated = current.replace(
                        stamp, f"@ {nxt.strftime('%Y-%m-%d %H:%M')}", 1
                    )
            else:
                updated = current + " @avisado"
            lines[item.line_index] = updated + newline
            changed = True
            pending.append(item)
        if changed and _guardar(path, "".join(lines), checar="", raiz=raiz):
            marked.extend(pending)
    return marked


def alert_speech(items):
    shown = list(items[:5])
    extra = len(items) - len(shown)
    if len(shown) == 1 and extra == 0:
        return f"Senhor, lembrete: {shown[0].text}."
    body = "; ".join(item.text for item in shown)
    if extra:
        body += f"; e mais {extra}"
    return f"Senhor, lembretes: {body}."


def iter_notes(root):
    from .leitura import iter_markdown

    yield from iter_markdown(root)


def linhas_de_caixa(path):
    chave = str(path)
    try:
        marca = Path(path).stat()
    except OSError:
        _CAIXAS.pop(chave, None)
        return ()
    anterior = _CAIXAS.get(chave)
    recente = time.time_ns() - marca.st_mtime_ns < JANELA_RECENTE_NS
    if (
        anterior is not None
        and not recente
        and anterior[0] == marca.st_mtime_ns
        and anterior[1] == marca.st_size
    ):
        return anterior[2]
    linhas = tuple(
        (index, line)
        for index, line in enumerate(_read(path).splitlines())
        if CAIXA_RE.match(line)
    )
    if recente:
        _CAIXAS.pop(chave, None)
        return linhas
    if len(_CAIXAS) >= _TETO_CAIXAS:
        _CAIXAS.clear()
    _CAIXAS[chave] = (marca.st_mtime_ns, marca.st_size, linhas)
    return linhas


def limpar_caixas():
    _CAIXAS.clear()


def _inside_vault(root_resolved, path):
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.is_file():
        return False
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def _append_line(root, places, path, moment, line):
    if caminho_bloqueado(path):
        raise GuardError("escrita bloqueada")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        current = _read(path)
        if current and not current.endswith("\n"):
            current += "\n"
        if not _guardar(path, current + "\n" + line, checar=line, raiz=root):
            raise GuardError("escrita bloqueada")
        return
    body = _new_note_body(root, places, path, moment)
    if body and not body.endswith("\n"):
        body += "\n"
    if not _guardar(path, body + "\n" + line, checar=line, raiz=root):
        raise GuardError("escrita bloqueada")


def _new_note_body(root, places, path, moment):
    template = _daily_template(root)
    if template and path == daily_note_path(root, places, moment.date()):
        text = _read(template)
        stamp = moment.strftime("%Y-%m-%d")
        clock = moment.strftime("%H:%M")
        text = text.replace("{{date:YYYY-MM-DD}}", stamp)
        text = text.replace("{{date}}", stamp)
        text = text.replace("{{time}}", clock)
        text = text.replace("{{title}}", stamp)
        return text
    return f"# {moment.strftime('%Y-%m-%d')}\n"


def _pending_lines(root, places, moment):
    texts = []
    agenda = agenda_path(root, places)
    if agenda is not None:
        texts.extend(_note_items(agenda))
    today = daily_note_path(root, places, moment.date())
    if today.is_file() and (agenda is None or today.resolve() != agenda.resolve()):
        texts.extend(_note_items(today))
    for item in list_due(root, moment):
        if item.when.date() <= moment.date():
            texts.append(item.text)
    unique = []
    seen = set()
    for text in texts:
        cleaned = _plain(text)
        if not cleaned:
            continue
        key = fold(cleaned)
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


def _note_items(path):
    path = Path(path)
    files = []
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = list(iter_notes(path))
    tasks = []
    bullets = []
    for file in files:
        for line in _read(file).splitlines():
            task = OPEN_TASK_RE.match(line)
            if task:
                tasks.append(re.sub(r"\s@\s+\d{4}-\d{2}-\d{2}.*$", "", task.group(1)))
                continue
            bullet = BULLET_RE.match(line)
            if bullet:
                bullets.append(bullet.group(1))
    return tasks or bullets[:5]


def _recent_titles(root, places, moment):
    cutoff = moment - timedelta(days=3)
    agenda = agenda_path(root, places)
    today = daily_note_path(root, places, moment.date())
    ranked = []
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        if path.name.casefold() in ROOT_NAMES:
            continue
        if agenda is not None and _same(path, agenda):
            continue
        if _same(path, today):
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, places.tz)
        except OSError:
            continue
        if modified < cutoff:
            continue
        ranked.append((modified, _title(path, _read(path))))
    ranked.sort(key=lambda item: item[0], reverse=True)
    titles = []
    used = set()
    for _modified, title in ranked:
        key = fold(title)
        if key in used:
            continue
        used.add(key)
        titles.append(title)
    return titles


REPEAT_SPEECH = {
    "dia": "todo dia",
    "uteis": "nos dias úteis",
    "segunda": "toda segunda",
    "terca": "toda terça",
    "quarta": "toda quarta",
    "quinta": "toda quinta",
    "sexta": "toda sexta",
    "sabado": "todo sábado",
    "domingo": "todo domingo",
}
WEEKDAY_CODE = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}


def _repeat_code(phrase):
    folded = fold(phrase)
    if "util" in folded or "utei" in folded:
        return "uteis"
    for name in WEEKDAY_CODE:
        if name in folded:
            return name
    if "dia" in folded:
        return "dia"
    return ""


def _repeat_token(line):
    match = re.search(r"@repete\s+([a-z]+)", line or "")
    if not match:
        return ""
    code = match.group(1)
    if code in REPEAT_SPEECH:
        return code
    return ""


def _moment_for(when, now):
    if now is None:
        return when
    if now.tzinfo is None:
        return now.replace(tzinfo=when.tzinfo)
    if when.tzinfo is None:
        return now.replace(tzinfo=None)
    return now.astimezone(when.tzinfo)


def _first_when(repeat, time_text, now):
    hour, minute = _clock(time_text)
    previous = datetime(
        now.year, now.month, now.day, hour, minute, tzinfo=now.tzinfo
    ) - timedelta(days=1)
    found = next_occurrence(previous, repeat, now, inclusive=True)
    if found is None:
        raise ValueError("horario")
    return found


def next_occurrence(when, repeat, now, inclusive=False):
    moment = _moment_for(when, now)
    hour = when.hour
    minute = when.minute
    tz = when.tzinfo

    def at(day):
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)

    def accepts(day):
        if repeat == "dia":
            return True
        if repeat == "uteis":
            return day.weekday() < 5
        target = WEEKDAY_CODE.get(repeat)
        return target is not None and day.weekday() == target

    day = moment.date()
    for _step in range(400):
        candidate = at(day)
        due = candidate >= moment if inclusive else candidate > moment
        if due and candidate > when and accepts(day):
            return candidate
        day += timedelta(days=1)
    return None


def _resolve_when(day_text, time_text, now, tz):
    hour, minute = _clock(time_text)
    folded = fold(day_text)
    if folded == "hoje":
        target = now.date()
    elif folded == "amanha":
        target = now.date() + timedelta(days=1)
    elif folded == "depois de amanha":
        target = now.date() + timedelta(days=2)
    elif folded.startswith("dia "):
        target = _day_of_month(folded, now, hour, minute)
    else:
        target = _next_weekday(folded, now, hour, minute)
    when = datetime(target.year, target.month, target.day, hour, minute, tzinfo=tz)
    if folded == "hoje" and when <= now:
        raise ValueError("passado")
    return when


def _clock(time_text):
    if not time_text:
        return 9, 0
    match = re.search(
        r"(?i)(\d{1,2})(?:h|:)?(\d{2})?(?:\s+da\s+(manh[ãa]|tarde|noite))?",
        time_text,
    )
    if not match:
        raise ValueError("horario")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = fold(match.group(3) or "")
    if period == "manha":
        if hour == 12:
            hour = 0
    elif period == "tarde" and hour < 12:
        hour += 12
    elif period == "noite":
        if hour == 12:
            hour = 0
        elif hour < 12:
            hour += 12
    if hour > 23 or minute > 59:
        raise ValueError("horario")
    return hour, minute


def _day_of_month(folded, now, hour, minute):
    match = re.search(r"dia\s+(\d{1,2})(?:\s+de\s+([a-z]+))?", folded)
    if not match:
        raise ValueError("data")
    day = int(match.group(1))
    month_name = match.group(2)
    if month_name:
        month = MONTH_INDEX.get(month_name)
        if not month or day < 1 or day > calendar.monthrange(now.year, month)[1]:
            raise ValueError("data")
        year = now.year
        candidate = datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
        if candidate <= now:
            year += 1
            if day > calendar.monthrange(year, month)[1]:
                raise ValueError("data")
        return datetime(year, month, day).date()
    if day < 1 or day > 31:
        raise ValueError("data")
    year, month = now.year, now.month
    for _step in range(14):
        if day <= calendar.monthrange(year, month)[1]:
            candidate = datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
            if candidate > now:
                return candidate.date()
        month += 1
        if month == 13:
            month = 1
            year += 1
    raise ValueError("data")


def _next_weekday(folded, now, hour, minute):
    names = {
        "segunda": 0,
        "terca": 1,
        "quarta": 2,
        "quinta": 3,
        "sexta": 4,
        "sabado": 5,
        "domingo": 6,
    }
    key = folded.split("-", 1)[0].strip()
    if key not in names:
        raise ValueError("data")
    target = names[key]
    days = (target - now.weekday()) % 7
    candidate_day = now.date() + timedelta(days=days)
    candidate = datetime(
        candidate_day.year,
        candidate_day.month,
        candidate_day.day,
        hour,
        minute,
        tzinfo=now.tzinfo,
    )
    if candidate <= now:
        candidate_day = candidate_day + timedelta(days=7)
    return candidate_day


def _obsidian_daily(root, day):
    import json

    config_path = root / ".obsidian" / "daily-notes.json"
    if not config_path.is_file():
        return None
    try:
        data = json.loads(_read(config_path))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    folder = _safe_relative(str(data.get("folder") or ""))
    fmt = str(data.get("format") or "YYYY-MM-DD")
    stamp = (
        fmt.replace("YYYY", "%Y")
        .replace("DD", "%d")
        .replace("MM", "%m")
    )
    try:
        name = day.strftime(stamp)
    except ValueError:
        name = day.strftime("%Y-%m-%d")
    if "/" in name or name.startswith("."):
        return None
    relative = f"{folder}/{name}.md" if folder else f"{name}.md"
    safe = _safe_relative(relative)
    if not safe:
        return None
    return root / safe


def _daily_template(root):
    import json

    config_path = root / ".obsidian" / "daily-notes.json"
    if not config_path.is_file():
        return None
    try:
        data = json.loads(_read(config_path))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    relative = _safe_relative(str(data.get("template") or ""))
    if not relative:
        return None
    path = root / relative
    if path.is_file() and _inside(path, root):
        return path
    return None


def _dated_parent(root):
    newest = None
    parent = None
    seen = 0
    for path in iter_notes(root):
        seen += 1
        if seen > MAX_WALK:
            break
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or modified > newest:
            newest = modified
            parent = path.parent
    if parent is None:
        return None
    try:
        return Path(root) / parent.relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return parent


def _apply_date(template, day, root):
    stamp = day.strftime("%Y-%m-%d")
    text = template
    for token in ("AAAA-MM-DD", "YYYY-MM-DD", "{{date}}", "{{date:YYYY-MM-DD}}"):
        text = text.replace(token, stamp)
    if stamp in text:
        return text
    candidate = root / text
    if text.endswith(".md") and not candidate.is_dir():
        return text
    return text.rstrip("/") + f"/{stamp}.md"


def _reminder_confirmation(text, when, now, repeat=""):
    clock = str(when.hour) if when.minute == 0 else f"{when.hour}:{when.minute:02d}"
    day = _day_phrase(when, now)
    if repeat:
        habit = REPEAT_SPEECH.get(repeat, "de novo")
        return (
            f"Combinado, senhor. Vou lembrar {habit} às {clock}, "
            f"a partir de {day}: {text}."
        )
    return f"Combinado, senhor. Vou lembrar {day} às {clock}: {text}."


def _day_phrase(when, now):
    if when.date() == now.date():
        return "hoje"
    if when.date() == now.date() + timedelta(days=1):
        return "amanhã"
    if when.date() == now.date() + timedelta(days=2):
        return "depois de amanhã"
    return f"{WEEKDAYS[when.weekday()]}, {when.day} de {MONTHS[when.month - 1]}"


def _spoken_date(moment):
    return (
        f"{WEEKDAYS[moment.weekday()]}, {moment.day} de "
        f"{MONTHS[moment.month - 1]} de {moment.year}"
    )


def _join_pt(items):
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


def _snippet(text, tokens):
    body = _without_frontmatter(text)
    lines = body.splitlines()
    best = ""
    best_score = 0
    for index, line in enumerate(lines):
        folded = fold(line)
        present = sum(1 for token in tokens if token in folded)
        if present == 0:
            continue
        plain = _plain(line)
        if not plain:
            continue
        extra = ""
        if line.lstrip().startswith("#") and index + 1 < len(lines):
            nxt = _plain(lines[index + 1])
            if nxt:
                extra = " " + nxt
        candidate = (plain + extra)[:180]
        if present > best_score or (present == best_score and len(candidate) > len(best)):
            best = candidate
            best_score = present
    if best:
        return best
    plain = _plain(body)
    return plain[:180] if plain else "há um registro"


def _without_frontmatter(text):
    if (text or "").startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :]
    return text or ""


def _title(path, text):
    for line in text.splitlines():
        if line.startswith("# "):
            title = _plain(line)
            if title:
                return title
    return path.stem


def _plain(text):
    cleaned = re.sub(r"[#>*_`\[\]]", " ", text or "")
    cleaned = cleaned.replace("\u2014", " ").replace("\u2013", " ")
    return " ".join(cleaned.split())


def _read(path):
    from .leitura import ler_nota

    try:
        texto, _digest = ler_nota(path)
    except Exception:
        return ""
    if texto is None:
        return ""
    return texto[:MAX_NOTE_CHARS]


def _safe_relative(raw):
    from .paths import caminho_relativo

    return caminho_relativo(raw)


def _label_in(folded, label):
    return re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", folded) is not None


def _aware(now, places):
    if now.tzinfo is None:
        return now.replace(tzinfo=places.tz)
    return now.astimezone(places.tz)


def _inside(path, root):
    from .paths import esta_dentro

    return esta_dentro(path, root)


def _same(path, other):
    try:
        return Path(path).resolve() == Path(other).resolve()
    except OSError:
        return False
