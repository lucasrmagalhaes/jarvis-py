import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.brain import VAULT_RULES, Brain
from jarvis.persona import PERSONA
from jarvis.reminders import ReminderService
from jarvis.vault import Vault, VaultError, commit_message, normalize_remote

WRAPPER = """#!/usr/bin/env python3
import os
import sys

log = os.environ.get("JARVIS_GIT_LOG", "")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("\\t".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
command = ""
index = 0
while index < len(args):
    item = args[index]
    if item == "-C":
        index += 2
        continue
    if item.startswith("-"):
        index += 1
        continue
    command = item
    break
if os.environ.get("JARVIS_GIT_FAIL_NET") == "1" and command in ("fetch", "push"):
    sys.stderr.write("fatal: unable to access network\\n")
    raise SystemExit(128)
if os.environ.get("JARVIS_GIT_FAIL_PULL") == "1" and command == "merge":
    sys.stderr.write("fatal: pull failed\\n")
    raise SystemExit(1)
if os.environ.get("JARVIS_GIT_FAIL_STASH") == "1" and command == "stash" and "push" in args:
    sys.stderr.write("fatal: stash failed\\n")
    raise SystemExit(1)
os.execvp("git", ["git", *args])
"""

ENV_KEYS = (
    "JARVIS_VAULT",
    "JARVIS_VAULT_REMOTE",
    "JARVIS_VAULT_SYNC",
    "JARVIS_VAULT_BRANCH",
    "JARVIS_PROMPT_FILE",
    "JARVIS_WORKSPACE",
    "JARVIS_ALLOWED_TOOLS",
    "JARVIS_GIT_BIN",
    "JARVIS_GIT_LOG",
    "JARVIS_GIT_FAIL_NET",
    "JARVIS_GIT_FAIL_PULL",
    "JARVIS_GIT_FAIL_STASH",
    "JIRA_URL",
    "JIRA_EMAIL",
    "JIRA_TOKEN",
    "GMAIL_EMAIL",
    "GMAIL_APP_PASSWORD",
    "GMAIL_IMAP_HOST",
    "GMAIL_IMAP_PORT",
    "JARVIS_GH_BIN",
    "JARVIS_HOME",
)


def run_git(path, *args, check=True):
    command = ["git"]
    if path is not None:
        command += ["-C", str(path)]
    command += list(args)
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and process.returncode != 0:
        raise AssertionError((process.stderr or process.stdout or "git falhou").strip())
    return process


def config_repo(path):
    run_git(path, "config", "user.email", "jarvis-test@example.com")
    run_git(path, "config", "user.name", "Jarvis Test")
    run_git(path, "config", "commit.gpgsign", "false")


def make_pair(tmp):
    bare = tmp / "remote.git"
    run_git(None, "init", "--bare", "-b", "main", str(bare))
    work = tmp / "work"
    run_git(None, "init", "-b", "main", str(work))
    config_repo(work)
    agenda = work / "Agenda Profissional"
    agenda.mkdir()
    (work / "AGENTS.md").write_text("Use as pastas existentes.\n", encoding="utf-8")
    (work / "CLAUDE.md").write_text("# Vault\n", encoding="utf-8")
    (agenda / "Hoje.md").write_text("v1\n", encoding="utf-8")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "base")
    run_git(work, "remote", "add", "origin", str(bare))
    run_git(work, "push", "-u", "origin", "HEAD:main")
    local = tmp / "local"
    run_git(None, "clone", str(bare), str(local))
    config_repo(local)
    return bare, work, local


