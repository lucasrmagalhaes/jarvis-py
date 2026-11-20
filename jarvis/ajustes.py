"""Catálogo tipado das variáveis de ambiente do Jarvis.

Cada nome tem padrão, validação e texto para o exemplo e para o README.
Valor inválido cai no padrão ou no limite. O diagnóstico lista o número
que não pôde ser lido, para o erro de digitação não passar em silêncio.
"""

import math
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Sem remoto padrão. O clone é o que JARVIS_VAULT apontar.
# JARVIS_VAULT_REMOTE, se preenchido, trava o destino do sync.
VAULT_REMOTE_DEFAULT = ""
NOME_PADRAO = "usuario"
READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]
VAULT_WRITE_TOOLS = ["Edit", "Write"]

_FALSO = {"0", "off", "false", "no", "nao", "não"}
_NUMEROS = {
    "JARVIS_TURN_TIMEOUT": (int, 300, 1, None),
    "JARVIS_SPEECH_RATE": (int, 190, 1, None),
    "JARVIS_EDGE_TIMEOUT": (float, 30.0, 0.1, None),
    "JARVIS_SAPI_RATE": (int, 1, -10, 10),
    "JARVIS_SILENCE_THRESHOLD": (float, 0.012, 0.0, None),
    "JARVIS_SILENCE_SECONDS": (float, 1.2, 0.05, None),
    "JARVIS_NO_SPEECH_SECONDS": (float, 6.0, 0.05, None),
    "JARVIS_MAX_RECORD_SECONDS": (float, 60.0, 0.05, None),
    "JARVIS_WAKE_THRESHOLD": (float, 0.5, 0.0, 1.0),
    "JARVIS_FOLLOWUP_NO_SPEECH_SECONDS": (float, 4.0, 0.0, None),
    "JARVIS_PANEL_PORT": (int, 8765, 1, 65535),
}


class Ajuste:
    def __init__(self, nome, padrao, grupo, descricao, segredo=False, mostrar=False):
        self.nome = nome
        self.padrao = padrao
        self.grupo = grupo
        self.descricao = descricao
        self.segredo = segredo
        self.mostrar = mostrar


def _flag(nome, padrao):
    raw = os.environ.get(nome)
    if raw is None:
        return padrao
    return raw.strip().lower() not in _FALSO


def _ler_numero(nome, environ=None):
    tipo, padrao, baixo, alto = _NUMEROS[nome]
    source = os.environ if environ is None else environ
    raw = str(source.get(nome) or "").strip()
    if not raw:
        return padrao, True
    texto = raw.replace(",", ".") if tipo is float else raw
    try:
        valor = tipo(texto)
    except (ValueError, OverflowError):
        return padrao, False
    if isinstance(valor, float) and not math.isfinite(valor):
        return padrao, False
    if baixo is not None and valor < baixo:
        return padrao, False
    if alto is not None and valor > alto:
        return padrao, False
    return valor, True


def _numero(nome):
    return _ler_numero(nome)[0]


def numeros_invalidos(environ=None):
    return [nome for nome in _NUMEROS if not _ler_numero(nome, environ)[1]]


def _bounded_int(nome, padrao, baixo, alto):
    raw = os.environ.get(nome, "").strip()
    if not raw:
        return padrao
    try:
        value = int(raw)
    except ValueError:
        return padrao
    if value < baixo:
        return baixo
    if value > alto:
        return alto
    return value


def _relogio(raw, padrao):
    parts = (raw or "").split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return padrao
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return padrao
    return (hour, minute)


