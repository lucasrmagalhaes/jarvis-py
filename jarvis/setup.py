"""Instalador guiado do Jarvis.

python -m jarvis.setup
python -m jarvis.setup --desativar-inicio
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import autostart
from .config import vault_remote
from .deps import (
    OPTIONAL,
    REQUIRED,
    core_pip_args,
    missing_packages,
    requirements_without_wake,
    wake_dep_pip_args,
    wake_pip_args,
    wakeword_hint,
    wakeword_usable,
)
from .envfile import (
    SECRET_KEYS,
    env_path,
    merge_env,
    read_env,
    write_env,
)
from .external import github_auth_state

OPTIONAL_PROMPTS = (
    ("JIRA_URL", "Endereço do Jira", False),
    ("JIRA_EMAIL", "E-mail da conta Atlassian", False),
    ("JIRA_TOKEN", "Token de API do Jira", True),
    ("GMAIL_EMAIL", "Conta Gmail", False),
    ("GMAIL_APP_PASSWORD", "Senha de app do Gmail", True),
    ("TELEGRAM_BOT_TOKEN", "Token do bot do Telegram", True),
    ("TELEGRAM_ALLOWED_USER_ID", "ID numérico do seu usuário no Telegram", False),
    ("TELEGRAM_VOICE_REPLY", "Resposta em áudio no Telegram (on ou off)", False),
    ("TELEGRAM_CHAT_ID", "ID da conversa privada no Telegram (Enter usa o do usuário)", False),
    ("TELEGRAM_LIMITE", "Mensagens por minuto no Telegram (Enter usa 20)", False),
    ("JARVIS_CHECKIN", "Check-ins do dia (on ou off)", False),
    ("JARVIS_CHECKIN_MORNING", "Briefing no primeiro arranque (on ou off)", False),
    ("JARVIS_CHECKIN_EVENING", "Resumo do fim do dia (on ou off)", False),
    ("JARVIS_CHECKIN_EVENING_AT", "Horário do resumo (HH:MM)", False),
    ("READWISE_TOKEN", "Token do Readwise", True),
)

INTRO = (
    "Instalação do JARVIS\n"
    "\n"
    "Vou checar as dependências, o clone do vault e as chaves opcionais.\n"
    "As chaves ficam em um arquivo local, fora do git, com permissão só sua.\n"
    "Telegram e check-ins do dia também entram aqui, se você quiser.\n"
    "Rodar este comando de novo edita a configuração."
)


class Choices:
    def __init__(self, install_deps, vault_path, clone, values, autostart_choice):
        self.install_deps = install_deps
        self.vault_path = vault_path
        self.clone = clone
        self.values = values
        self.autostart_choice = autostart_choice


class SetupContext:
    def __init__(
        self,
        root,
        home,
        environ,
        env_file,
        python,
        runner,
        autostart_service,
        remote,
        has_git=True,
        github_state="missing",
        missing_required=None,
        missing_optional=None,
        python_ok=True,
        python_label="",
        claude_present=True,
        wake_ready=None,
    ):
        self.root = Path(root)
        self.home = Path(home)
        self.environ = environ
        self.env_path = Path(env_file)
        self.python = python
        self.runner = runner
        self.autostart = autostart_service
        self.remote = remote
        self.has_git = has_git
        self.github_state = github_state
        self.missing_required = missing_required or (lambda: [])
        self.missing_optional = missing_optional or (lambda: [])
        self.python_ok = python_ok
        self.python_label = python_label
        self.claude_present = claude_present
        self.wake_ready = wakeword_usable if wake_ready is None else wake_ready

    @classmethod
    def from_here(cls):
        from .config import CLAUDE_BIN, PROJECT_ROOT, git_bin as git_bin_config

        version = sys.version_info
        git_bin = git_bin_config()
        return cls(
            root=PROJECT_ROOT,
            home=Path.home(),
            environ=os.environ,
            env_file=env_path(),
            python=sys.executable,
            runner=autostart.default_runner,
            autostart_service=autostart.for_current_process(),
            remote=vault_remote(),
            has_git=shutil.which(git_bin) is not None,
            github_state=github_auth_state(),
            missing_required=lambda: missing_packages(REQUIRED),
            missing_optional=lambda: missing_packages(OPTIONAL),
            python_ok=version >= (3, 10),
            python_label=f"{version.major}.{version.minor}.{version.micro}",
            claude_present=shutil.which(CLAUDE_BIN) is not None,
            wake_ready=wakeword_usable,
        )


class Console:
    def __init__(self, input_fn=None, output_fn=None, secret_fn=None):
        self._input = input_fn or input
        self._output = output_fn or print
        self._secret = secret_fn or _hidden_input

    def say(self, text=""):
        self._output(text)

    def ask(self, prompt):
        try:
            return self._input(prompt + ": ").strip()
        except EOFError:
            return ""

    def secret(self, prompt):
        try:
            value = self._secret(prompt + ": ")
        except EOFError:
            return ""
        except KeyboardInterrupt:
            raise
        except Exception:
            self.say("Sem terminal oculto. O valor vai aparecer ao digitar.")
            return self.ask(prompt)
        return (value or "").strip()

    def confirm(self, prompt, default=False):
        hint = "S/n" if default else "s/N"
        entered = self.ask(prompt + " (" + hint + ")")
        if entered == "":
            return default
        return entered.casefold() in {"s", "sim", "y", "yes"}


def main(argv=None, context=None, console=None):
    parser = argparse.ArgumentParser(
        prog="python -m jarvis.setup",
        description="Instala e configura o Jarvis nesta máquina.",
    )
    parser.add_argument(
        "--desativar-inicio",
        action="store_true",
        help="remove o início automático no login e encerra",
    )
    args = parser.parse_args(argv)
    active = context or SetupContext.from_here()
    output = console or Console()
    if args.desativar_inicio:
        result = active.autostart.disable()
        output.say(result.message)
        return 0 if result.ok else 1
    try:
        return run_interactive(active, output)
    except KeyboardInterrupt:
        output.say("")
        output.say("Instalação cancelada.")
        return 130


def run_interactive(context, console):
    choices = collect_choices(console, context)
    return apply_setup(console, context, choices)


def collect_choices(console, context):
    console.say(INTRO)
    console.say("")
    if context.python_ok:
        label = context.python_label or "disponível"
        console.say("Python " + label + " ok.")
    else:
        console.say(
            "Python "
            + (context.python_label or "atual")
            + " é anterior ao 3.10. Instale uma versão mais nova."
        )
    missing = list(context.missing_required())
    optional = list(context.missing_optional())
    if missing:
        console.say("Dependências faltando: " + ", ".join(missing))
    if optional:
        console.say("Opcionais faltando: " + ", ".join(optional))
    if missing or optional:
        install_deps = console.confirm(
            "Instalar dependências agora?",
            default=bool(missing),
        )
    else:
        console.say("Dependências presentes.")
        install_deps = False
    if context.claude_present:
        console.say(
            "Claude Code encontrado. O login continua em python -m jarvis.doctor."
        )
    else:
        console.say(
            "Claude Code não está no PATH. Instale e faça login antes de usar o Jarvis."
        )

    current = _current_values(context)
    console.say("")
    console.say("Vault pessoal")
    default_vault = current.get("JARVIS_VAULT") or str(
        context.home / "Documents" / "vault-de-notas"
    )
    typed = console.ask(
        "Caminho do clone [" + default_vault + "] (limpar remove)"
    )
    vault_path, clone = _resolve_vault(console, context, typed, default_vault, current)

    console.say("")
    console.say("Chaves opcionais. Enter mantém ou pula. limpar remove.")
    values = {"JARVIS_VAULT": vault_path}
    for key, label, secret in OPTIONAL_PROMPTS:
        values[key] = _prompt_key(console, label, secret, current.get(key, ""))

    console.say(_github_line(context.github_state))
    want_auto = console.confirm(
        "Iniciar o Jarvis ao entrar no computador?",
        default=False,
    )
    autostart_choice = None
    if want_auto:
        autostart_choice = True
    elif context.autostart.status().enabled:
        if console.confirm("Desativar o início automático?", default=True):
            autostart_choice = False
    return Choices(install_deps, vault_path, clone, values, autostart_choice)


def apply_setup(console, context, choices):
    code = 0
    if choices.install_deps:
        if not _install_requirements(console, context):
            code = 1
    if choices.clone:
        invalid = not choices.vault_path or is_inside(context.root, choices.vault_path)
        if invalid or not context.has_git:
            console.say("Não cloniei o vault: caminho inválido ou git ausente.")
            choices.values["JARVIS_VAULT"] = _keep_previous_repo(context)
            code = 1
        else:
            ok, detail = clone_vault(
                choices.vault_path,
                context.remote,
                context.runner,
            )
            if ok:
                console.say("Vault clonado.")
            else:
                console.say(
                    "Não consegui clonar o vault: "
                    + scrub_text(detail, _secret_values(choices, context))
                )
                console.say(
                    "O repositório é privado. Autentique o git e rode o instalador de novo. "
                    "Se a pasta ficou pela metade, apague ela antes."
                )
                choices.values["JARVIS_VAULT"] = _keep_previous_repo(context)
                code = 1
    elif choices.vault_path and describe_vault_path(choices.vault_path) == "absent":
        console.say("Sem clone. O vault fica desligado até a pasta existir.")
        choices.values["JARVIS_VAULT"] = ""

    existing = read_env(context.env_path)
    merged = merge_env(existing, choices.values)
    try:
        write_env(context.env_path, merged)
    except OSError as error:
        console.say("Não consegui gravar o arquivo de ambiente: " + str(error))
        return 1
    _announce(console, choices.values)
    if choices.autostart_choice is True:
        result = context.autostart.enable()
        console.say(result.message)
        if not result.ok and not result.unsupported:
            code = 1
    elif choices.autostart_choice is False:
        result = context.autostart.disable()
        console.say(result.message)
        if not result.ok:
            code = 1
    console.say("")
    console.say("Configuração salva em " + str(context.env_path))
    console.say(
        "Para desligar o início automático: python -m jarvis.setup --desativar-inicio"
    )
    console.say("Diagnóstico: python -m jarvis.doctor")
    return code


def describe_vault_path(path):
    folder = Path(path)
    if not folder.exists():
        return "absent"
    if (folder / ".git").is_dir():
        return "repo"
    try:
        next(folder.iterdir())
    except StopIteration:
        return "empty"
    except OSError:
        return "occupied"
    return "occupied"


def is_inside(parent, child):
    from .paths import esta_dentro

    return esta_dentro(child, parent)


def clone_vault(path, remote, runner):
    if not str(remote or "").strip():
        return False, "JARVIS_VAULT_REMOTE está vazio. Não há repositório para clonar."
    folder = Path(path)
    try:
        folder.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return False, str(error)
    from .procutil import command_argv

    command = command_argv("git", "clone", remote, str(folder))
    if command is None:
        return False, "Não encontrei o git. Instale o git e deixe-o no PATH."
    try:
        result = runner(command, timeout=300)
    except subprocess.TimeoutExpired:
        return False, "o clone passou do tempo"
    except OSError as error:
        return False, str(error)
    if getattr(result, "returncode", 1) != 0:
        detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "")
        detail = detail.strip() or "git clone falhou"
        return False, detail
    if not (folder / ".git").is_dir():
        return False, "o clone terminou sem a pasta .git"
    return True, ""


def scrub_text(text, secrets):
    cleaned = re.sub(r"://[^/\s:@]+:[^/\s@]+@", "://", text or "")
    for secret in secrets:
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "***")
    return " ".join(cleaned.split())[:240]


def _resolve_vault(console, context, typed, default_vault, current):
    if typed.strip().casefold() == "limpar":
        console.say("Vault desligado.")
        return "", False
    vault_path = str(Path(typed.strip() or default_vault).expanduser())
    if is_inside(context.root, vault_path):
        console.say("O vault não pode ficar dentro da pasta do Jarvis.")
        return _keep_or_clear(console, current, vault_path)
    state = describe_vault_path(vault_path)
    if state == "repo":
        console.say("Clone já existe. Vou usar esta pasta.")
        return vault_path, False
    if not context.has_git:
        console.say("git não encontrado. Instale o git para clonar o vault.")
        if state == "occupied":
            return _occupied_choice(console, vault_path, current)
        return _keep_or_clear(console, current, vault_path)
    if state in {"absent", "empty"}:
        remote = str(context.remote or "").strip()
        if not remote:
            console.say(
                "JARVIS_VAULT_REMOTE está vazio. "
                "Não há repositório padrão para clonar. "
                "Aponte uma pasta que já seja um clone, ou grave o remoto no arquivo de ambiente."
            )
            return _keep_or_clear(console, current, vault_path)
        clone = console.confirm(
            "Clonar " + remote + " nesta pasta?",
            default=True,
        )
        return vault_path, clone
    return _occupied_choice(console, vault_path, current)


def _occupied_choice(console, vault_path, current):
    console.say("Esta pasta não é um repositório git. Não vou clonar por cima.")
    if console.confirm("Usar esta pasta mesmo assim?", default=False):
        return vault_path, False
    return _keep_or_clear(console, current, vault_path)


def _keep_or_clear(console, current, rejected):
    path, clone = _previous_repo(current, rejected)
    if path:
        console.say("Mantive o clone anterior.")
    return path, clone


def _previous_repo(current, rejected):
    previous = current.get("JARVIS_VAULT", "")
    if (
        previous
        and previous != rejected
        and describe_vault_path(previous) == "repo"
    ):
        return previous, False
    return "", False


def _prompt_key(console, label, secret, current):
    if secret:
        hint = (
            "já definido, Enter mantém, limpar remove"
            if current
            else "Enter pula, não aparece ao digitar"
        )
        entered = console.secret(label + " (" + hint + ")")
    elif current:
        entered = console.ask(label + " [" + current + "]")
        if entered == "":
            return current
    else:
        entered = console.ask(label + " (Enter pula)")
    if entered.strip().casefold() == "limpar":
        return ""
    if entered.strip() == "":
        return current
    return _strip_wrapping_quotes(entered.strip())


def _strip_wrapping_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _current_values(context):
    current = {}
    if context.env_path.is_file():
        current.update(read_env(context.env_path))
    managed = {"JARVIS_VAULT"} | {key for key, _label, _secret in OPTIONAL_PROMPTS}
    for key in managed:
        value = str(context.environ.get(key, "")).strip()
        if value:
            current[key] = value
    return current


def _install_requirements(console, context):
    console.say("Instalando dependências...")
    code, detail = _pip_result(context, core_pip_args(context.python, context.root))
    used_fallback = False
    if code != 0:
        fallback = _write_core_requirements(context)
        try:
            code, detail = _pip_result(
                context, [context.python, "-m", "pip", "install", "-r", fallback]
            )
        finally:
            Path(fallback).unlink(missing_ok=True)
        used_fallback = True
    if code != 0:
        _say_pip_failure(console, context, detail, code)
        return False
    still = list(context.missing_required())
    if still:
        console.say("Ainda faltam: " + ", ".join(still))
        return False
    if used_fallback or not context.wake_ready():
        wake_code, wake_detail = _install_wakeword(context)
        if wake_code != 0 or not context.wake_ready():
            console.say(
                "Instalei o restante das dependências. A palavra de ativação não entrou. "
                + wakeword_hint()
            )
            if wake_code not in (0, None):
                _say_pip_tail(console, context, wake_detail)
            return True
    console.say("Dependências instaladas.")
    return True


def _install_wakeword(context):
    code, detail = _pip_result(context, wake_dep_pip_args(context.python, context.root))
    if code != 0:
        return code, detail
    return _pip_result(context, wake_pip_args(context.python, context.root))


def _write_core_requirements(context):
    source = Path(context.root) / "requirements.txt"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        text = ""
    handle = tempfile.NamedTemporaryFile(
        "w", suffix="-jarvis-requirements.txt", delete=False, encoding="utf-8"
    )
    try:
        handle.write(requirements_without_wake(text))
    finally:
        handle.close()
    return handle.name


def _pip_result(context, args):
    try:
        result = context.runner(args, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    code = getattr(result, "returncode", 1)
    detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "")
    return code, detail


def _say_pip_failure(console, context, detail, code):
    if code is None:
        console.say("A instalação falhou: " + scrub_text(detail or "", _environ_secrets(context))[:200])
        return
    console.say("A instalação falhou.")
    _say_pip_tail(console, context, detail)


def _say_pip_tail(console, context, detail):
    tail = (detail or "").strip().splitlines()
    if tail:
        console.say(scrub_text(tail[-1], _environ_secrets(context))[:200])


def _keep_previous_repo(context):
    candidates = [
        read_env(context.env_path).get("JARVIS_VAULT", ""),
        str(context.environ.get("JARVIS_VAULT", "")).strip(),
    ]
    for previous in candidates:
        if previous and describe_vault_path(previous) == "repo":
            return previous
    return ""


def _environ_secrets(context):
    found = []
    for key in SECRET_KEYS:
        value = str(context.environ.get(key, "") or "")
        if value:
            found.append(value)
    return found


def _secret_values(choices, context):
    found = list(_environ_secrets(context))
    for key in SECRET_KEYS:
        value = str(choices.values.get(key, "") or "")
        if value and value not in found:
            found.append(value)
    return found


def _announce(console, values):
    for key, value in values.items():
        if not value and key == "JARVIS_VAULT":
            console.say("JARVIS_VAULT: desligado")
        elif key in SECRET_KEYS:
            console.say(key + ": " + ("definido" if value else "removido"))
        elif value:
            console.say(key + ": " + value)
        else:
            console.say(key + ": removido")


def _github_line(state):
    if state == "ok":
        return "GitHub: gh autenticado. Os PRs entram no bom dia."
    if state == "missing":
        return (
            "GitHub: gh não encontrado. É opcional. "
            "Instale e rode gh auth login para consultar PRs."
        )
    if state == "anonymous":
        return "GitHub: gh sem login. É opcional. Rode gh auth login para consultar PRs."
    return "GitHub: não consegui consultar o gh. É opcional."


def _hidden_input(prompt):
    import getpass

    return getpass.getpass(prompt)


if __name__ == "__main__":
    sys.exit(main())