def show(bare, spec):
    return run_git(None, "--git-dir", str(bare), "show", spec).stdout


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.saved = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tmp = Path(tempfile.mkdtemp())
        self.log = self.tmp / "git.log"
        self.wrapper = self.tmp / "gitwrap.py"
        self.wrapper.write_text(WRAPPER, encoding="utf-8")
        self.wrapper.chmod(self.wrapper.stat().st_mode | stat.S_IEXEC)
        os.environ["JARVIS_GIT_LOG"] = str(self.log)
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        os.environ["JARVIS_HOME"] = str(self.tmp / "home")

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def vault(self, local, bare, **kwargs):
        return Vault(
            local,
            remote=str(bare),
            git_bin=str(self.wrapper),
            timeout=30,
            **kwargs,
        )

    def assert_git_safe(self):
        if not self.log.exists():
            return
        for line in self.log.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            self.assertNotIn("--force", parts)
            self.assertNotIn("--force-with-lease", parts)
            self.assertNotIn("--force-if-includes", parts)
            self.assertNotIn("-f", parts)
            if "reset" in parts:
                self.assertIn("--merge", parts)
                self.assertNotIn("--hard", parts)
            self.assertNotIn("rebase", parts)
            self.assertNotIn("clean", parts)
            for part in parts:
                self.assertFalse(part.startswith("+"), part)

    def test_normalize_remote(self):
        expected = "github.com/exemplo/vault-de-notas"
        samples = [
            "https://github.com/exemplo/vault-de-notas.git",
            "https://github.com/exemplo/vault-de-notas",
            "git@github.com:exemplo/vault-de-notas.git",
            "ssh://git@github.com/exemplo/vault-de-notas.git",
            "https://x-access-token:secret@github.com/exemplo/vault-de-notas.git",
        ]
        for sample in samples:
            self.assertEqual(normalize_remote(sample), expected, sample)
        self.assertNotEqual(
            normalize_remote("https://github.com/other/repo.git"),
            expected,
        )

    def test_empty_expected_remote_uses_origin(self):
        bare, _work, local = make_pair(self.tmp)
        vault = Vault(local, remote="", git_bin=str(self.wrapper), timeout=30)
        result = vault.prepare()
        self.assertFalse(result.fatal, result.detail)
        self.assertEqual(vault.remote_name, "origin")
        self.assertEqual(result.action, "ready")
        self.assert_git_safe()

    def test_commit_message_sanitizes(self):
        message = commit_message("anota que pagar a luz")
        self.assertEqual(message, "Jarvis: anota que pagar a luz")
        self.assertNotIn("\u2014", message)
        dashed = commit_message("reunião\u2014amanhã\u2013cedo")
        self.assertNotIn("\u2014", dashed)
        self.assertNotIn("\u2013", dashed)
        self.assertTrue(dashed.startswith("Jarvis: "))
        long_message = commit_message("palavra " * 40)
        self.assertLessEqual(len(long_message), 72)
        self.assertTrue(long_message.endswith("..."))
        self.assertEqual(commit_message("   "), "Jarvis: atualiza notas")

    def test_pull_fast_forward(self):
        bare, work, local = make_pair(self.tmp)
        note = work / "Agenda Profissional" / "Amanha.md"
        note.write_text("pagar a luz\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "agenda")
        run_git(work, "push")
        result = self.vault(local, bare).prepare()
        self.assertIn(result.action, {"pulled", "synced", "ready"})
        self.assertEqual(
            (local / "Agenda Profissional" / "Amanha.md").read_text(encoding="utf-8"),
            "pagar a luz\n",
        )
        again = self.vault(local, bare).prepare()
        self.assertEqual(again.action, "ready")
        self.assert_git_safe()

    def test_publish_commits_and_pushes(self):
        bare, _work, local = make_pair(self.tmp)
        folder = local / "Casa"
        folder.mkdir()
        (folder / "Lista.md").write_text("leite\n", encoding="utf-8")
        result = self.vault(local, bare).publish("anota que comprar leite")
        self.assertTrue(result.pushed)
        self.assertTrue(result.committed)
        self.assertEqual(show(bare, "main:Casa/Lista.md"), "leite\n")
        log = run_git(local, "log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(log, "Jarvis: anota que comprar leite")
        self.assert_git_safe()

    def test_conflict_keeps_open_notes_in_stash(self):
        bare, work, local = make_pair(self.tmp)
        hoje = local / "Agenda Profissional" / "Hoje.md"
        hoje.write_text("versao local\n", encoding="utf-8")
        (work / "Agenda Profissional" / "Hoje.md").write_text("versao remota\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto")
        run_git(work, "push")
        before = run_git(None, "--git-dir", str(bare), "rev-parse", "main").stdout.strip()
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "stash_conflict")
        self.assertEqual(hoje.read_text(encoding="utf-8"), "versao remota\n")
        self.assertNotIn("<<<<<<<", hoje.read_text(encoding="utf-8"))
        pending = run_git(local, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
        self.assertNotEqual(pending.returncode, 0)
        after = run_git(None, "--git-dir", str(bare), "rev-parse", "main").stdout.strip()
        self.assertEqual(before, after)
        self.assertEqual(show(bare, "main:Agenda Profissional/Hoje.md"), "versao remota\n")
        stash = run_git(local, "stash", "show", "-p").stdout
        self.assertIn("versao local", stash)
        self.assertNotIn("Jarvis:", run_git(local, "log", "--format=%s").stdout)
        self.assert_git_safe()

    def test_distinct_files_merge_and_push(self):
        bare, work, local = make_pair(self.tmp)
        (work / "Agenda Profissional" / "Hoje.md").write_text("v1\nremoto\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto")
        run_git(work, "push")
        casa = local / "Casa"
        casa.mkdir()
        (casa / "Lista.md").write_text("pao\n", encoding="utf-8")
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "pulled")
        self.assertFalse(result.pushed)
        self.assertEqual((local / "Agenda Profissional" / "Hoje.md").read_text(encoding="utf-8"), "v1\nremoto\n")
        self.assertEqual((local / "Casa" / "Lista.md").read_text(encoding="utf-8"), "pao\n")
        self.assertIn("Lista.md", run_git(local, "status", "--porcelain", "-uall").stdout)
        missing = run_git(
            None, "--git-dir", str(bare), "cat-file", "-e", "main:Casa/Lista.md", check=False
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(show(bare, "main:Agenda Profissional/Hoje.md"), "v1\nremoto\n")
        self.assert_git_safe()

    def test_offline_keeps_open_notes_uncommitted(self):
        bare, _work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        note.write_text("sem rede\n", encoding="utf-8")
        os.environ["JARVIS_GIT_FAIL_NET"] = "1"
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "offline")
        self.assertFalse(result.committed)
        self.assertIn("Nada foi apagado", result.spoken())
        self.assertEqual(note.read_text(encoding="utf-8"), "sem rede\n")
        self.assertEqual(show(bare, "main:Agenda Profissional/Hoje.md"), "v1\n")
        self.assertNotIn("Jarvis:", run_git(local, "log", "--format=%s").stdout)
        self.assert_git_safe()

    def test_turn_commit_pushes_later_when_network_returns(self):
        bare, _work, local = make_pair(self.tmp)
        vault = self.vault(local, bare)
        ready = vault.prepare()
        self.assertEqual(ready.action, "ready")
        folder = local / "IA"
        folder.mkdir()
        (folder / "Nota.md").write_text("texto do pedido\n", encoding="utf-8")
        os.environ["JARVIS_GIT_FAIL_NET"] = "1"
        saved = vault.publish("anota o texto do pedido")
        self.assertTrue(saved.committed)
        self.assertFalse(saved.pushed)
        missing = run_git(
            None, "--git-dir", str(bare), "cat-file", "-e", "main:IA/Nota.md", check=False
        )
        self.assertNotEqual(missing.returncode, 0)
        os.environ["JARVIS_GIT_FAIL_NET"] = "0"
        again = vault.prepare()
        self.assertTrue(again.pushed)
        self.assertEqual(show(bare, "main:IA/Nota.md"), "texto do pedido\n")
        self.assert_git_safe()

    def test_publish_skips_preexisting_and_obsidian(self):
        bare, _work, local = make_pair(self.tmp)
        draft = local / "IA"
        draft.mkdir()
        (draft / "Rascunho.md").write_text("rascunho\n", encoding="utf-8")
        vault = self.vault(local, bare)
        prepared = vault.prepare()
        self.assertIn(prepared.action, {"ready", "pulled"})
        self.assertIn("Rascunho.md", run_git(local, "status", "--porcelain", "-uall").stdout)
        (draft / "Nota.md").write_text("nota nova\n", encoding="utf-8")
        obsidian = local / ".obsidian"
        obsidian.mkdir()
        (obsidian / "app.json").write_text("{}\n", encoding="utf-8")
        (local / ".env").write_text("TOKEN=segredo\n", encoding="utf-8")
        (draft / ".env.local").write_text("TOKEN=local\n", encoding="utf-8")
        (draft / "chave.pem").write_text("chave\n", encoding="utf-8")
        result = vault.publish("anota a nota nova")
        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertEqual(show(bare, "main:IA/Nota.md"), "nota nova\n")
        for spec in (
            "main:IA/Rascunho.md",
            "main:.obsidian/app.json",
            "main:.env",
            "main:IA/.env.local",
            "main:IA/chave.pem",
        ):
            missing = run_git(None, "--git-dir", str(bare), "cat-file", "-e", spec, check=False)
            self.assertNotEqual(missing.returncode, 0, spec)
        self.assertEqual((draft / "Rascunho.md").read_text(encoding="utf-8"), "rascunho\n")
        self.assertTrue((obsidian / "app.json").is_file())
        self.assertEqual((local / ".env").read_text(encoding="utf-8"), "TOKEN=segredo\n")
        self.assert_git_safe()

    def test_busy_merge_is_left_alone(self):
        bare, work, local = make_pair(self.tmp)
        (local / "Agenda Profissional" / "Hoje.md").write_text("lado local\n", encoding="utf-8")
        run_git(local, "add", "-A")
        run_git(local, "commit", "-m", "local")
        (work / "Agenda Profissional" / "Hoje.md").write_text("lado remoto\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto")
        run_git(work, "push")
        run_git(local, "fetch", "origin")
        merged = subprocess.run(
            ["git", "-C", str(local), "merge", "origin/main"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(merged.returncode, 0)
        before = (local / "Agenda Profissional" / "Hoje.md").read_text(encoding="utf-8")
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "busy")
        self.assertEqual((local / "Agenda Profissional" / "Hoje.md").read_text(encoding="utf-8"), before)
        self.assertEqual(run_git(local, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode, 0)
        self.assert_git_safe()

    def test_remote_mismatch_does_not_commit(self):
        bare, _work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        note.write_text("nao enviar\n", encoding="utf-8")
        other = self.tmp / "outro.git"
        run_git(None, "init", "--bare", "-b", "main", str(other))
        result = self.vault(local, other).prepare()
        self.assertTrue(result.fatal)
        self.assertEqual(result.action, "mismatch")
        self.assertEqual(note.read_text(encoding="utf-8"), "nao enviar\n")
        log = run_git(local, "log", "--format=%s").stdout
        self.assertNotIn("Jarvis:", log)

    def test_branch_override_does_not_checkout(self):
        bare, _work, local = make_pair(self.tmp)
        result = self.vault(local, bare, branch="outra").prepare()
        self.assertTrue(result.fatal)
        self.assertEqual(result.action, "bad_branch")
        self.assertEqual(run_git(local, "branch", "--show-current").stdout.strip(), "main")

    def test_guard_blocks_force_and_reset(self):
        bare, _work, local = make_pair(self.tmp)
        vault = self.vault(local, bare)
        with self.assertRaises(VaultError):
            vault._git("push", "--force")
        with self.assertRaises(VaultError):
            vault._git("reset", "--hard", "HEAD")
        with self.assertRaises(VaultError):
            vault._git("push", "origin", "+HEAD:main")

    def test_missing_path_is_fatal(self):
        result = Vault(self.tmp / "ausente", remote=str(self.tmp / "remote.git")).prepare()
        self.assertTrue(result.fatal)
        self.assertEqual(result.action, "missing")

    def test_diagnose_warns_when_agents_missing(self):
        bare, _work, local = make_pair(self.tmp)
        (local / "AGENTS.md").unlink()
        checks = {item.name: item for item in self.vault(local, bare).diagnose()}
        self.assertEqual(checks["Vault"].level, "ok")
        self.assertEqual(checks["AGENTS.md"].level, "warn")
        self.assertEqual(checks["CLAUDE.md"].level, "ok")
        self.assertEqual(checks["Remoto do vault"].level, "ok")

    def test_brain_keeps_vault_claude_md_and_exposes_write_tools(self):
        bare, _work, local = make_pair(self.tmp)
        os.environ["JARVIS_VAULT"] = str(local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        prompt = self.tmp / "prompt.md"
        os.environ["JARVIS_PROMPT_FILE"] = str(prompt)
        original = (local / "CLAUDE.md").read_text(encoding="utf-8")
        brain = Brain()
        self.assertEqual((local / "CLAUDE.md").read_text(encoding="utf-8"), original)
        self.assertNotIn("Tony Stark", original)
        text = prompt.read_text(encoding="utf-8")
        self.assertIn("Tony Stark", text)
        self.assertIn("Use as pastas existentes.", text)
        self.assertIn("linguagem direta", text)
        self.assertIn("[[nota|rótulo]]", text)
        self.assertNotIn("Agenda Profissional", VAULT_RULES)
        self.assertNotIn("Tecnologia", VAULT_RULES)
        self.assertIn(VAULT_RULES.splitlines()[0], text)
        self.assertIn("dado-nao-confiavel", text)
        self.assertIn('origem="WebFetch"', text)
        self.assertIn('origem="Jarvis/Inbox"', text)
        self.assertGreater(text.index("Use as pastas existentes."), text.index("Tony Stark"))
        self.assertGreater(text.index("linguagem direta"), text.index("Use as pastas existentes."))
        self.assertEqual(run_git(local, "status", "--porcelain").stdout.strip(), "")
        self.assertEqual(brain._cwd(), local.resolve())
        brain._supports_prompt_file = lambda _executable: True
        options = brain._options(None, False, "claude")
        tools = options[options.index("--allowedTools") + 1].split(",")
        self.assertIn("Edit", tools)
        self.assertIn("Write", tools)
        self.assertNotIn("Bash", tools)
        self.assertEqual(options[options.index("--disallowedTools") + 1], "Bash")
        self.assertEqual(options[options.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(
            options[options.index("--append-system-prompt-file") + 1],
            str(prompt),
        )
        self.assertNotIn("--dangerously-skip-permissions", options)
        readonly = brain._options(None, True, "claude")
        readonly_tools = readonly[readonly.index("--allowedTools") + 1].split(",")
        self.assertNotIn("Edit", readonly_tools)
        self.assertNotIn("Write", readonly_tools)
        self.assertNotIn("--permission-mode", readonly)

    def test_explicit_tools_are_respected(self):
        bare, _work, local = make_pair(self.tmp)
        os.environ["JARVIS_VAULT"] = str(local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        os.environ["JARVIS_ALLOWED_TOOLS"] = "Read,Bash"
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        brain = Brain()
        brain._supports_prompt_file = lambda _executable: True
        options = brain._options(None, False, "claude")
        tools = options[options.index("--allowedTools") + 1].split(",")
        self.assertEqual(tools, ["Read", "Bash"])
        self.assertNotIn("--disallowedTools", options)
        self.assertNotIn("--permission-mode", options)

    def test_brain_without_vault_keeps_persona_file(self):
        workspace = self.tmp / "workspace"
        os.environ["JARVIS_WORKSPACE"] = str(workspace)
        brain = Brain()
        self.assertIsNone(brain.vault)
        self.assertEqual((workspace / "CLAUDE.md").read_text(encoding="utf-8"), PERSONA)
        options = brain._options(None, False, "claude")
        self.assertNotIn("--append-system-prompt-file", options)
        self.assertNotIn("--disallowedTools", options)
        self.assertNotIn("Edit", options[options.index("--allowedTools") + 1].split(","))

    def test_capture_commits_only_the_daily_note(self):
        bare, _work, local = make_pair(self.tmp)
        os.environ["JARVIS_VAULT"] = str(local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        os.environ["JARVIS_GIT_BIN"] = str(self.wrapper)
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        (local / "aberto.md").write_text("rascunho\n", encoding="utf-8")
        brain = Brain()
        brain.clock = lambda: datetime(2026, 10, 28, 11, 5, tzinfo=ZoneInfo("America/Sao_Paulo"))
        reply = brain.ask("Hey Jarvis, anota que comprar cafe")
        self.assertIn("nota de hoje", reply)
        note = local / "2026-10-28.md"
        self.assertIn("- 11:05 comprar cafe", note.read_text(encoding="utf-8"))
        self.assertNotIn("senhor", note.read_text(encoding="utf-8"))
        self.assertEqual(show(bare, "main:2026-10-28.md"), note.read_text(encoding="utf-8"))
        missing = run_git(None, "--git-dir", str(bare), "cat-file", "-e", "main:aberto.md", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual((local / "aberto.md").read_text(encoding="utf-8"), "rascunho\n")
        self.assert_git_safe()

    def test_reminder_tick_commits_only_the_mark(self):
        bare, _work, local = make_pair(self.tmp)
        vault = self.vault(local, bare)
        vault.prepare()
        folder = local / "IA"
        folder.mkdir()
        note = folder / "Lembretes.md"
        note.write_text("- [ ] pagar o boleto @ 2020-01-01 09:00\n", encoding="utf-8")
        (local / "aberto.md").write_text("rascunho\n", encoding="utf-8")
        spoken = []

        class Bus:
            def transcript(self, role, text):
                spoken.append((role, text))

            def state(self, value):
                pass

        service = ReminderService(
            vault,
            speak=lambda text: spoken.append(("voice", text)),
            bus=Bus(),
            lock=threading.Lock(),
        )
        service.tick()
        self.assertIn("@avisado", note.read_text(encoding="utf-8"))
        self.assertIn("pagar o boleto", show(bare, "main:IA/Lembretes.md"))
        missing = run_git(None, "--git-dir", str(bare), "cat-file", "-e", "main:aberto.md", check=False)
        self.assertNotEqual(missing.returncode, 0)
        before = len(spoken)
        service.tick()
        self.assertEqual(len(spoken), before)
        self.assert_git_safe()

    def test_hud_counts_unpushed_commits(self):
        bare, _work, local = make_pair(self.tmp)
        vault = self.vault(local, bare)
        (local / "extra.md").write_text("x\n", encoding="utf-8")
        run_git(local, "add", "extra.md")
        run_git(local, "commit", "-m", "local")
        waiting = vault.hud_payload()
        self.assertEqual(waiting["pending"], 1)
        self.assertTrue(waiting["pending_known"])
        result = vault.prepare()
        self.assertTrue(result.pushed)
        caught_up = vault.hud_payload()
        self.assertEqual(caught_up["pending"], 0)
        self.assertEqual(caught_up["detail"], result.detail)
        self.assertEqual(show(bare, "main:extra.md"), "x\n")
        self.assert_git_safe()

    def _brain(self, local, bare):
        os.environ["JARVIS_VAULT"] = str(local)
        os.environ["JARVIS_VAULT_REMOTE"] = str(bare)
        os.environ["JARVIS_GIT_BIN"] = str(self.wrapper)
        os.environ["JARVIS_PROMPT_FILE"] = str(self.tmp / "prompt.md")
        brain = Brain()
        brain.clock = lambda: datetime(2026, 10, 28, 11, 5, tzinfo=ZoneInfo("America/Sao_Paulo"))
        return brain

    def test_week_confirmation_commits_only_the_summary(self):
        bare, _work, local = make_pair(self.tmp)
        moment = datetime(2026, 10, 28, 11, 0, tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()
        note = local / "Diario.md"
        note.write_text(
            "# Diario\n\n- [x] enviar o relatorio\n- [ ] revisar a proposta\n",
            encoding="utf-8",
        )
        old = local / "Arquivo antigo.md"
        old.write_text("# Arquivo antigo\n\n- [ ] tarefa velha\n", encoding="utf-8")
        run_git(local, "add", "Diario.md", "Arquivo antigo.md")
        run_git(local, "commit", "-m", "notas")
        run_git(local, "push", "origin", "HEAD:main")
        os.utime(note, (moment, moment))
        os.utime(old, (1_600_000_000, 1_600_000_000))
        (local / "aberto.md").write_text("rascunho\n", encoding="utf-8")
        brain = self._brain(local, bare)
        reply = brain.ask("como foi minha semana?")
        self.assertIn("Quer que eu grave esse resumo", reply)
        self.assertNotIn("tarefa velha", reply)
        self.assertFalse((local / "semana-2026-10-26.md").exists())
        declined = brain.ask("não")
        self.assertIn("Não gravei", declined)
        self.assertIsNone(brain.pending)
        self.assertFalse((local / "semana-2026-10-26.md").exists())
        brain.ask("como foi minha semana?")
        saved = brain.ask("sim")
        self.assertIn("Gravei o resumo", saved)
        summary = local / "semana-2026-10-26.md"
        text = summary.read_text(encoding="utf-8")
        self.assertIn("## Feitas", text)
        self.assertIn("enviar o relatorio", text)
        self.assertIn("revisar a proposta", text)
        self.assertNotIn("senhor", text)
        self.assertNotIn("tarefa velha", text)
        self.assertEqual(show(bare, "main:semana-2026-10-26.md"), text)
        missing = run_git(None, "--git-dir", str(bare), "cat-file", "-e", "main:aberto.md", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual((local / "aberto.md").read_text(encoding="utf-8"), "rascunho\n")
        self.assert_git_safe()

    def test_done_marks_one_task_and_confirms_when_several(self):
        bare, _work, local = make_pair(self.tmp)
        (local / "Casa.md").write_text("- [ ] pagar a conta de luz da casa\n", encoding="utf-8")
        (local / "Escritorio.md").write_text(
            "- [ ] pagar a conta de luz do escritorio\n",
            encoding="utf-8",
        )
        run_git(local, "add", "Casa.md", "Escritorio.md")
        run_git(local, "commit", "-m", "tarefas")
        run_git(local, "push", "origin", "HEAD:main")
        (local / "aberto.md").write_text("rascunho\n", encoding="utf-8")
        brain = self._brain(local, bare)
        reply = brain.ask("marca como feito pagar a conta de luz")
        self.assertIn("Diga o número", reply)
        self.assertIn("- [ ]", (local / "Casa.md").read_text(encoding="utf-8"))
        self.assertIn("- [ ]", (local / "Escritorio.md").read_text(encoding="utf-8"))
        options = list(brain.pending["options"])
        self.assertEqual(len(options), 2)
        saved = brain.ask("1")
        self.assertIn("Marquei como feito", saved)
        self.assertIn(options[0]["text"], saved)
        self.assertIn("- [x]", (local / options[0]["relative"]).read_text(encoding="utf-8"))
        self.assertIn("- [ ]", (local / options[1]["relative"]).read_text(encoding="utf-8"))
        self.assertIn("- [x]", show(bare, "main:" + options[0]["relative"]))
        self.assertIn("- [ ]", show(bare, "main:" + options[1]["relative"]))
        rest = brain.ask("marca como feito pagar a conta de luz")
        self.assertIn("Marquei como feito", rest)
        self.assertIn("- [x]", (local / options[1]["relative"]).read_text(encoding="utf-8"))
        self.assertIn("- [x]", show(bare, "main:" + options[1]["relative"]))
        missing = run_git(None, "--git-dir", str(bare), "cat-file", "-e", "main:aberto.md", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual((local / "aberto.md").read_text(encoding="utf-8"), "rascunho\n")
        self.assert_git_safe()

    def test_profile_outbox_and_inbox_commit_only_their_notes(self):
        bare, _work, local = make_pair(self.tmp)
        folder = local / "Jarvis" / "Inbox"
        folder.mkdir(parents=True)
        recado = folder / "codex.md"
        recado.write_text(
            "---\nde: Codex\npara: usuario\ndata: 2026-10-28\nstatus: novo\n---\n\nOlha o PR.\n",
            encoding="utf-8",
        )
        (local / "aberto.md").write_text("rascunho\n", encoding="utf-8")
        brain = self._brain(local, bare)
        remembered = brain.ask("lembra que eu gosto de cafe sem acucar")
        self.assertIn("nota de perfil", remembered)
        profile = (local / "Jarvis" / "Perfil.md").read_text(encoding="utf-8")
        self.assertIn("- 2026-10-28: gosto de cafe sem acucar", profile)
        self.assertNotIn("senhor", profile)
        self.assertEqual(show(bare, "main:Jarvis/Perfil.md"), profile)
        asked = brain.ask("pede pro Codex revisar o PR do HUD")
        self.assertIn("Codex", asked)
        request = local / "Jarvis" / "Outbox" / "Codex" / "2026-10-28-1105.md"
        body = request.read_text(encoding="utf-8")
        self.assertIn("de: usuario", body)
        self.assertIn("para: Codex", body)
        self.assertIn("status: novo", body)
        self.assertIn("revisar o PR do HUD", body)
        self.assertNotIn("senhor", body)
        self.assertEqual(show(bare, "main:Jarvis/Outbox/Codex/2026-10-28-1105.md"), body)
        heard = brain.ask("o que os assistentes mandaram?")
        self.assertIn("Olha o PR", heard)
        marked = recado.read_text(encoding="utf-8")
        self.assertIn("status: lido", marked)
        self.assertIn("de: Codex", marked)
        self.assertEqual(show(bare, "main:Jarvis/Inbox/codex.md"), marked)
        missing = run_git(None, "--git-dir", str(bare), "cat-file", "-e", "main:aberto.md", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual((local / "aberto.md").read_text(encoding="utf-8"), "rascunho\n")
        from types import SimpleNamespace

        brain.vault = SimpleNamespace(path=local)
        composed = brain._compose("e amanha?", SimpleNamespace(instruction=lambda: "leia"))
        self.assertIn("gosto de cafe sem acucar", composed)
        self.assertIn("Pedido do senhor: e amanha?", composed)
        self.assert_git_safe()

    def test_jira_without_vault_does_not_call_claude(self):
        workspace = self.tmp / "workspace"
        os.environ["JARVIS_WORKSPACE"] = str(workspace)
        os.environ["JARVIS_GH_BIN"] = "/bin/false"
        brain = Brain()

        def fail(*_args, **_kwargs):
            raise AssertionError("claude")

        brain._ask = fail
        reply = brain.ask("o que tenho no Jira?")
        self.assertEqual(
            reply,
            "O Jira não está configurado, senhor. "
            "Falta a chave. Rode python -m jarvis.setup.",
        )
        self.assertNotIn("vault", reply)
        self.assertIsNone(brain.vault)

    def test_pull_failure_keeps_open_notes(self):
        bare, work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        original = "nota aberta local\n"
        note.write_text(original, encoding="utf-8")
        extra = local / "Casa"
        extra.mkdir()
        loose = extra / "Aberta.md"
        loose.write_text("arquivo solto\n", encoding="utf-8")
        remote_note = work / "Remoto"
        remote_note.mkdir()
        (remote_note / "Novo.md").write_text("veio do remoto\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto novo")
        run_git(work, "push")
        before = run_git(local, "rev-parse", "HEAD").stdout.strip()
        os.environ["JARVIS_GIT_FAIL_PULL"] = "1"
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "error")
        self.assertTrue(result.kept_open)
        self.assertIn("já estavam abertas", result.detail)
        self.assertIn("Nada foi apagado", result.detail)
        self.assertIn("Nada foi apagado", result.spoken())
        self.assertNotIn("\u2014", result.detail)
        self.assertEqual(note.read_text(encoding="utf-8"), original)
        self.assertEqual(loose.read_text(encoding="utf-8"), "arquivo solto\n")
        self.assertFalse((local / "Remoto" / "Novo.md").exists())
        self.assertEqual(run_git(local, "rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(show(bare, "main:Remoto/Novo.md"), "veio do remoto\n")
        self.assertNotIn("Jarvis:", run_git(local, "log", "--format=%s").stdout)
        self.assertNotIn("arquivo solto", show(bare, "main:Agenda Profissional/Hoje.md"))
        pending = run_git(local, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
        self.assertNotEqual(pending.returncode, 0)
        self.assert_git_safe()

    def test_pull_failure_on_a_clean_clone_keeps_local_notes(self):
        bare, work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        remote_note = work / "Remoto"
        remote_note.mkdir()
        (remote_note / "Novo.md").write_text("veio do remoto\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto novo")
        run_git(work, "push")
        before = run_git(local, "rev-parse", "HEAD").stdout.strip()
        os.environ["JARVIS_GIT_FAIL_PULL"] = "1"
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "error")
        self.assertFalse(result.kept_open)
        self.assertIn("notas locais foram mantidas", result.detail)
        self.assertIn("Nada foi apagado", result.spoken())
        self.assertEqual(note.read_text(encoding="utf-8"), "v1\n")
        self.assertFalse((local / "Remoto" / "Novo.md").exists())
        self.assertEqual(run_git(local, "rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(run_git(local, "status", "--porcelain").stdout.strip(), "")
        self.assert_git_safe()

    def test_stash_failure_leaves_open_notes_untouched(self):
        bare, work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        original = "continua aberta\n"
        note.write_text(original, encoding="utf-8")
        (work / "Agenda Profissional" / "Hoje.md").write_text("versao remota\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto")
        run_git(work, "push")
        before = run_git(local, "rev-parse", "HEAD").stdout.strip()
        os.environ["JARVIS_GIT_FAIL_STASH"] = "1"
        result = self.vault(local, bare).prepare()
        self.assertEqual(result.action, "stash_error")
        self.assertTrue(result.read_only)
        self.assertIn("Não alterei nada", result.detail)
        self.assertIn("Nada foi apagado", result.spoken())
        self.assertEqual(note.read_text(encoding="utf-8"), original)
        self.assertEqual(run_git(local, "rev-parse", "HEAD").stdout.strip(), before)
        self.assertEqual(show(bare, "main:Agenda Profissional/Hoje.md"), "versao remota\n")
        self.assertNotIn("Jarvis:", run_git(local, "log", "--format=%s").stdout)
        self.assert_git_safe()

    def stash_calls(self):
        if not self.log.exists():
            return []
        return [
            line
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if "stash" in line.split("\t")
        ]

    def test_open_notes_stay_in_place_when_nothing_arrives(self):
        bare, _work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        note.write_text("aberta sem commit\n", encoding="utf-8")
        loose = local / "Rascunho.md"
        loose.write_text("arquivo solto\n", encoding="utf-8")
        os.environ["JARVIS_GIT_FAIL_STASH"] = "1"
        vault = self.vault(local, bare)
        for _turn in range(3):
            result = vault.prepare()
            self.assertTrue(result.ok, result.detail)
            self.assertEqual(result.action, "ready")
        self.assertEqual(self.stash_calls(), [])
        self.assertEqual(note.read_text(encoding="utf-8"), "aberta sem commit\n")
        self.assertEqual(loose.read_text(encoding="utf-8"), "arquivo solto\n")
        self.assertEqual(run_git(local, "stash", "list").stdout.strip(), "")
        self.assert_git_safe()

    def test_pull_of_other_files_does_not_stash_open_notes(self):
        bare, work, local = make_pair(self.tmp)
        note = local / "Agenda Profissional" / "Hoje.md"
        note.write_text("aberta sem commit\n", encoding="utf-8")
        loose = local / "Rascunho.md"
        loose.write_text("arquivo solto\n", encoding="utf-8")
        remote_note = work / "Remoto"
        remote_note.mkdir()
        (remote_note / "Novo.md").write_text("veio do remoto\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "remoto novo")
        run_git(work, "push")
        os.environ["JARVIS_GIT_FAIL_STASH"] = "1"
        result = self.vault(local, bare).prepare()
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.action, "pulled")
        self.assertEqual(self.stash_calls(), [])
        self.assertEqual((local / "Remoto" / "Novo.md").read_text(encoding="utf-8"), "veio do remoto\n")
        self.assertEqual(note.read_text(encoding="utf-8"), "aberta sem commit\n")
        self.assertEqual(loose.read_text(encoding="utf-8"), "arquivo solto\n")
        status = run_git(local, "status", "--porcelain").stdout
        self.assertIn("Hoje.md", status)
        self.assertIn("Rascunho.md", status)
        self.assertNotIn("Jarvis:", run_git(local, "log", "--format=%s").stdout)
        self.assert_git_safe()

    def test_pull_of_the_same_note_stashes_and_restores(self):
        bare, work, local = make_pair(self.tmp)
        lista = work / "Casa"
        lista.mkdir()
        (lista / "Lista.md").write_text("um\ndois\ntres\nquatro\ncinco\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "lista")
        run_git(work, "push")
        vault = self.vault(local, bare)
        self.assertEqual(vault.prepare().action, "pulled")
        local_note = local / "Casa" / "Lista.md"
        local_note.write_text("um\ndois\ntres\nquatro\ncinco local\n", encoding="utf-8")
        (lista / "Lista.md").write_text("um remoto\ndois\ntres\nquatro\ncinco\n", encoding="utf-8")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "lista remota")
        run_git(work, "push")
        self.assertEqual(self.stash_calls(), [])
        result = vault.prepare()
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.action, "pulled")
        self.assertTrue(self.stash_calls())
        self.assertEqual(
            local_note.read_text(encoding="utf-8"),
            "um remoto\ndois\ntres\nquatro\ncinco local\n",
        )
        self.assertEqual(run_git(local, "stash", "list").stdout.strip(), "")
        self.assertNotIn("Jarvis:", run_git(local, "log", "--format=%s").stdout)
        self.assert_git_safe()

    def test_docs_have_no_em_dash(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## Vault do Obsidian", 1)[1].split("## Diferenças", 1)[0]
        for path in (
            ROOT / "jarvis" / "vault.py",
            ROOT / "jarvis" / "brain.py",
            ROOT / "jarvis" / "routines.py",
            ROOT / "jarvis" / "reminders.py",
            ROOT / "jarvis" / "memory.py",
            ROOT / "jarvis" / "log.py",
            ROOT / "jarvis" / "barge.py",
            ROOT / "jarvis" / "main.py",
            ROOT / "jarvis" / "external.py",
            ROOT / "jarvis" / "bridge.py",
            ROOT / "jarvis" / "chat.py",
            ROOT / "jarvis" / "telegram.py",
            ROOT / "jarvis" / "telegram_api.py",
            ROOT / "jarvis" / "checkins.py",
            ROOT / "jarvis" / "companion.py",
            ROOT / "jarvis" / "setup.py",
            ROOT / "jarvis" / "doctor.py",
            ROOT / "jarvis" / "radar.py",
            ROOT / "jarvis" / "review.py",
            ROOT / "jarvis" / "alerts.py",
            ROOT / "jarvis" / "config.py",
            ROOT / "jarvis" / "voice.py",
            ROOT / "jarvis" / "busca.py",
            ROOT / "jarvis" / "guardas.py",
            ROOT / "jarvis" / "avaliar.py",
            ROOT / "jarvis" / "readwise.py",
            ROOT / "jarvis" / "consult.py",
            ROOT / "jarvis" / "memoria.py",
            ROOT / "jarvis" / "pedidos.py",
            ROOT / "jarvis" / "aprendizado.py",
            ROOT / "jarvis" / "persona.py",
            ROOT / "jarvis" / "cerebro.py",
            ROOT / "jarvis" / "fontes.py",
            ROOT / "jarvis" / "estudo.py",
            ROOT / "jarvis" / "indice.py",
            ROOT / "jarvis" / "relacionadas.py",
            ROOT / "jarvis" / "resumo.py",
            ROOT / "jarvis" / "panel.py",
            ROOT / "mapa" / "Vault.md",
            ROOT / "mapa" / "Consulta Android.md",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, path.name)
            self.assertNotIn("\u2013", path.read_text(encoding="utf-8"), path.name)
        self.assertNotIn("\u2014", section)
        self.assertNotIn("\u2013", section)
        decisions = (ROOT / "mapa" / "Decisões.md").read_text(encoding="utf-8")
        added = decisions.split("## Vault como diretório de trabalho", 1)[1].split("## Relacionado", 1)[0]
        self.assertNotIn("\u2014", added)
        self.assertNotIn("\u2013", added)
        hybrid = decisions.split("## Busca híbrida e escrita recusada no código", 1)[1]
        self.assertNotIn("\u2014", hybrid)
        self.assertNotIn("\u2013", hybrid)


if __name__ == "__main__":
    unittest.main()
