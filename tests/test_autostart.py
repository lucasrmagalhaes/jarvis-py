import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.autostart import LABEL, TASK_NAME, Autostart


TOKEN = "token-super-secreto"
PASSWORD = "senha de app secreta"


class Runner:
    def __init__(self, create_code=0, query_code=0):
        self.calls = []
        self.create_code = create_code
        self.query_code = query_code
        self.task_present = False

    def __call__(self, args, timeout=60):
        listed = list(args)
        self.calls.append(listed)
        code = 0
        if len(listed) > 1 and listed[0] == "schtasks" and listed[1] == "/Create":
            code = self.create_code
            if code == 0:
                self.task_present = True
        elif len(listed) > 1 and listed[0] == "schtasks" and listed[1] == "/Delete":
            self.task_present = False
        elif len(listed) > 1 and listed[0] == "schtasks" and listed[1] == "/Query":
            code = 0 if self.task_present else self.query_code or 1
        return subprocess.CompletedProcess(listed, code, "", "")


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "casa de teste"
        self.project = self.tmp / "jarvis & co"
        self.project.mkdir(parents=True)
        self.home.mkdir()
        self.saved = {
            "JIRA_TOKEN": os.environ.get("JIRA_TOKEN"),
            "GMAIL_APP_PASSWORD": os.environ.get("GMAIL_APP_PASSWORD"),
        }
        os.environ["JIRA_TOKEN"] = TOKEN
        os.environ["GMAIL_APP_PASSWORD"] = PASSWORD

    def tearDown(self):
        import shutil

        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def service(self, platform_name, runner=None):
        return Autostart(
            platform_name=platform_name,
            home=self.home,
            project=self.project,
            python="/usr/bin/python3",
            runner=runner or Runner(),
            uid="501",
            appdata=str(self.home / "AppData" / "Roaming"),
            path_env="/usr/bin:/bin",
        )

    def assert_no_secrets(self, text):
        self.assertNotIn(TOKEN, text)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn("JIRA_TOKEN", text)
        self.assertNotIn("GMAIL_APP_PASSWORD", text)

    def test_darwin_plist_has_no_secret_and_does_not_start_now(self):
        runner = Runner()
        service = self.service("Darwin", runner)
        result = service.enable()
        self.assertTrue(result.ok)
        self.assertIn("próximo login", result.message)
        plist = service.plist_path.read_text(encoding="utf-8")
        self.assert_no_secrets(plist)
        self.assertIn("jarvis &amp; co", plist)
        self.assertNotIn("jarvis & co", plist)
        self.assertIn("<string>/usr/bin/python3</string>", plist)
        self.assertIn("<string>-m</string>", plist)
        self.assertIn("<string>jarvis.main</string>", plist)
        self.assertIn("<key>RunAtLoad</key>", plist)
        self.assertIn("<string>Aqua</string>", plist)
        self.assertIn(LABEL, plist)
        self.assertIn("PYTHONUTF8", plist)
        joined = [" ".join(call) for call in runner.calls]
        self.assertTrue(any(item == "launchctl enable gui/501/" + LABEL for item in joined))
        self.assertFalse(any("bootstrap" in item or "kickstart" in item for item in joined))
        marker = service.marker_path.read_text(encoding="utf-8")
        self.assert_no_secrets(marker)
        self.assertIn("launchagent", marker)
        self.assertTrue(service.status().enabled)
        self.assertIn("LaunchAgent", service.status().detail)

        disabled = service.disable()
        self.assertTrue(disabled.ok)
        self.assertFalse(service.plist_path.exists())
        self.assertFalse(service.marker_path.exists())
        self.assertFalse(service.status().enabled)
        joined = [" ".join(call) for call in runner.calls]
        self.assertTrue(any(item.startswith("launchctl bootout") for item in joined))
        self.assertTrue(any(item.startswith("launchctl disable") for item in joined))
        again = service.disable()
        self.assertTrue(again.ok)

    def test_windows_prefers_a_scheduled_task(self):
        runner = Runner()
        service = self.service("Windows", runner)
        result = service.enable()
        self.assertTrue(result.ok)
        self.assertIn("Tarefa agendada", result.message)
        self.assertIn(TASK_NAME, result.message)
        launcher = service.launcher_path.read_text(encoding="utf-8")
        self.assert_no_secrets(launcher)
        self.assertIn("python3\" -m jarvis.main", launcher)
        self.assertIn("PYTHONUTF8", launcher)
        self.assertFalse(service.startup_script.exists())
        create = next(call for call in runner.calls if call[1] == "/Create")
        flat = " ".join(create)
        self.assert_no_secrets(flat)
        self.assertIn("/SC", create)
        self.assertIn("ONLOGON", create)
        self.assertIn("LIMITED", create)
        self.assertIn(TASK_NAME, create)
        target = create[create.index("/TR") + 1]
        self.assertTrue(target.startswith('"') and target.endswith('"'))
        self.assertTrue(service.status().enabled)
        self.assertIn("tarefa agendada", service.status().detail)
        service.disable()
        self.assertFalse(service.launcher_path.exists())
        self.assertTrue(any(call[1] == "/Delete" for call in runner.calls))
        self.assertFalse(service.status().enabled)

    def test_windows_falls_back_to_the_startup_folder(self):
        runner = Runner(create_code=1, query_code=1)
        service = self.service("Windows", runner)
        result = service.enable()
        self.assertTrue(result.ok)
        self.assertIn("Inicializar", result.message)
        self.assertTrue(service.startup_script.is_file())
        text = service.startup_script.read_text(encoding="utf-8")
        self.assert_no_secrets(text)
        self.assertIn("-m jarvis.main", text)
        self.assertIn("atalho", service.status().detail)
        mode = stat.S_IMODE(service.marker_path.stat().st_mode) if os.name != "nt" else None
        if mode is not None:
            self.assertEqual(mode & 0o077, 0)
        service.disable()
        self.assertFalse(service.startup_script.exists())
        self.assertFalse(service.launcher_path.exists())

    def test_linux_reports_unavailable_without_commands(self):
        def boom(_args, timeout=60):
            raise AssertionError("não devia chamar comando")

        service = self.service("Linux", boom)
        state = service.status()
        self.assertFalse(state.enabled)
        self.assertIn("não disponível", state.detail)
        result = service.enable()
        self.assertFalse(result.ok)
        self.assertTrue(result.unsupported)
        disabled = service.disable()
        self.assertTrue(disabled.ok)

    def test_rejects_a_path_with_quotes(self):
        service = Autostart(
            platform_name="Darwin",
            home=self.home,
            project=self.project,
            python='/usr/bin/python"3',
            runner=Runner(),
            uid="501",
        )
        result = service.enable()
        self.assertFalse(result.ok)
        self.assertFalse(service.plist_path.exists())


if __name__ == "__main__":
    unittest.main()