def env_file(environ=None):
    source = os.environ if environ is None else environ
    raw = source.get("JARVIS_ENV_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".jarvis" / ".env"


def jarvis_home():
    raw = os.environ.get("JARVIS_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".jarvis"


def workspace_dir():
    raw = os.environ.get("JARVIS_WORKSPACE", "").strip()
    if not raw:
        return PROJECT_ROOT / "workspace"
    return Path(raw).expanduser()


def prompt_path():
    raw = os.environ.get("JARVIS_PROMPT_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return PROJECT_ROOT / "workspace" / "prompt-vault.md"


def vault_dir():
    raw = os.environ.get("JARVIS_VAULT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def vault_sync_enabled():
    if vault_dir() is None:
        return False
    return _flag("JARVIS_VAULT_SYNC", True)


def vault_remote():
    raw = os.environ.get("JARVIS_VAULT_REMOTE")
    if raw is None or not raw.strip():
        return VAULT_REMOTE_DEFAULT
    return raw.strip()


def nome_usuario():
    """Remetente das notas de pedido. O padrão não identifica ninguém."""
    raw = os.environ.get("JARVIS_NOME", "").strip()
    if not raw or len(raw) > 40:
        return NOME_PADRAO
    if any(char in raw for char in "\r\n:{}[]#/\\"):
        return NOME_PADRAO
    return raw


def vault_branch():
    return os.environ.get("JARVIS_VAULT_BRANCH", "").strip()


def vault_git_timeout():
    raw = os.environ.get("JARVIS_VAULT_GIT_TIMEOUT", "").strip()
    if not raw:
        return 120
    try:
        value = int(raw)
    except ValueError:
        return 120
    return value if value > 0 else 120


def doctor_git_timeout():
    return _bounded_int("JARVIS_DOCTOR_GIT_TIMEOUT", 10, 1, 120)


def git_bin():
    return os.environ.get("JARVIS_GIT_BIN", "git")


def gh_bin():
    return os.environ.get("JARVIS_GH_BIN", "gh").strip() or "gh"


def claude_bin():
    return os.environ.get("JARVIS_CLAUDE_BIN", "claude")


def model():
    return os.environ.get("JARVIS_MODEL", "")


def allowed_tools():
    explicit = os.environ.get("JARVIS_ALLOWED_TOOLS")
    if explicit is None:
        tools = list(READ_ONLY_TOOLS)
        if vault_dir() is not None:
            tools.extend(VAULT_WRITE_TOOLS)
        return tools
    return [tool.strip() for tool in explicit.split(",") if tool.strip()]


def turn_timeout():
    return _numero("JARVIS_TURN_TIMEOUT")


def log_path():
    raw = os.environ.get("JARVIS_LOG", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".jarvis" / "logs" / "jarvis.log"


def state_file():
    raw = os.environ.get("JARVIS_STATE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return jarvis_home() / "state.json"


def review_file():
    raw = os.environ.get("JARVIS_REVISAO", "").strip()
    if raw:
        return Path(raw).expanduser()
    return jarvis_home() / "revisao.json"


def voice():
    return os.environ.get("JARVIS_VOICE", "Luciana")


def speech_rate():
    return _numero("JARVIS_SPEECH_RATE")


def tts_backend():
    return os.environ.get("JARVIS_TTS", "auto")


def edge_voice():
    return os.environ.get("JARVIS_EDGE_VOICE", "pt-BR-AntonioNeural")


def edge_rate():
    return os.environ.get("JARVIS_EDGE_RATE", "+10%")


def edge_timeout():
    return _numero("JARVIS_EDGE_TIMEOUT")


def sapi_rate():
    return _numero("JARVIS_SAPI_RATE")


def stt_backend():
    raw = os.environ.get("JARVIS_STT", "").strip().lower().replace("_", "-")
    if raw in {"faster-whisper", "faster"}:
        return "faster-whisper"
    if raw in {"whisper", "openai-whisper", "openai"}:
        return "whisper"
    return "auto"


def whisper_model():
    raw = os.environ.get("JARVIS_WHISPER_MODEL", "").strip() or "small"
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-")
    if 1 <= len(raw) <= 64 and all(char in allowed for char in raw):
        return raw
    return "small"


def language():
    return os.environ.get("JARVIS_LANGUAGE", "pt")


def silence_threshold():
    return _numero("JARVIS_SILENCE_THRESHOLD")


def silence_seconds():
    return _numero("JARVIS_SILENCE_SECONDS")


def no_speech_seconds():
    return _numero("JARVIS_NO_SPEECH_SECONDS")


def max_record_seconds():
    return _numero("JARVIS_MAX_RECORD_SECONDS")


def wake_model():
    return os.environ.get("JARVIS_WAKE_MODEL", "hey_jarvis_v0.1")


def wake_threshold():
    return _numero("JARVIS_WAKE_THRESHOLD")


def followup_seconds():
    return _numero("JARVIS_FOLLOWUP_NO_SPEECH_SECONDS")


def context_persist():
    return _flag("JARVIS_CONTEXTO", True)


def context_turns():
    return _bounded_int("JARVIS_CONTEXTO_TURNOS", 6, 1, 12)


def context_file():
    raw = os.environ.get("JARVIS_CONTEXTO_ARQUIVO", "").strip()
    if raw:
        return Path(raw).expanduser()
    return jarvis_home() / "contexto.json"


def stream_enabled():
    return _flag("JARVIS_STREAM", True)


def panel_enabled():
    raw = os.environ.get("JARVIS_PANEL", "on")
    return raw.lower() != "off"


def panel_port():
    return _numero("JARVIS_PANEL_PORT")


def panel_bind():
    raw = os.environ.get("JARVIS_PANEL_BIND", "").strip().lower()
    if raw in {"", "127.0.0.1", "localhost", "::1"}:
        return "127.0.0.1"
    return "127.0.0.1"


def panel_open():
    return _flag("JARVIS_PANEL_OPEN", True)


def bandeja_ligada():
    return _flag("JARVIS_BANDEJA", True)


def consult_port():
    raw = os.environ.get("JARVIS_CONSULT_PORT", "").strip()
    if not raw:
        return 8766
    try:
        value = int(raw)
    except ValueError:
        return 8766
    if value < 1 or value > 65535:
        return 8766
    return value


def consult_bind():
    return os.environ.get("JARVIS_CONSULT_BIND", "127.0.0.1").strip() or "127.0.0.1"


def consult_model_enabled():
    return _flag("JARVIS_CONSULT_MODEL", True)


def consult_model_dir():
    raw = os.environ.get("JARVIS_CONSULT_MODEL_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return jarvis_home() / "models" / "consult"


def reminder_interval():
    return _bounded_int("JARVIS_REMINDER_SECONDS", 15, 5, 300)


def checkin_enabled():
    return _flag("JARVIS_CHECKIN", True)


def checkin_morning():
    return checkin_enabled() and _flag("JARVIS_CHECKIN_MORNING", True)


def checkin_evening():
    return checkin_enabled() and _flag("JARVIS_CHECKIN_EVENING", True)


def checkin_evening_at():
    raw = os.environ.get("JARVIS_CHECKIN_EVENING_AT", "").strip() or "18:30"
    return _relogio(raw, (18, 30))


def radar_enabled():
    return _flag("JARVIS_RADAR", True)


def radar_interval():
    return _bounded_int("JARVIS_RADAR_SECONDS", 300, 60, 3600)


def radar_cooldown():
    return _bounded_int("JARVIS_RADAR_COOLDOWN", 900, 60, 86400)


def review_limit():
    return _bounded_int("JARVIS_REVISAO_LIMITE", 10, 1, 50)


def review_new_limit():
    return _bounded_int("JARVIS_REVISAO_NOVOS", 5, 0, 50)


def review_priority():
    raw = os.environ.get("JARVIS_REVISAO_PRIORIDADE", "")
    found = []
    for part in raw.split(","):
        token = " ".join(part.strip().split())
        if not token or len(token) > 120 or token in found:
            continue
        found.append(token)
        if len(found) >= 12:
            break
    return tuple(found)


def pastas_privadas_raw():
    return os.environ.get("JARVIS_PASTAS_PRIVADAS", "")


def pastas_ignoradas_raw():
    return os.environ.get("JARVIS_PASTAS_IGNORADAS", "")


def tag_sigilosa():
    raw = os.environ.get("JARVIS_TAG_SIGILOSA", "").strip()
    token = raw.lstrip("#").strip() or "sigiloso"
    token = token.split()[0].lstrip("#")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", token):
        return "sigiloso"
    return token.casefold()


def jira_url():
    return os.environ.get("JIRA_URL", "").strip().rstrip("/")


def jira_email():
    return os.environ.get("JIRA_EMAIL", "").strip()


def jira_token():
    return os.environ.get("JIRA_TOKEN", "").strip()


def gmail_email():
    return os.environ.get("GMAIL_EMAIL", "").strip()


def gmail_password():
    return os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()


def gmail_host():
    return os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com"


def gmail_port():
    raw = os.environ.get("GMAIL_IMAP_PORT", "993").strip() or "993"
    try:
        return int(raw)
    except ValueError:
        return 993


def telegram_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def telegram_user_raw():
    return os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()


def telegram_allowed_user_id():
    raw = telegram_user_raw()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def telegram_voice_reply():
    return _flag("TELEGRAM_VOICE_REPLY", False)


def telegram_chat_raw():
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def telegram_chat_id():
    raw = telegram_chat_raw()
    if not raw:
        return telegram_allowed_user_id()
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def telegram_limite():
    return _bounded_int("TELEGRAM_LIMITE", 20, 1, 60)


def telegram_ready():
    return (
        bool(telegram_token())
        and telegram_allowed_user_id() is not None
        and telegram_chat_id() is not None
    )


def readwise_token():
    return os.environ.get("READWISE_TOKEN", "").strip()


def readwise_pasta():
    raw = os.environ.get("JARVIS_READWISE_PASTA", "").strip()
    return raw or "Leituras/Readwise"


def destaques_pasta():
    raw = os.environ.get("JARVIS_DESTAQUES_PASTA", "").strip()
    return raw or "Leituras/Destaques"


def destaques_entrada():
    from .paths import windows_drive

    raw = os.environ.get("JARVIS_DESTAQUES_ENTRADA", "").strip()
    if not raw:
        return jarvis_home() / "destaques"
    bruto = os.path.expandvars(raw)
    caminho = Path(bruto).expanduser()
    if windows_drive(bruto) or caminho.is_absolute():
        return caminho
    return jarvis_home() / caminho


def _pasta_segura(raw, padrao):
    from .paths import caminho_relativo

    if not str(raw or "").strip():
        return padrao
    safe = caminho_relativo(raw)
    return safe or padrao


def videos_pasta():
    return _pasta_segura(os.environ.get("JARVIS_VIDEOS_PASTA", ""), "Tecnologia/Vídeos")


def livros_pasta():
    return _pasta_segura(os.environ.get("JARVIS_LIVROS_PASTA", ""), "Tecnologia/Livros")


def cursos_pasta():
    return _pasta_segura(os.environ.get("JARVIS_CURSOS_PASTA", ""), "Tecnologia/Cursos")


def artigos_pasta():
    return _pasta_segura(os.environ.get("JARVIS_ARTIGOS_PASTA", ""), "Tecnologia/Artigos")


def podcasts_pasta():
    return _pasta_segura(os.environ.get("JARVIS_PODCASTS_PASTA", ""), "Tecnologia/Podcasts")


def estudo_midia_pasta():
    raw = os.environ.get("JARVIS_ESTUDO_MIDIA_PASTA", "").strip()
    return raw or "Estudos/Mídia"


def midia_entrada():
    from .paths import windows_drive

    raw = os.environ.get("JARVIS_MIDIA_ENTRADA", "").strip()
    if not raw:
        return jarvis_home() / "midia"
    bruto = os.path.expandvars(raw)
    caminho = Path(bruto).expanduser()
    if windows_drive(bruto) or caminho.is_absolute():
        return caminho
    return jarvis_home() / caminho


def captura_cartoes():
    return _flag("JARVIS_CAPTURA_CARTOES", True)


def digest_enabled():
    return _flag("JARVIS_DIGEST", False)


def digest_at():
    raw = os.environ.get("JARVIS_DIGEST_AT", "").strip()
    if not raw:
        return checkin_evening_at()
    return _relogio(raw, (18, 30))


def briefing_telegram():
    return _flag("JARVIS_BRIEFING_TELEGRAM", False)


def briefing_at():
    raw = os.environ.get("JARVIS_BRIEFING_HORA", "").strip() or "07:30"
    return _relogio(raw, (7, 30))


def lembrete_nota():
    return _flag("JARVIS_LEMBRETE_NOTA", False)


def lembrete_nota_at():
    raw = os.environ.get("JARVIS_LEMBRETE_NOTA_HORA", "").strip() or "08:00"
    return _relogio(raw, (8, 0))


def revisao_semanal():
    return _flag("JARVIS_REVISAO_SEMANAL", False)


def revisao_semanal_at():
    raw = os.environ.get("JARVIS_REVISAO_SEMANAL_HORA", "").strip() or "10:00"
    return _relogio(raw, (10, 0))


def revisao_semanal_pasta():
    return _pasta_segura(os.environ.get("JARVIS_REVISAO_SEMANAL_PASTA", ""), "Diario/Revisao")


def toque_sequencia():
    return _flag("JARVIS_TOQUE_SEQUENCIA", False)


def toque_sequencia_at():
    raw = os.environ.get("JARVIS_TOQUE_SEQUENCIA_HORA", "").strip() or "20:00"
    return _relogio(raw, (20, 0))


def modo_prazo():
    return _bounded_int("JARVIS_MODO_PRAZO", 1800, 60, 7200)


def sessao_minutos():
    return _bounded_int("JARVIS_SESSAO_MINUTOS", 25, 1, 180)


def sessao_pausa():
    return _bounded_int("JARVIS_SESSAO_PAUSA", 5, 0, 60)


def sessao_nota():
    raw = os.environ.get("JARVIS_SESSAO_NOTA", "").strip().lower()
    if raw in {"diario", "diaria", "dia"}:
        return "diario"
    return "meta"


def sessao_pasta():
    return _pasta_segura(os.environ.get("JARVIS_SESSAO_PASTA", ""), "Estudos/Sessoes")


def sessao_telegram():
    return _flag("JARVIS_SESSAO_TELEGRAM", False)


def sessao_silencio():
    return _flag("JARVIS_SESSAO_SILENCIO", True)


def metas_no_vault():
    return _flag("JARVIS_METAS_VAULT", False)


def metas_pasta():
    return _pasta_segura(os.environ.get("JARVIS_METAS_PASTA", ""), "Estudos/Metas")


def mapas_pasta():
    return _pasta_segura(os.environ.get("JARVIS_MAPAS_PASTA", ""), "Estudos/Mapas")


def persona_relativa():
    return os.environ.get("JARVIS_PERSONA", "").strip() or "Jarvis/Persona.md"


def cerebro_raw():
    return os.environ.get("JARVIS_CEREBRO", "").strip().lower()


def ollama_url():
    return os.environ.get("JARVIS_OLLAMA_URL", "").strip() or "http://127.0.0.1:11434"


def ollama_model():
    raw = os.environ.get("JARVIS_OLLAMA_MODEL", "").strip() or "llama3.2"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", raw):
        return "llama3.2"
    return raw


def ollama_timeout():
    return _bounded_int("JARVIS_OLLAMA_TIMEOUT", 20, 1, 120)


def study_limit():
    return _bounded_int("JARVIS_ESTUDO_LIMITE", 3, 1, 8)


def study_brain():
    return _flag("JARVIS_ESTUDO_CEREBRO", False)


def busca_modo():
    raw = os.environ.get("JARVIS_BUSCA", "")
    texto = _sem_acento(raw)
    if texto in {"semantica"}:
        return "semantica"
    if texto in {"hibrida", "hybrid"}:
        return "hibrida"
    return "palavras"


def _sem_acento(raw):
    import unicodedata

    normal = unicodedata.normalize("NFKD", raw or "")
    plain = "".join(char for char in normal if not unicodedata.combining(char))
    return plain.casefold().strip()


def index_relative():
    raw = os.environ.get("JARVIS_INDICE")
    if raw is None:
        return "indice.md"
    text = raw.strip()
    if not text or text.lower() in _FALSO:
        return ""
    return text


def skip_hardware():
    raw = os.environ.get("JARVIS_SKIP_HARDWARE", "").strip().lower()
    return raw in {"1", "on", "true", "yes", "sim"}


def atualizar_ligado():
    return _flag("JARVIS_ATUALIZAR", True)


def atualizar_timeout():
    return _bounded_int("JARVIS_ATUALIZAR_TIMEOUT", 120, 5, 600)


def relatorio_linhas():
    return _bounded_int("JARVIS_RELATORIO_LINHAS", 40, 0, 200)


def relatorio_pasta():
    raw = os.environ.get("JARVIS_RELATORIO_PASTA", "").strip()
    if not raw:
        return Path.home()
    return Path(raw).expanduser()


CATALOGO = (
    Ajuste("JARVIS_HOME", "~/.jarvis", "Pastas", "Pasta local de log, estado e revisão."),
    Ajuste(
        "JARVIS_ENV_FILE",
        "~/.jarvis/.env",
        "Pastas",
        "Arquivo de ambiente. Variável que já existe no processo não é coberta.",
    ),
    Ajuste(
        "JARVIS_VAULT",
        "",
        "Vault",
        "Clone local do vault. Vazio desliga a leitura das notas.",
        mostrar=True,
    ),
    Ajuste(
        "JARVIS_PASTAS_PRIVADAS",
        "",
        "Vault",
        "Pastas relativas do vault, separadas por vírgula, que não saem desta máquina.",
        mostrar=True,
    ),
    Ajuste(
        "JARVIS_PASTAS_IGNORADAS",
        "",
        "Vault",
        "Pastas do vault, separadas por vírgula, fora da busca, dos cartões e dos lembretes. "
        "Não é sigilo: o Claude continua lendo essas pastas.",
        mostrar=True,
    ),
    Ajuste(
        "JARVIS_TAG_SIGILOSA",
        "sigiloso",
        "Vault",
        "Tag de nota que fica só no modelo local.",
        mostrar=True,
    ),
    Ajuste("JARVIS_VAULT_SYNC", "on", "Vault", "off usa o vault sem pull, commit ou push."),
    Ajuste(
        "JARVIS_VAULT_REMOTE",
        VAULT_REMOTE_DEFAULT,
        "Vault",
        "Remoto git esperado. Vazio aceita o origin do clone. Se preenchido, outro destino é recusado. HTTPS e SSH do mesmo repositório contam igual.",
    ),
    Ajuste(
        "JARVIS_VAULT_BRANCH",
        "",
        "Vault",
        "Se definida, o clone já precisa estar nessa branch.",
    ),
    Ajuste("JARVIS_VAULT_GIT_TIMEOUT", "120", "Vault", "Segundos de cada comando git do sync."),
    Ajuste("JARVIS_DOCTOR_GIT_TIMEOUT", "10", "Vault", "Segundos da checagem de remoto no diagnóstico."),
    Ajuste("JARVIS_GIT_BIN", "git", "Executáveis", "Executável do git, nome no PATH ou caminho completo."),
    Ajuste("JARVIS_CLAUDE_BIN", "claude", "Executáveis", "Executável do Claude Code."),
    Ajuste("JARVIS_GH_BIN", "gh", "Executáveis", "Executável do GitHub CLI. A consulta de PR é só leitura."),
    Ajuste("JARVIS_MODEL", "", "Executáveis", "Modelo do Claude. Vazio usa o padrão da conta."),
    Ajuste("JARVIS_WORKSPACE", "./workspace", "Pastas", "Pasta de trabalho quando o vault não está configurado."),
    Ajuste("JARVIS_PROMPT_FILE", "./workspace/prompt-vault.md", "Pastas", "Arquivo do prompt montado fora do vault."),
    Ajuste(
        "JARVIS_ALLOWED_TOOLS",
        "Read,Glob,Grep,WebSearch,WebFetch",
        "Executáveis",
        "Ferramentas do Claude, separadas por vírgula. Com vault e sem esta variável, entram Edit e Write.",
    ),
    Ajuste("JARVIS_TURN_TIMEOUT", "300", "Executáveis", "Segundos de cada consulta ao Claude."),
    Ajuste("JARVIS_LOG", "~/.jarvis/logs/jarvis.log", "Pastas", "Log local rotativo, fora do vault."),
    Ajuste("JARVIS_STATE", "~/.jarvis/state.json", "Pastas", "Estado local dos avisos. Não guarda segredo."),
    Ajuste("JARVIS_REVISAO", "~/.jarvis/revisao.json", "Estudo", "Agendamento da revisão espaçada, fora do vault."),
    Ajuste("JARVIS_TTS", "auto", "Voz", "Backend de voz: auto, say, edge ou sapi."),
    Ajuste("JARVIS_VOICE", "Luciana", "Voz", "Voz do macOS."),
    Ajuste("JARVIS_SPEECH_RATE", "190", "Voz", "Velocidade da fala do backend say."),
    Ajuste("JARVIS_EDGE_VOICE", "pt-BR-AntonioNeural", "Voz", "Voz neural do backend edge."),
    Ajuste("JARVIS_EDGE_RATE", "+10%", "Voz", "Velocidade da fala do backend edge."),
    Ajuste("JARVIS_EDGE_TIMEOUT", "30", "Voz", "Segundos para sintetizar com o backend edge."),
    Ajuste("JARVIS_SAPI_RATE", "1", "Voz", "Velocidade da fala do backend sapi, de -10 a 10."),
    Ajuste(
        "JARVIS_STT",
        "auto",
        "Ouvido",
        "faster-whisper, whisper ou auto. auto prefere o faster-whisper.",
    ),
    Ajuste("JARVIS_WHISPER_MODEL", "small", "Ouvido", "Tamanho do modelo local: tiny, base, small ou medium."),
    Ajuste("JARVIS_LANGUAGE", "pt", "Ouvido", "Idioma da transcrição."),
    Ajuste("JARVIS_SILENCE_THRESHOLD", "0.012", "Ouvido", "Sensibilidade do detector de silêncio."),
    Ajuste("JARVIS_SILENCE_SECONDS", "1.2", "Ouvido", "Pausa, em segundos, que encerra a captura."),
    Ajuste("JARVIS_NO_SPEECH_SECONDS", "6", "Ouvido", "Segundos sem fala antes de desistir da captura."),
    Ajuste("JARVIS_MAX_RECORD_SECONDS", "60", "Ouvido", "Duração máxima, em segundos, de uma captura."),
    Ajuste("JARVIS_WAKE_MODEL", "hey_jarvis_v0.1", "Ouvido", "Modelo ONNX da palavra de ativação."),
    Ajuste("JARVIS_WAKE_THRESHOLD", "0.5", "Ouvido", "Sensibilidade da palavra de ativação."),
    Ajuste("JARVIS_FOLLOWUP_NO_SPEECH_SECONDS", "4", "Ouvido", "Segundos de continuação depois da resposta."),
    Ajuste(
        "JARVIS_NOME",
        NOME_PADRAO,
        "Conversa",
        "Nome no remetente das notas de pedido. O padrão é neutro.",
    ),
    Ajuste("JARVIS_CONTEXTO", "on", "Conversa", "on guarda as últimas trocas em ~/.jarvis/contexto.json."),
    Ajuste("JARVIS_CONTEXTO_TURNOS", "6", "Conversa", "Quantas trocas recentes acompanham o pedido seguinte."),
    Ajuste("JARVIS_CONTEXTO_ARQUIVO", "~/.jarvis/contexto.json", "Conversa", "Arquivo do contexto. Não leva trecho de nota."),
    Ajuste("JARVIS_STREAM", "on", "Conversa", "Fala a primeira frase assim que ela fecha."),
    Ajuste(
        "JARVIS_MODO_PRAZO",
        "1800",
        "Conversa",
        "Prazo em segundos de explicação, teste ou confirmação. cancela ou para encerra.",
    ),
    Ajuste("JARVIS_PANEL", "on", "Painel", "Painel local. off desliga."),
    Ajuste("JARVIS_PANEL_PORT", "8765", "Painel", "Porta do painel. Não exponha fora da máquina."),
    Ajuste("JARVIS_PANEL_BIND", "127.0.0.1", "Painel", "Só loopback. Outro valor é ignorado."),
    Ajuste("JARVIS_PANEL_OPEN", "on", "Painel", "Abrir o navegador ao iniciar."),
    Ajuste("JARVIS_BANDEJA", "on", "Painel", "off não cria o ícone da bandeja."),
    Ajuste("JARVIS_CONSULT_PORT", "8766", "Consulta", "Porta da consulta somente leitura."),
    Ajuste("JARVIS_CONSULT_BIND", "127.0.0.1", "Consulta", "127.0.0.1 ou lan. 0.0.0.0 e IP público são recusados."),
    Ajuste("JARVIS_CONSULT_MODEL", "on", "Consulta", "off ignora o modelo local mesmo com os pesos em disco."),
    Ajuste("JARVIS_CONSULT_MODEL_DIR", "~/.jarvis/models/consult", "Consulta", "Pasta dos pesos do modelo gratuito."),
    Ajuste("JARVIS_REMINDER_SECONDS", "15", "Avisos", "Intervalo, em segundos, da busca de lembretes vencidos."),
    Ajuste("JARVIS_CHECKIN", "on", "Avisos", "off desliga o briefing e o resumo do fim do dia."),
    Ajuste("JARVIS_CHECKIN_MORNING", "on", "Avisos", "Briefing no primeiro arranque do dia."),
    Ajuste("JARVIS_CHECKIN_EVENING", "on", "Avisos", "Resumo do fim do dia, com oferta de gravar."),
    Ajuste("JARVIS_CHECKIN_EVENING_AT", "18:30", "Avisos", "Horário local do resumo, HH:MM."),
    Ajuste("JARVIS_RADAR", "on", "Avisos", "off desliga os alertas de PR, Jira e e-mail. Só leitura."),
    Ajuste("JARVIS_RADAR_SECONDS", "300", "Avisos", "Intervalo, em segundos, da consulta somente leitura."),
    Ajuste("JARVIS_RADAR_COOLDOWN", "900", "Avisos", "Segundos mínimos entre um aviso e outro."),
    Ajuste("JARVIS_REVISAO_LIMITE", "10", "Estudo", "Cartões da revisão por dia, entre 1 e 50."),
    Ajuste(
        "JARVIS_REVISAO_NOVOS",
        "5",
        "Estudo",
        "Cartões novos por dia, entre 0 e 50. O limite do dia continua valendo.",
    ),
    Ajuste(
        "JARVIS_REVISAO_PRIORIDADE",
        "",
        "Estudo",
        "Pastas ou tags, separadas por vírgula. Esses cartões entram primeiro.",
    ),
    Ajuste("JIRA_URL", "", "Integrações", "Endereço do Jira. O Jarvis só lê issues.", segredo=False),
    Ajuste("JIRA_EMAIL", "", "Integrações", "E-mail da conta Atlassian. Só leitura."),
    Ajuste("JIRA_TOKEN", "", "Integrações", "Token de API do Jira. Só leitura. Não commite.", segredo=True),
    Ajuste("GMAIL_EMAIL", "", "Integrações", "Conta Gmail lida por IMAP. O Jarvis não envia e-mail."),
    Ajuste("GMAIL_APP_PASSWORD", "", "Integrações", "Senha de app do Gmail. Não envia e-mail. Não commite.", segredo=True),
    Ajuste("GMAIL_IMAP_HOST", "imap.gmail.com", "Integrações", "Servidor IMAP."),
    Ajuste("GMAIL_IMAP_PORT", "993", "Integrações", "Porta IMAP."),
    Ajuste("TELEGRAM_BOT_TOKEN", "", "Telegram", "Token do bot. Vazio desliga. Não commite.", segredo=True),
    Ajuste("TELEGRAM_ALLOWED_USER_ID", "", "Telegram", "ID numérico do único usuário. Sem ele o bot não conecta."),
    Ajuste("TELEGRAM_VOICE_REPLY", "off", "Telegram", "on também envia a resposta em áudio."),
    Ajuste(
        "TELEGRAM_CHAT_ID",
        "",
        "Telegram",
        "ID numérico da conversa privada. Vazio usa o ID do usuário. Outro chat é recusado.",
    ),
    Ajuste(
        "TELEGRAM_LIMITE",
        "20",
        "Telegram",
        "Mensagens por minuto no Telegram, entre 1 e 60.",
    ),
    Ajuste("READWISE_TOKEN", "", "Integrações", "Token do Readwise. Só baixa destaque. Não commite.", segredo=True),
    Ajuste("JARVIS_READWISE_PASTA", "Leituras/Readwise", "Integrações", "Pasta do clone para cada livro ou artigo."),
    Ajuste(
        "JARVIS_DESTAQUES_PASTA",
        "Leituras/Destaques",
        "Integrações",
        "Pasta do clone para uma nota por livro importado do Kindle, PDF ou KOReader.",
    ),
    Ajuste(
        "JARVIS_DESTAQUES_ENTRADA",
        "~/.jarvis/destaques",
        "Integrações",
        "Pasta de entrada de My Clippings, PDF e exportação do KOReader. Fora do vault.",
    ),
    Ajuste(
        "JARVIS_LIVROS_PASTA",
        "Tecnologia/Livros",
        "Captura",
        "Pasta dos livros. A busca nos livros usa este caminho.",
    ),
    Ajuste(
        "JARVIS_VIDEOS_PASTA",
        "Tecnologia/Vídeos",
        "Captura",
        "Pasta do vault para o resumo de um vídeo do YouTube.",
    ),
    Ajuste(
        "JARVIS_CURSOS_PASTA",
        "Tecnologia/Cursos",
        "Captura",
        "Pasta dos cursos. A busca nos cursos usa este caminho.",
    ),
    Ajuste(
        "JARVIS_ARTIGOS_PASTA",
        "Tecnologia/Artigos",
        "Captura",
        "Pasta do vault para o resumo de um artigo.",
    ),
    Ajuste(
        "JARVIS_PODCASTS_PASTA",
        "Tecnologia/Podcasts",
        "Captura",
        "Pasta do vault para o resumo de um episódio.",
    ),
    Ajuste(
        "JARVIS_ESTUDO_MIDIA_PASTA",
        "Estudos/Mídia",
        "Captura",
        "Pasta da nota de estudo de um vídeo ou áudio. Uma nota por vídeo.",
    ),
    Ajuste(
        "JARVIS_MIDIA_ENTRADA",
        "~/.jarvis/midia",
        "Captura",
        "Pasta de entrada de áudio e de links.txt, fora do vault. A fila pede confirmação.",
    ),
    Ajuste(
        "JARVIS_CAPTURA_CARTOES",
        "on",
        "Captura",
        "off grava o resumo sem cartões em rascunho.",
    ),
    Ajuste("JARVIS_DIGEST", "off", "Avisos", "on envia o que aprendi esta semana no Telegram, no domingo."),
    Ajuste("JARVIS_DIGEST_AT", "18:30", "Avisos", "Horário desse envio. Vazio segue o check-in da tarde."),
    Ajuste("JARVIS_BRIEFING_TELEGRAM", "off", "Avisos", "on envia o bom dia no Telegram, uma vez por dia."),
    Ajuste("JARVIS_BRIEFING_HORA", "07:30", "Avisos", "Horário local desse envio, HH:MM."),
    Ajuste(
        "JARVIS_LEMBRETE_NOTA",
        "off",
        "Avisos",
        "on envia no Telegram, uma vez por dia, o título de uma nota antiga e um ponto seu. Nota privada fica de fora.",
    ),
    Ajuste(
        "JARVIS_LEMBRETE_NOTA_HORA",
        "08:00",
        "Avisos",
        "Horário local desse lembrete de nota, HH:MM. O padrão é desligado.",
    ),
    Ajuste(
        "JARVIS_REVISAO_SEMANAL",
        "off",
        "Avisos",
        "on lembra no Telegram, no domingo, de começar a revisão semanal. Não manda texto de nota. O padrão é desligado.",
    ),
    Ajuste(
        "JARVIS_REVISAO_SEMANAL_HORA",
        "10:00",
        "Avisos",
        "Horário local desse lembrete de domingo, HH:MM. Só vale com JARVIS_REVISAO_SEMANAL=on.",
    ),
    Ajuste(
        "JARVIS_TOQUE_SEQUENCIA",
        "off",
        "Avisos",
        "on manda no Telegram, à noite, um aviso se não houve revisão no dia. Não leva texto de nota. O padrão é desligado.",
    ),
    Ajuste(
        "JARVIS_TOQUE_SEQUENCIA_HORA",
        "20:00",
        "Avisos",
        "Horário local desse aviso, HH:MM. Só vale com JARVIS_TOQUE_SEQUENCIA=on.",
    ),
    Ajuste(
        "JARVIS_SESSAO_TELEGRAM",
        "off",
        "Avisos",
        "on avisa no Telegram quando a sessão de estudo acaba. Não leva texto de nota nem o que você aprendeu. O padrão é desligado.",
    ),
    Ajuste(
        "JARVIS_SESSAO_SILENCIO",
        "on",
        "Avisos",
        "on adia briefing, lembrete e resumo enquanto a sessão de estudo está em andamento. off deixa esses avisos passarem.",
    ),
    Ajuste("JARVIS_PERSONA", "Jarvis/Persona.md", "Cérebro", "Nota da persona, relativa ao clone e fora de .obsidian."),
    Ajuste("JARVIS_CEREBRO", "claude", "Cérebro", "claude é o padrão. ollama atende pergunta simples."),
    Ajuste("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434", "Cérebro", "Endereço do Ollama, sem usuário nem senha na URL."),
    Ajuste("JARVIS_OLLAMA_MODEL", "llama3.2", "Cérebro", "Modelo local quando JARVIS_CEREBRO=ollama."),
    Ajuste("JARVIS_OLLAMA_TIMEOUT", "20", "Cérebro", "Segundos da resposta local."),
    Ajuste(
        "JARVIS_SESSAO_MINUTOS",
        "25",
        "Estudo",
        "Minutos da sessão de estudo quando o pedido não diz o tempo. Entre 1 e 180.",
    ),
    Ajuste(
        "JARVIS_SESSAO_PAUSA",
        "5",
        "Estudo",
        "Minutos de pausa depois da sessão, no estilo Pomodoro. 0 desliga a pausa. Entre 0 e 60.",
    ),
    Ajuste(
        "JARVIS_SESSAO_NOTA",
        "meta",
        "Estudo",
        "meta anexa o que você aprendeu na nota do tema. diario anexa na nota do dia. Só depois do sim.",
    ),
    Ajuste(
        "JARVIS_SESSAO_PASTA",
        "Estudos/Sessoes",
        "Estudo",
        "Pasta da nota do tema quando ainda não existe nota de meta.",
    ),
    Ajuste("JARVIS_ESTUDO_LIMITE", "3", "Estudo", "Cartões de me testa sobre, entre 1 e 8."),
    Ajuste(
        "JARVIS_METAS_VAULT",
        "off",
        "Estudo",
        "on também grava a meta de quero aprender numa nota do vault. O padrão fica só em ~/.jarvis.",
    ),
    Ajuste(
        "JARVIS_METAS_PASTA",
        "Estudos/Metas",
        "Estudo",
        "Pasta da nota de meta quando JARVIS_METAS_VAULT=on.",
    ),
    Ajuste(
        "JARVIS_MAPAS_PASTA",
        "Estudos/Mapas",
        "Estudo",
        "Pasta do mapa de conteúdo gravado depois da confirmação de conecta ideias.",
    ),
    Ajuste(
        "JARVIS_REVISAO_SEMANAL_PASTA",
        "Diario/Revisao",
        "Estudo",
        "Pasta da nota revisao-semanal-AAAA-Www.md, gravada depois da confirmação.",
    ),
    Ajuste("JARVIS_ESTUDO_CEREBRO", "off", "Estudo", "on pede ao cérebro só quando a resposta fica parecida."),
    Ajuste("JARVIS_INDICE", "indice.md", "Consulta", "Nota de índice no clone. off desliga."),
    Ajuste(
        "JARVIS_BUSCA",
        "palavras",
        "Consulta",
        "palavras, semantica ou hibrida. O padrão é palavras e a busca não muda. "
        "semantica e hibrida usam embeddings só nesta máquina, gravados em ~/.jarvis.",
    ),
    Ajuste("JARVIS_SKIP_HARDWARE", "", "Diagnóstico", "1 pula a checagem de microfone. Útil sem placa de áudio."),
    Ajuste(
        "JARVIS_ATUALIZAR",
        "on",
        "Manutenção",
        "off recusa a atualização do código. O vault não entra nessa atualização.",
    ),
    Ajuste(
        "JARVIS_ATUALIZAR_TIMEOUT",
        "120",
        "Manutenção",
        "Segundos do git pull do código. Não vale para o vault.",
    ),
    Ajuste(
        "JARVIS_RELATORIO_LINHAS",
        "40",
        "Manutenção",
        "Linhas finais do log no relatório, sem o texto da mensagem.",
    ),
    Ajuste(
        "JARVIS_RELATORIO_PASTA",
        "",
        "Manutenção",
        "Pasta do zip de diagnóstico. Vazia usa a pasta do usuário.",
    ),
)


def nomes():
    return tuple(item.nome for item in CATALOGO)


def render_env_exemplo():
    lines = [
        "# Exemplo de configuração do Jarvis. Não tem segredo.",
        "# Copie para ~/.jarvis/.env e preencha o que for usar.",
        "# Variável que já existe no ambiente não é coberta.",
        "# O arquivo ~/.jarvis/.env fica fora do git.",
        "# Gmail, Jira e GitHub ficam somente leitura. O Jarvis não envia e-mail.",
        "",
    ]
    grupo = None
    for item in CATALOGO:
        if item.grupo != grupo:
            if grupo is not None:
                lines.append("")
            grupo = item.grupo
            lines.append("# " + grupo)
        lines.append("# " + item.descricao)
        valor = "" if item.segredo else item.padrao
        linha = item.nome + "=" + valor
        if item.mostrar and not item.segredo:
            lines.append(linha)
        else:
            lines.append("# " + linha)
    return "\n".join(lines).rstrip() + "\n"


def render_tabela():
    linhas = [
        "| Variável | Padrão | Descrição |",
        "|---|---|---|",
    ]
    for item in CATALOGO:
        padrao = item.padrao or "vazio"
        linhas.append("| `" + item.nome + "` | `" + padrao + "` | " + item.descricao + " |")
    return "\n".join(linhas)
