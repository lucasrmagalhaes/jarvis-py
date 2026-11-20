import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from . import autostart, config
from .__version__ import __version__
from .deps import (
    OPTIONAL,
    REQUIRED,
    WAKE_PACKAGE,
    is_wake_package,
    missing_packages,
    package_ready,
    pip_commands,
    wakeword_hint,
    wakeword_usable,
)
from .envfile import env_path, permissions_restricted, restrict_permissions

OK = "OK  "
WARN = "AVISO"
FAIL = "FALHA"

JIRA_KEYS = ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN")
MAIL_KEYS = ("GMAIL_EMAIL", "GMAIL_APP_PASSWORD")
READWISE_KEYS = ("READWISE_TOKEN",)

results = []


def report(status, name, detail="", fix=""):
    results.append((status, name))
    print(f"[{status}] {name}" + (f": {detail}" if detail else ""))
    if fix and status != OK:
        print(f"         → {fix}")


def python_status(version):
    major = version[0]
    minor = version[1]
    micro = version[2] if len(version) > 2 else 0
    label = f"{major}.{minor}.{micro}"
    if (major, minor) >= (3, 10):
        return OK, label, ""
    return FAIL, label, "instale o Python 3.10 ou superior"


def check_python():
    status, detail, fix = python_status(sys.version_info)
    report(status, "Python", detail, fix)


def check_dependencies():
    missing = missing_packages(REQUIRED)
    if missing:
        report(
            FAIL,
            "Dependências",
            f"faltando: {', '.join(missing)}",
            "rode: python -m jarvis.doctor --corrigir",
        )
    else:
        report(OK, "Dependências", "todas presentes")

    absent = missing_packages(OPTIONAL)
    if absent:
        report(
            WARN,
            "Voz neural (opcional)",
            f"faltando: {', '.join(absent)}",
            _dica_voz_neural(),
        )


def _dica_voz_neural(sistema=None):
    host = platform.system() if sistema is None else sistema
    if host == "Windows":
        return "sem isso o Windows fica só com a voz robótica do SAPI"
    if host == "Darwin":
        return "sem isso a fala usa só a voz do sistema, pelo comando say"
    return "sem isso a fala fica só com a voz do sistema"


def check_numeros(environ=None):
    from .ajustes import numeros_invalidos

    invalidos = numeros_invalidos(environ)
    if not invalidos:
        return
    report(
        WARN,
        "Ajustes numéricos",
        f"valor que não é número válido em: {', '.join(invalidos)}. Usei o padrão",
        "corrija no arquivo de ambiente: só o número, sem unidade",
    )


def check_notas(directory, contar=None):
    from .routines import MAX_WALK

    try:
        total = _contar_notas(directory) if contar is None else contar(directory)
    except OSError:
        return
    if total > MAX_WALK:
        report(
            WARN,
            "Notas do vault",
            f"{total} notas, acima do teto de {MAX_WALK}. O que passa do teto fica fora da busca",
            "use JARVIS_PASTAS_IGNORADAS para tirar da busca as pastas que não são notas suas",
        )
        return
    report(OK, "Notas do vault", f"{total} notas ao alcance da busca{_fora_da_busca(directory, total)}")


def _fora_da_busca(directory, dentro):
    from .leitura import iter_markdown, pastas_ignoradas

    if not pastas_ignoradas():
        return ""
    try:
        todas = sum(1 for _path in iter_markdown(directory, ignorar=False))
    except OSError:
        return ""
    return f". {max(0, todas - dentro)} fora por JARVIS_PASTAS_IGNORADAS"


def _contar_notas(directory):
    from .leitura import iter_markdown

    return sum(1 for _path in iter_markdown(directory))


def check_wakeword():
    if wakeword_usable():
        report(OK, "Palavra de ativação", "backend ONNX")
        return
    report(WARN, "Palavra de ativação", "openwakeword indisponível", wakeword_hint())


