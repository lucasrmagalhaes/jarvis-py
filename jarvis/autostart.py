"""Início do Jarvis no login, sem gravar segredo no agendador.

macOS: LaunchAgent em ~/Library/LaunchAgents.
Windows: tarefa agendada no logon ou, se ela falhar, arquivo na pasta Inicializar.
O processo só começa no próximo login. O plist e a tarefa apontam para o Python
e a pasta do projeto. As chaves ficam em ~/.jarvis/.env, lidas pelo próprio Jarvis.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

LABEL = "com.jarvispy.assistant"
TASK_NAME = "Jarvis"


class AutoState:
    def __init__(self, enabled, detail, level="ok", fix=""):
        self.enabled = enabled
        self.detail = detail
        self.level = level
        self.fix = fix


class AutoResult:
    def __init__(self, ok, message, unsupported=False):
        self.ok = ok
        self.message = message
        self.unsupported = unsupported


def default_runner(args, timeout=60):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def for_current_process():
    from .config import PROJECT_ROOT

    uid = str(os.getuid()) if hasattr(os, "getuid") else "0"
    return Autostart(
        platform_name=platform.system(),
        home=Path.home(),
        project=PROJECT_ROOT,
        python=sys.executable,
        runner=default_runner,
        uid=uid,
        appdata=os.environ.get("APPDATA", ""),
        path_env=os.environ.get("PATH", ""),
    )


class Autostart:
    def __init__(
        self,
        platform_name,
        home,
        project,
        python,
        runner,
        uid="0",
        appdata="",
        path_env="",
    ):
        self.platform_name = platform_name
        self.home = Path(home)
        self.project = Path(project)
        self.python = str(python)
        self.runner = runner
        self.uid = str(uid)
        self.appdata = appdata
        self.path_env = path_env

    @property
    def plist_path(self):
        return self.home / "Library" / "LaunchAgents" / (LABEL + ".plist")

    @property
    def marker_path(self):
        return self.home / ".jarvis" / "autostart.json"

    @property
    def launcher_path(self):
        return self.home / ".jarvis" / "start-jarvis.cmd"

    @property
    def startup_script(self):
        return self.startup_dir / "Jarvis.cmd"

    @property
    def startup_dir(self):
        if self.appdata:
            base = Path(self.appdata)
        else:
            base = self.home / "AppData" / "Roaming"
        return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    @property
    def log_path(self):
        return self.home / ".jarvis" / "logs" / "autostart.log"

    def status(self):
        if self.platform_name == "Darwin":
            if self.plist_path.is_file():
                return AutoState(True, "ativo, LaunchAgent")
            return AutoState(False, "desligado")
        if self.platform_name == "Windows":
            if self._task_exists():
                return AutoState(True, "ativo, tarefa agendada")
            if self.startup_script.is_file():
                return AutoState(True, "ativo, atalho de inicialização")
            return AutoState(False, "desligado")
        return AutoState(False, "não disponível neste sistema")

    def enable(self):
        if not self._paths_safe():
            return AutoResult(
                False,
                "O caminho do Python ou do projeto tem aspas. Escolha outro caminho.",
            )
        if self.platform_name == "Darwin":
            return self._enable_darwin()
        if self.platform_name == "Windows":
            return self._enable_windows()
        return AutoResult(
            False,
            "Início automático existe no macOS e no Windows. "
            "Neste sistema, inicie com python -m jarvis.main.",
            unsupported=True,
        )

    def disable(self):
        if self.platform_name == "Darwin":
            return self._disable_darwin()
        if self.platform_name == "Windows":
            return self._disable_windows()
        self._remove_marker()
        return AutoResult(True, "Início automático não está disponível neste sistema.")

    def render_plist(self):
        log_path = str(self.log_path)
        arguments = [self.python, "-m", "jarvis.main"]
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
            "<plist version=\"1.0\">",
            "<dict>",
            "  <key>Label</key>",
            "  <string>" + _xml(LABEL) + "</string>",
            "  <key>ProgramArguments</key>",
            "  <array>",
        ]
        for argument in arguments:
            lines.append("    <string>" + _xml(argument) + "</string>")
        lines.extend(
            [
                "  </array>",
                "  <key>WorkingDirectory</key>",
                "  <string>" + _xml(str(self.project)) + "</string>",
                "  <key>RunAtLoad</key>",
                "  <true/>",
                "  <key>LimitLoadToSessionType</key>",
                "  <string>Aqua</string>",
                "  <key>StandardOutPath</key>",
                "  <string>" + _xml(log_path) + "</string>",
                "  <key>StandardErrorPath</key>",
                "  <string>" + _xml(log_path) + "</string>",
                "  <key>EnvironmentVariables</key>",
                "  <dict>",
                "    <key>PATH</key>",
                "    <string>" + _xml(self._path_value()) + "</string>",
                "    <key>PYTHONUTF8</key>",
                "    <string>1</string>",
                "  </dict>",
                "</dict>",
                "</plist>",
                "",
            ]
        )
        return "\n".join(lines)

    def launcher_text(self):
        return (
            "@echo off\r\n"
            "set PYTHONUTF8=1\r\n"
            'cd /d "' + str(self.project) + '"\r\n'
            '"' + self.python + '" -m jarvis.main\r\n'
        )

    def _enable_darwin(self):
        self.plist_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.plist_path.write_text(self.render_plist(), encoding="utf-8", newline="\n")
        os.chmod(self.plist_path, 0o644)
        self._write_marker("launchagent")
        self._run(["launchctl", "enable", "gui/" + self.uid + "/" + LABEL])
        return AutoResult(
            True,
            "Início automático armado. LaunchAgent em "
            + str(self.plist_path)
            + ". O Jarvis entra no próximo login.",
        )

    def _disable_darwin(self):
        target = "gui/" + self.uid + "/" + LABEL
        self._run(["launchctl", "bootout", target])
        if self.plist_path.is_file():
            self._run(["launchctl", "bootout", "gui/" + self.uid, str(self.plist_path)])
        self._run(["launchctl", "disable", target])
        self.plist_path.unlink(missing_ok=True)
        self._remove_marker()
        return AutoResult(True, "Início automático desligado.")

    def _enable_windows(self):
        try:
            self._write_launcher()
        except OSError as error:
            return AutoResult(False, "Não consegui gravar o atalho: " + str(error))
        command = [
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TR",
            self._task_target(),
        ]
        try:
            result = self.runner(command, timeout=30)
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired):
            code = 1
        if code == 0:
            self._remove_startup()
            self._write_marker("schtasks")
            return AutoResult(
                True,
                "Início automático armado. Tarefa agendada "
                + TASK_NAME
                + ". O Jarvis entra no próximo login.",
            )
        try:
            self._write_startup()
        except OSError as error:
            return AutoResult(False, "Não consegui gravar o atalho: " + str(error))
        self._write_marker("startup")
        return AutoResult(
            True,
            "Não consegui criar a tarefa agendada. Deixei o arquivo "
            + str(self.startup_script)
            + " na pasta Inicializar. O Windows executa esse arquivo no login.",
        )

    def _disable_windows(self):
        try:
            self.runner(
                ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.launcher_path.unlink(missing_ok=True)
        self._remove_startup()
        self._remove_marker()
        return AutoResult(True, "Início automático desligado.")

    def _task_exists(self):
        try:
            result = self.runner(
                ["schtasks", "/Query", "/TN", TASK_NAME],
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return getattr(result, "returncode", 1) == 0

    def _task_target(self):
        path = str(self.launcher_path)
        if any(char in path for char in ' "'):
            return '"' + path.replace('"', "") + '"'
        return path

    def _write_launcher(self):
        self.launcher_path.parent.mkdir(parents=True, exist_ok=True)
        self.launcher_path.write_text(self.launcher_text(), encoding="utf-8", newline="\n")

    def _write_startup(self):
        self.startup_dir.mkdir(parents=True, exist_ok=True)
        self.startup_script.write_text(self.launcher_text(), encoding="utf-8", newline="\n")

    def _remove_startup(self):
        self.startup_script.unlink(missing_ok=True)

    def _write_marker(self, method):
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "method": method,
            "python": self.python,
            "project": str(self.project),
        }
        self.marker_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if os.name != "nt":
            try:
                os.chmod(self.marker_path, 0o600)
            except OSError:
                pass

    def _remove_marker(self):
        self.marker_path.unlink(missing_ok=True)

    def _path_value(self):
        parts = []
        if self.path_env:
            parts.append(self.path_env)
        parts.append(str(Path(self.python).parent))
        parts.extend(
            [
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        )
        seen = []
        for part in ":".join(parts).split(":"):
            if part and part not in seen:
                seen.append(part)
        return ":".join(seen)

    def _paths_safe(self):
        for value in (str(self.project), self.python):
            if '"' in value or "\n" in value or "\r" in value:
                return False
        return True

    def _run(self, args):
        try:
            return self.runner(args, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None


def _xml(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
