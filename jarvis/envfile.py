"""Arquivo de ambiente local, fora do git.

O caminho padrão é ~/.jarvis/.env. Variável que já existe no processo
não é coberta. Segredos não vão para o repositório.
"""

import os
import platform
import re
import subprocess
from pathlib import Path

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RAW_RE = re.compile(r"^[A-Za-z0-9_./:@%+\-]*$")
SECRET_KEYS = frozenset(
    {"JIRA_TOKEN", "GMAIL_APP_PASSWORD", "TELEGRAM_BOT_TOKEN", "READWISE_TOKEN"}
)
MANAGED_ORDER = (
    "JARVIS_VAULT",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "READWISE_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
    "TELEGRAM_VOICE_REPLY",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_LIMITE",
    "JARVIS_CHECKIN",
    "JARVIS_CHECKIN_MORNING",
    "JARVIS_CHECKIN_EVENING",
    "JARVIS_CHECKIN_EVENING_AT",
    "JARVIS_LIVROS_PASTA",
    "JARVIS_VIDEOS_PASTA",
    "JARVIS_CURSOS_PASTA",
    "JARVIS_REVISAO_NOVOS",
    "JARVIS_REVISAO_PRIORIDADE",
)


def env_path(environ=None):
    from .ajustes import env_file

    return env_file(environ)


def load_env(path=None, environ=None):
    target = env_path() if path is None else Path(path)
    sink = os.environ if environ is None else environ
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    for key, value in parse_env(text).items():
        if key not in sink:
            sink[key] = value
    return True


def read_env(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    return parse_env(text)


def parse_env(text):
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not KEY_RE.match(key):
            continue
        values[key] = _unescape(value.strip())
    return values


def dump_env(values):
    lines = [
        "# Configuração local do Jarvis. Fora do git. Não commitar.",
        "# Gerado por python -m jarvis.setup. Rodar de novo edita.",
        "# Variável já definida no ambiente tem prioridade.",
        "",
    ]
    ordered = [key for key in MANAGED_ORDER if values.get(key)]
    extras = sorted(key for key in values if key not in MANAGED_ORDER and values.get(key))
    for key in ordered + extras:
        if not KEY_RE.match(key):
            continue
        lines.append(key + "=" + quote_value(str(values[key])))
    lines.append("")
    return "\n".join(lines)


def quote_value(value):
    if RAW_RE.match(value):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return '"' + escaped + '"'


def write_env(path, values, system=None, runner=None, user=None):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = dump_env(values)
    temporary = target.with_name(target.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, target)
    restrict_permissions(target, system=system, runner=runner, user=user)
    return target


def restrict_permissions(path, system=None, runner=None, user=None):
    target = Path(path)
    system = system or platform.system()
    if system != "Windows":
        os.chmod(target, 0o600)
        if target.parent.name == ".jarvis":
            try:
                os.chmod(target.parent, 0o700)
            except OSError:
                pass
        return True
    commands = windows_restrict_commands(target, user or _windows_user())
    execute = runner or _run
    ok = True
    for command in commands:
        try:
            result = execute(command, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            ok = False
            continue
        if getattr(result, "returncode", 1) != 0 and "/grant:r" in command:
            ok = False
    return ok


def windows_restrict_commands(path, user):
    quoted = str(path)
    return [
        ["icacls", quoted, "/inheritance:r"],
        ["icacls", quoted, "/grant:r", user + ":(R,W)"],
        ["icacls", quoted, "/remove:g", "*S-1-1-0", "*S-1-5-11", "*S-1-5-32-545"],
    ]


def permissions_restricted(path, system=None, acl_text=None):
    target = Path(path)
    system = system or platform.system()
    if system == "Windows":
        text = acl_text if acl_text is not None else _read_acl(target)
        if text is None:
            return False
        return acl_private(text)
    try:
        mode = target.stat().st_mode
    except OSError:
        return False
    return mode & 0o077 == 0


def acl_private(text):
    folded = text.casefold()
    blocked = (
        "everyone:",
        "everyone:(",
        "todos:",
        "todos:(",
        "builtin\\users",
        "authenticated users",
        "usuários autenticados",
    )
    return not any(item in folded for item in blocked)


def merge_env(existing, updates):
    merged = {
        key: value
        for key, value in existing.items()
        if KEY_RE.match(key) and str(value)
    }
    for key, value in updates.items():
        if not KEY_RE.match(key):
            continue
        if str(value):
            merged[key] = str(value)
        else:
            merged.pop(key, None)
    return merged


def _unescape(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        body = value[1:-1]
        if value[0] == "'":
            return body
        return _unescape_double(body)
    return value


def _unescape_double(body):
    chars = []
    index = 0
    while index < len(body):
        if body[index] == "\\" and index + 1 < len(body):
            nxt = body[index + 1]
            mapping = {"n": "\n", "r": "\r"}
            chars.append(mapping.get(nxt, nxt))
            index += 2
            continue
        chars.append(body[index])
        index += 1
    return "".join(chars)


def _windows_user():
    return os.environ.get("USERNAME") or Path.home().name


def _read_acl(path):
    try:
        result = subprocess.run(
            ["icacls", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout or ""


def _run(args, timeout=20):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