def check_claude(which=None, runner=None):
    from .procutil import command_argv, resolve_executable

    finder = resolve_executable if which is None else which
    executable = finder(config.CLAUDE_BIN)
    if not executable:
        report(
            FAIL,
            "Claude Code",
            "não encontrado no PATH",
            "instale o Claude Code e garanta que o comando 'claude' funcione. "
            "Enquanto isso, pergunta livre busca no vault e os pedidos do dia seguem",
        )
        return
    report(OK, "Claude Code", executable)

    command = command_argv(executable, "-p", "--output-format", "json")
    if not command:
        report(
            FAIL,
            "Claude Code",
            "não encontrado no PATH",
            "instale o Claude Code e garanta que o comando 'claude' funcione. "
            "Enquanto isso, pergunta livre busca no vault e os pedidos do dia seguem",
        )
        return
    try:
        if runner is None:
            process = subprocess.run(
                command,
                input="Responda apenas: ok",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
        else:
            process = runner(command)
    except subprocess.TimeoutExpired:
        report(FAIL, "Login do Claude", "sem resposta em 90s", "rode 'claude' e faça login")
        return
    except OSError as error:
        report(FAIL, "Login do Claude", str(error), "verifique a instalação do Claude Code")
        return

    if process.returncode == 0:
        report(OK, "Login do Claude", "sessão ativa, consulta respondida")
    else:
        detail = (process.stderr or process.stdout).strip()[:160]
        report(
            FAIL,
            "Login do Claude",
            detail or f"código {process.returncode}",
            "rode 'claude' no terminal e faça login na sua conta",
        )


def hardware_skipped():
    return config.skip_hardware()


def check_microphone():
    if hardware_skipped():
        report(
            WARN,
            "Microfone",
            "checagem pulada neste ambiente",
            "rode de novo sem JARVIS_SKIP_HARDWARE para testar o microfone",
        )
        return
    try:
        import numpy as np
        import sounddevice as sd
    except (ImportError, OSError):
        report(
            WARN,
            "Microfone",
            "dependências de áudio ausentes",
            "rode: python -m jarvis.doctor --corrigir",
        )
        return

    try:
        device = sd.query_devices(kind="input")
    except Exception as error:
        report(
            FAIL,
            "Microfone",
            f"nenhum dispositivo de entrada ({type(error).__name__})",
            "conecte um microfone e verifique as configurações de som",
        )
        return
    report(OK, "Dispositivo de entrada", device["name"])

    try:
        with sd.InputStream(
            samplerate=config.SAMPLE_RATE, channels=1, dtype="float32", blocksize=1024
        ) as stream:
            frames, _ = stream.read(int(config.SAMPLE_RATE * 0.8))
        level = float(np.abs(frames).max())
    except Exception as error:
        report(
            FAIL,
            "Captura de áudio",
            f"{type(error).__name__}: {error}",
            _mic_permission_hint(),
        )
        return

    if level == 0.0:
        report(
            WARN,
            "Captura de áudio",
            "silêncio absoluto (0.0), provável permissão negada",
            _mic_permission_hint(),
        )
    else:
        report(OK, "Captura de áudio", f"nível detectado {level:.4f}")


def _mic_permission_hint():
    if platform.system() == "Darwin":
        return "Ajustes do Sistema → Privacidade e Segurança → Microfone → habilite o Terminal"
    if platform.system() == "Windows":
        return "Configurações → Privacidade → Microfone → permita apps de desktop"
    return "verifique a permissão de microfone do sistema"


def check_voice():
    from . import voice

    backends = [backend.__name__.lstrip("_") for backend in voice._backends()]
    report(OK, "Backends de voz", " → ".join(backends))


def check_transcription():
    from .stt import doctor_line

    status, detail, fix = doctor_line()
    levels = {"ok": OK, "warn": WARN, "fail": FAIL}
    report(levels.get(status, WARN), "Transcrição", detail, fix)


def check_models():
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        return
    from pathlib import Path

    cache = Path.home() / ".cache" / "huggingface" / "hub"
    whisper_cached = cache.exists() and any(cache.glob("*faster-whisper*"))
    wake_cached = True if not wakeword_usable() else _wake_models_present()
    if whisper_cached and wake_cached:
        report(OK, "Modelos", "Whisper e palavra de ativação em cache")
    else:
        pending = []
        if not whisper_cached:
            pending.append("Whisper (~460 MB)")
        if not wake_cached:
            pending.append("Hey Jarvis (~7 MB)")
        report(
            WARN,
            "Modelos",
            f"serão baixados no primeiro uso: {', '.join(pending)}",
            "a primeira execução precisa de internet e leva alguns minutos",
        )


def _wake_models_present():
    try:
        import openwakeword
        from pathlib import Path

        base = Path(openwakeword.__file__).parent / "resources" / "models"
        return base.exists() and any(base.glob("*hey_jarvis*"))
    except Exception:
        return False


def check_env_file(path=None):
    target = env_path() if path is None else Path(path)
    if not target.is_file():
        report(
            WARN,
            "Arquivo de ambiente",
            "ausente",
            "rode: python -m jarvis.setup",
        )
        return
    if permissions_restricted(target):
        report(OK, "Arquivo de ambiente", str(target))
        return
    report(
        WARN,
        "Arquivo de ambiente",
        str(target) + " está legível por outros usuários",
        "rode: python -m jarvis.setup",
    )


def integration_lines(env, github_state):
    return [
        _group_line("Jira", JIRA_KEYS, env),
        _group_line("Gmail", MAIL_KEYS, env),
        _group_line("Readwise", READWISE_KEYS, env),
        _github_line(github_state),
    ]


def _group_line(name, keys, env):
    present = [key for key in keys if str(env.get(key, "")).strip()]
    if name == "Readwise":
        if len(present) == len(keys):
            return (OK, name, "token presente", "")
        return (
            WARN,
            name,
            "token ausente",
            "opcional: defina READWISE_TOKEN no arquivo de ambiente. "
            "O diagnóstico não mostra o valor",
        )
    if len(present) == len(keys):
        detail = "configurado"
        if name == "Jira":
            host = _public_host(env.get("JIRA_URL", ""))
            if host:
                detail = "configurado em " + host
        return (OK, name, detail, "")
    if not present:
        return (OK, name, "não configurado", "")
    missing = [key for key in keys if key not in present]
    return (
        WARN,
        name,
        "incompleto, falta " + ", ".join(missing),
        "rode: python -m jarvis.setup",
    )


def _public_host(url):
    raw = str(url or "").strip()
    if "://" not in raw:
        return ""
    host = raw.split("://", 1)[1].split("/", 1)[0]
    if "@" in host:
        host = host.split("@", 1)[1]
    return host.split(":")[0]


def _github_line(state):
    if state == "ok":
        return (OK, "GitHub", "gh autenticado", "")
    if state == "missing":
        return (OK, "GitHub", "gh não instalado", "")
    if state == "anonymous":
        return (WARN, "GitHub", "gh sem login", "rode: gh auth login")
    return (WARN, "GitHub", "não foi possível consultar o gh", "rode: gh auth status")


def check_destaques():
    pasta = config.destaques_pasta() or "Leituras/Destaques"
    try:
        entrada = config.destaques_entrada()
        pronta = entrada.is_dir()
    except OSError:
        pronta = False
    detalhe = "pasta " + pasta
    detalhe += ". entrada pronta" if pronta else ". entrada ausente"
    try:
        import pypdf  # noqa: F401

        detalhe += ". pypdf presente"
        report(OK, "Destaques", detalhe)
    except ImportError:
        detalhe += ". pypdf ausente"
        report(
            WARN,
            "Destaques",
            detalhe + ". anotações de PDF ficam de fora",
            "pip install pypdf",
        )


def check_estudo_midia():
    pasta = config.estudo_midia_pasta() or "Estudos/Mídia"
    try:
        entrada = config.midia_entrada()
        pronta = entrada.is_dir()
    except OSError:
        pronta = False
    detalhe = "pasta " + pasta
    detalhe += ". entrada pronta" if pronta else ". entrada ausente"
    faltas = []
    try:
        import youtube_transcript_api  # noqa: F401

        detalhe += ". youtube-transcript-api presente"
    except ImportError:
        detalhe += ". youtube-transcript-api ausente"
        faltas.append("pip install youtube-transcript-api")
    from .estudo_midia import ffmpeg_disponivel

    if ffmpeg_disponivel():
        detalhe += ". ffmpeg presente"
    else:
        detalhe += ". ffmpeg ausente"
        faltas.append("instale o ffmpeg e deixe o comando no PATH, inclusive ffmpeg.exe")
    if faltas:
        report(
            WARN,
            "Estudo de mídia",
            detalhe,
            ". ".join(faltas),
        )
        return
    report(OK, "Estudo de mídia", detalhe)


def check_integrations(github_state=None, env=None):
    source = os.environ if env is None else env
    if github_state is None:
        from .external import github_auth_state

        github_state = github_auth_state()
    for status, name, detail, fix in integration_lines(source, github_state):
        report(status, name, detail, fix)


def check_autostart(service=None):
    service = service or autostart.for_current_process()
    state = service.status()
    if state.level == "warn":
        report(WARN, "Início automático", state.detail, state.fix)
        return
    report(OK, "Início automático", state.detail)


def check_vault():
    from .vault import Vault

    directory = config.vault_dir()
    if directory is None:
        report(
            WARN,
            "Vault",
            "JARVIS_VAULT não definido. Sem essa pasta eu não leio as notas.",
            "rode: python -m jarvis.setup",
        )
        return
    vault = Vault(
        directory,
        remote=config.vault_remote(),
        branch=config.vault_branch(),
        sync=config.vault_sync_enabled(),
        timeout=config.doctor_git_timeout(),
        git_bin=config.git_bin(),
    )
    levels = {"ok": OK, "warn": WARN, "fail": FAIL}
    checks = vault.diagnose()
    for item in checks:
        report(levels[item.level], item.name, item.detail, item.fix)
    if checks and checks[0].level != "fail":
        check_notas(vault.path)


def telegram_report(token, user_id, raw_user, probe):
    if not token and not raw_user:
        return WARN, "desligado", "opcional: python -m jarvis.setup"
    if token and user_id is None:
        detail = "usuário autorizado inválido" if raw_user else "token sem usuário autorizado"
        return (
            FAIL,
            detail,
            "defina TELEGRAM_ALLOWED_USER_ID com o seu ID numérico. Sem isso o bot não conecta.",
        )
    if not token:
        return (
            WARN,
            "usuário sem token",
            "defina TELEGRAM_BOT_TOKEN ou apague TELEGRAM_ALLOWED_USER_ID",
        )
    try:
        me = probe(token) if probe else _probe_telegram(token)
    except Exception as error:
        from .telegram_api import redact

        return WARN, redact(error, token)[:180], "confira o token e a rede"
    username = ""
    if isinstance(me, dict):
        username = str(me.get("username") or "")
    if username:
        return OK, f"token presente, @{username}, só o usuário {user_id}", ""
    return OK, f"token presente, só o usuário {user_id}", ""


def _probe_telegram(token):
    from .telegram_api import Api

    return Api(token).call("getMe", {}, timeout=8)


def check_telegram():
    token = config.telegram_token()
    raw_user = config.telegram_user_raw()
    user_id = config.telegram_allowed_user_id()
    status, detail, fix = telegram_report(token, user_id, raw_user, None)
    report(status, "Telegram", detail, fix)
    raw_chat = config.telegram_chat_raw()
    if raw_chat and config.telegram_chat_id() is None:
        report(
            FAIL,
            "Telegram conversa",
            "ID da conversa inválido",
            "defina TELEGRAM_CHAT_ID com o número da conversa privada, ou deixe vazio",
        )
        return
    if not config.telegram_ready():
        return
    if config.telegram_voice_reply():
        report(OK, "Telegram áudio", "resposta em áudio ligada")
    else:
        report(OK, "Telegram áudio", "resposta só em texto")
    from .estudo_midia import ffmpeg_disponivel

    if not ffmpeg_disponivel():
        report(
            WARN,
            "ffmpeg",
            "ausente",
            "notas de voz do Telegram precisam do ffmpeg no PATH, inclusive ffmpeg.exe",
        )


def check_radar():
    if not config.radar_enabled():
        report(
            WARN,
            "Alertas",
            "desligados por JARVIS_RADAR=off",
            "sem isso eu não aviso PR, issue nem e-mail importante",
        )
        return
    pause = config.radar_cooldown()
    report(
        OK,
        "Alertas",
        f"PR, Jira e e-mail importante, no máximo um aviso a cada {pause}s",
    )


def check_cerebro(transport=None):
    from .cerebro import report_status

    status, detail, fix = report_status(transport)
    levels = {"ok": OK, "warn": WARN, "fail": FAIL}
    report(levels.get(status, WARN), "Cérebro", detail, fix)


def check_ollama(which=None):
    finder = shutil.which if which is None else which
    binary = finder("ollama")
    if binary:
        report(OK, "Ollama", "comando encontrado")
        return
    report(
        WARN,
        "Ollama",
        "opcional, comando ausente",
        "instale o Ollama e deixe o comando ollama no PATH se quiser um modelo local",
    )


def check_digest():
    if not config.digest_enabled():
        report(OK, "Resumo no Telegram", "desligado. JARVIS_DIGEST=on envia no domingo à noite")
        return
    hour, minute = config.digest_at()
    when = f"domingo às {hour:02d}:{minute:02d}, só títulos e subtítulos"
    if not config.telegram_ready():
        report(
            WARN,
            "Resumo no Telegram",
            "ligado, mas o Telegram não está pronto. " + when,
            "defina TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID",
        )
        return
    report(OK, "Resumo no Telegram", when)


def check_briefing():
    if not config.briefing_telegram():
        report(
            OK,
            "Bom dia no Telegram",
            "desligado. JARVIS_BRIEFING_TELEGRAM=on envia o bom dia",
        )
        return
    hour, minute = config.briefing_at()
    when = f"uma vez por dia, a partir de {hour:02d}:{minute:02d}"
    if not config.telegram_ready():
        report(
            WARN,
            "Bom dia no Telegram",
            "ligado, mas o Telegram não está pronto. " + when,
            "defina TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID",
        )
        return
    report(OK, "Bom dia no Telegram", when + ". Só leitura, sem enviar e-mail")


def check_lembrete_nota():
    if not config.lembrete_nota():
        report(
            OK,
            "Lembrete de nota",
            "desligado. JARVIS_LEMBRETE_NOTA=on envia um título antigo no Telegram",
        )
        return
    hour, minute = config.lembrete_nota_at()
    when = f"uma vez por dia, a partir de {hour:02d}:{minute:02d}. Nota privada fica de fora"
    if not config.telegram_ready():
        report(
            WARN,
            "Lembrete de nota",
            "ligado, mas o Telegram não está pronto. " + when,
            "defina TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID",
        )
        return
    report(OK, "Lembrete de nota", when)


def check_revisao_semanal():
    if not config.revisao_semanal():
        report(
            OK,
            "Revisão semanal",
            "desligada. JARVIS_REVISAO_SEMANAL=on lembra no domingo, sem texto de nota",
        )
        return
    hour, minute = config.revisao_semanal_at()
    when = (
        f"domingo a partir de {hour:02d}:{minute:02d}. "
        "Só o convite, sem texto de nota"
    )
    if not config.telegram_ready():
        report(
            WARN,
            "Revisão semanal",
            "ligada, mas o Telegram não está pronto. " + when,
            "defina TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID",
        )
        return
    report(OK, "Revisão semanal", when)


def check_toque_sequencia():
    if not config.toque_sequencia():
        report(
            OK,
            "Toque da sequência",
            "desligado. JARVIS_TOQUE_SEQUENCIA=on avisa à noite se o dia não teve revisão",
        )
        return
    hour, minute = config.toque_sequencia_at()
    when = (
        f"a partir de {hour:02d}:{minute:02d}, sem texto de nota"
    )
    if not config.telegram_ready():
        report(
            WARN,
            "Toque da sequência",
            "ligado, mas o Telegram não está pronto. " + when,
            "defina TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID",
        )
        return
    report(OK, "Toque da sequência", when)


def check_sessao():
    minutos = config.sessao_minutos()
    pausa = config.sessao_pausa()
    if config.sessao_nota() == "diario":
        destino = "grava na nota do dia, depois do sim"
    else:
        destino = "grava na nota do tema, depois do sim"
    if config.sessao_silencio():
        silencio = "adiando briefing, lembrete e resumo"
    else:
        silencio = "avisos seguem durante a sessão"
    base = f"{minutos} min, pausa de {pausa} min, {destino}, {silencio}"
    if not config.sessao_telegram():
        report(OK, "Sessão de estudo", base + ". Telegram desligado")
        return
    extra = "Telegram no fim, sem texto de nota"
    if not config.telegram_ready():
        report(
            WARN,
            "Sessão de estudo",
            base + ". " + extra + ", mas o Telegram não está pronto",
            "defina TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_ID",
        )
        return
    report(OK, "Sessão de estudo", base + ". " + extra)


def check_modo_prazo():
    minutos = max(1, int(config.modo_prazo()) // 60)
    report(
        OK,
        "Modo de conversa",
        f"cancela ou para encerra. Sem uso, encerra em {minutos} min.",
    )


def check_checkins():
    if not config.checkin_enabled():
        report(WARN, "Check-ins", "desligados por JARVIS_CHECKIN=off")
        return
    hour, minute = config.checkin_evening_at()
    bits = ["resumo da semana no domingo"]
    if config.checkin_morning():
        bits.append("briefing no primeiro arranque do dia")
    if config.checkin_evening():
        bits.append(f"resumo do fim do dia às {hour:02d}:{minute:02d}")
    report(OK, "Check-ins", "; ".join(bits))


def check_busca():
    modo = config.busca_modo()
    if config.cerebro_raw() == "ollama" and modo != "palavras":
        report(
            OK,
            "Busca",
            "modo " + modo + ". Embeddings pelo Ollama nesta máquina. O índice fica em ~/.jarvis.",
        )
        return
    try:
        import sentence_transformers  # noqa: F401

        presente = True
    except ImportError:
        presente = False
    if modo == "palavras":
        extra = "sentence-transformers presente" if presente else "sentence-transformers ausente"
        report(
            OK,
            "Busca",
            "palavras. " + extra + ". semantica e hibrida ficam desligadas até o opt-in.",
        )
        return
    if presente:
        report(
            OK,
            "Busca",
            "modo " + modo + ". sentence-transformers presente. O índice fica em ~/.jarvis.",
        )
        return
    report(
        WARN,
        "Busca",
        "modo " + modo + ", sem sentence-transformers",
        "pip install sentence-transformers",
    )


def check_consult():
    port = config.consult_port()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        report(
            WARN,
            "Consulta",
            f"porta {port} ocupada",
            "use JARVIS_CONSULT_PORT para escolher outra",
        )
        return
    finally:
        probe.close()
    report(
        OK,
        "Consulta",
        f"python -m jarvis.consult na porta {port}, só em 127.0.0.1",
    )


def check_port():
    if not config.PANEL_ENABLED:
        report(WARN, "Painel", "desativado por JARVIS_PANEL=off")
        return
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", config.PANEL_PORT))
        report(
            OK,
            "Painel",
            f"porta {config.PANEL_PORT} livre, somente 127.0.0.1. Nunca exponha esta porta.",
        )
    except OSError:
        report(
            WARN,
            "Painel",
            f"porta {config.PANEL_PORT} ocupada",
            "use JARVIS_PANEL_PORT para escolher outra",
        )
    finally:
        probe.close()


def cabecalho():
    return (
        "Checklist do JARVIS "
        + __version__
        + " ("
        + platform.system()
        + " "
        + platform.release()
        + ")"
    )


def check_version():
    report(OK, "Versão", __version__)


def run():
    results.clear()
    print("\n" + cabecalho() + "\n")
    check_version()
    check_python()
    check_dependencies()
    check_wakeword()
    check_env_file()
    check_numeros()
    check_integrations()
    check_destaques()
    check_estudo_midia()
    check_autostart()
    check_claude()
    check_cerebro()
    check_ollama()
    check_vault()
    check_telegram()
    check_checkins()
    check_digest()
    check_briefing()
    check_lembrete_nota()
    check_revisao_semanal()
    check_toque_sequencia()
    check_sessao()
    check_modo_prazo()
    check_radar()
    check_microphone()
    check_voice()
    check_transcription()
    check_models()
    check_port()
    check_consult()
    check_busca()

    failures = [name for status, name in results if status == FAIL]
    warnings = [name for status, name in results if status == WARN]
    print()
    if failures:
        print(f"Pendências que impedem o funcionamento: {', '.join(failures)}")
        return 1
    if warnings:
        print(f"Tudo pronto, com ressalvas: {', '.join(warnings)}")
        return 0
    print("Tudo pronto, senhor. Rode: python -m jarvis.main ou python -m jarvis.chat")
    return 0


ENV_STUB = (
    "# Arquivo local do Jarvis. Fora do git.\n"
    "# Sem chaves ainda. Rode: python -m jarvis.setup\n"
)

HELP = """\
Uso:
  python -m jarvis.doctor
  python -m jarvis.doctor --corrigir

Sem argumentos, só diagnostica. --corrigir cria o arquivo de ambiente se faltar,
restringe a permissão dele e instala dependência ausente.
Confere o código de saída do pip e se o pacote realmente importa. Se o pip falhar,
a frase diz o que ficou de fora e o próximo comando.
A palavra de ativação usa ONNX e não segura o restante. Sem ela, use python -m jarvis.chat.
Não grava chave, não clona o vault, não envia e-mail e não mexe em .obsidian.
"""


def apply_fixes(env_file=None, missing=None, installer=None, probe=None):
    """Correções seguras. Não grava segredo e não chama a rede, salvo o pip das dependências."""
    actions = []
    target = env_path() if env_file is None else Path(env_file)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, ENV_STUB.encode("utf-8"))
        finally:
            os.close(descriptor)
        restrict_permissions(target)
        actions.append(
            "Criei o arquivo de ambiente, vazio de chaves. "
            "Rode python -m jarvis.setup para apontar o vault."
        )
    elif not permissions_restricted(target):
        restrict_permissions(target)
        if permissions_restricted(target):
            actions.append("Restringi o arquivo de ambiente ao seu usuário.")
        else:
            actions.append(
                "Não consegui restringir o arquivo de ambiente. "
                "Rode python -m jarvis.setup."
            )
    install = installer if installer is not None else _pip_install
    check = probe if probe is not None else package_ready
    for packages in _groups_to_install(missing):
        if not packages:
            continue
        actions.append(_install_group(packages, install, check))
    if not actions:
        actions.append("Nada automático pendente. O que falta pede a sua mão.")
    return actions


def _groups_to_install(missing):
    if missing is not None:
        return [list(missing)] if missing else []
    groups = [[package] for package in missing_packages(REQUIRED)]
    groups.extend([package] for package in missing_packages(OPTIONAL))
    if not wakeword_usable():
        groups.append([WAKE_PACKAGE])
    return groups


def _install_group(packages, install, probe):
    try:
        result = install(list(packages))
    except Exception:
        result = None
    exit_code = _exit_code(result)
    ready = [package for package in packages if probe(package)]
    pending = [package for package in packages if package not in ready]
    return describe_install(packages, exit_code, ready, pending)


def _exit_code(result):
    if result is None:
        return None
    if isinstance(result, bool):
        return 0 if result else 1
    if isinstance(result, int):
        return result
    return getattr(result, "returncode", 1)


def describe_install(packages, exit_code, ready, pending):
    """Diz o que o pip fez e o que passou a importar. Não trata falha como sucesso."""
    requested = ", ".join(packages)
    if not pending and exit_code == 0:
        return "Instalei as dependências: " + requested + "."
    if not pending:
        imported = ", ".join(ready)
        if exit_code is None:
            return "O pip não chegou a terminar, e estes pacotes importam: " + imported + "."
        return (
            "O pip saiu com código "
            + str(exit_code)
            + ", e estes pacotes importam: "
            + imported
            + "."
        )
    followup = _install_followup(pending)
    if ready:
        text = "Instalei: " + ", ".join(ready) + ". Continua de fora: " + ", ".join(pending) + "."
        text += _exit_clause(exit_code)
        return text + " " + followup
    if exit_code not in (0, None):
        return (
            "Não instalei as dependências ("
            + ", ".join(pending)
            + "). O pip saiu com código "
            + str(exit_code)
            + ". "
            + followup
        )
    if exit_code is None:
        return (
            "Não instalei as dependências ("
            + requested
            + "). O pip não chegou a terminar. "
            + followup
        )
    return (
        "O pip terminou sem erro, mas estes pacotes não importam: "
        + ", ".join(pending)
        + ". "
        + followup
    )


def _exit_clause(exit_code):
    if exit_code not in (0, None):
        return " O pip saiu com código " + str(exit_code) + "."
    if exit_code is None:
        return " O pip não chegou a terminar."
    return ""


def _install_followup(packages):
    if packages and all(is_wake_package(package) for package in packages):
        return wakeword_hint()
    return "Rode python -m jarvis.setup."


def _pip_install(packages):
    code = 0
    ran = False
    for command in pip_commands(packages, sys.executable, config.PROJECT_ROOT):
        ran = True
        current = _run_pip(command)
        if current is None:
            return None
        if current != 0:
            code = current
    return code if ran else 0


def _run_pip(command):
    timeout = 600 if _slow_pip(command) else 180
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return process.returncode


def _slow_pip(command):
    joined = " ".join(command)
    return "--no-deps" in command or "requirements-wake" in joined


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(item in {"-h", "--help"} for item in args):
        print(HELP)
        return 0
    unknown = [item for item in args if item != "--corrigir"]
    if unknown:
        print("Não entendi o argumento: " + " ".join(unknown))
        print(HELP)
        return 2
    if "--corrigir" in args:
        print("Correções automáticas\n")
        for line in apply_fixes():
            print(line)
        print()
    return run()


if __name__ == "__main__":
    sys.exit(main())
