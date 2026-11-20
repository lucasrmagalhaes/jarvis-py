"""Sincroniza o vault Obsidian com o GitHub sem apagar notas e sem push forçado."""

import hashlib
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .trava import TravaOcupada, fila_escrita

STASH_MESSAGE = "jarvis: preserva notas locais antes do pull"
MERGE_MESSAGE = "Jarvis: sincroniza notas com o remoto"
MAX_AGENTS_CHARS = 80000


class VaultError(Exception):
    pass


class GitResult:
    def __init__(self, code, out, err):
        self.code = code
        self.out = out or ""
        self.err = err or ""


class Check:
    def __init__(self, level, name, detail="", fix=""):
        self.level = level
        self.name = name
        self.detail = detail
        self.fix = fix


class SyncResult:
    def __init__(
        self,
        ok,
        action,
        detail,
        fatal=False,
        read_only=False,
        committed=False,
        pushed=False,
        offline=False,
        fix="",
    ):
        self.ok = ok
        self.action = action
        self.detail = detail
        self.fatal = fatal
        self.read_only = read_only
        self.committed = committed
        self.pushed = pushed
        self.offline = offline
        self.fix = fix
        self.kept_open = False

    def instruction(self):
        rules = (
            "Notas seguem o AGENTS.md e o CLAUDE.md do vault, com linguagem direta. "
            "A fala segue a persona, sem copiar esse tom para dentro da nota. "
            "Deixe o git com o Jarvis. "
            "Responda só ao pedido, em voz, sem repetir esta instrução."
        )
        if self.read_only:
            return (
                rules
                + " Neste turno apenas leia as notas. Não crie, não edite e não apague arquivos."
            )
        if self.offline:
            return (
                rules
                + " Pode ler e editar as notas locais. O GitHub está inacessível agora."
            )
        return rules + " Pode ler, criar e editar notas do vault."

    def spoken(self):
        if self.action == "conflict" and self.committed:
            return (
                "Guardei as notas neste computador, mas não enviei ao GitHub "
                "porque há divergência. Nada foi apagado."
            )
        if self.action == "conflict":
            return (
                "Não sincronizei o vault com o GitHub porque há divergência. "
                "As notas locais foram preservadas."
            )
        if self.action == "rejected" and self.committed:
            return (
                "Guardei as notas neste computador, mas o GitHub recusou o envio. "
                "Nada foi apagado."
            )
        if self.action == "rejected":
            return "O GitHub recusou a sincronização. As notas locais foram preservadas."
        if self.action == "offline" and self.committed:
            return (
                "Guardei as notas neste computador. "
                "O envio ao GitHub fica para quando a conexão voltar."
            )
        if self.action == "commit_error":
            return "Não consegui registrar as notas no git. Elas continuam na pasta do vault."
        if self.action == "busy":
            return "O vault está no meio de uma operação git. Não alterei nada."
        if self.action == "stash_conflict":
            return (
                "As notas que já estavam abertas ficaram no stash do git, "
                "porque misturá-las com o GitHub geraria conflito. Nada foi apagado."
            )
        if self.action == "stash_error":
            return (
                "Não atualizei o vault para não mexer nas notas que já estavam abertas. "
                "Nada foi apagado."
            )
        if self.action == "error":
            return self.detail
        if self.action == "offline" and not self.committed:
            return (
                "Não consegui falar com o GitHub. "
                "As notas locais foram mantidas. Nada foi apagado."
            )
        if self.fatal and self.committed:
            return "Guardei as notas neste computador, mas não concluí a sincronização."
        return ""


def commit_message(text):
    cleaned = (text or "").replace("\u2014", " ").replace("\u2013", " ")
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        cleaned = "atualiza notas"
    prefix = "Jarvis: "
    limit = 72
    room = limit - len(prefix)
    if len(cleaned) > room:
        cleaned = cleaned[: room - 3].rstrip() + "..."
    return prefix + cleaned


def normalize_remote(url):
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("file://"):
        raw = raw[7:]
    local = _as_local_path(raw)
    if local is not None:
        return str(local.resolve()) if local.exists() else str(local)

    raw = raw.rstrip("/")
    if raw.lower().endswith(".git"):
        raw = raw[:-4]
    lowered = raw.lower()
    for prefix in ("git+ssh://", "ssh://", "https://", "http://", "git://"):
        if lowered.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if "@" in raw.split("/", 1)[0] or "@" in raw.split(":", 1)[0]:
        raw = raw.split("@", 1)[1]
    head, sep, tail = raw.partition(":")
    if sep and "/" not in head:
        raw = head + "/" + tail
    return raw.strip("/").lower()


def _as_local_path(raw):
    if raw.startswith("/") or raw.startswith("./") or raw.startswith("../") or raw.startswith("~"):
        return Path(raw).expanduser()
    if len(raw) >= 3 and raw[0].isalpha() and raw[1] == ":" and raw[2] in "/\\":
        return Path(raw)
    return None


def _valid_branch(name):
    if not name or name.startswith("-") or name.endswith("/") or ".." in name:
        return False
    return all(char.isalnum() or char in "._/-" for char in name)


class Vault:
    def __init__(
        self,
        path,
        remote=None,
        branch="",
        sync=True,
        timeout=120,
        git_bin=None,
        extra_env=None,
    ):
        self.path = Path(path).expanduser().resolve()
        self.expected_remote = config.VAULT_REMOTE_DEFAULT if remote is None else remote
        self.branch_override = branch or ""
        self.sync = sync
        self.timeout = timeout
        self.git_bin = git_bin or "git"
        self.extra_env = extra_env or {}
        self.remote_unavailable = False
        self.blocked = False
        self.remote_name = ""
        self.branch_name = ""
        self._last_git_error = ""
        self._snapshot = None
        self._allow_merge_reset = False
        self._guardado = "clean"
        self.last_result = None
        self.last_sync_at = None

    @classmethod
    def from_env(cls):
        directory = config.vault_dir()
        if directory is None:
            return None
        return cls(
            directory,
            remote=config.vault_remote(),
            branch=config.vault_branch(),
            sync=config.vault_sync_enabled(),
            timeout=config.vault_git_timeout(),
            git_bin=config.git_bin(),
        )

    def read_agents(self):
        path = self.path / "AGENTS.md"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def agents_for_prompt(self):
        text = self.read_agents()
        if not text.strip():
            return (
                "Não há AGENTS.md na raiz do vault. "
                "Procure as convenções nas notas antes de escrever."
            )
        if len(text) > MAX_AGENTS_CHARS:
            return (
                "O AGENTS.md é longo demais para colar aqui. "
                "Leia o arquivo AGENTS.md na raiz com a ferramenta Read "
                "e siga-o por completo antes de escrever."
            )
        return (
            "Convenções lidas agora do AGENTS.md deste clone. "
            "Elas mandam na organização, no YAML e nos links:\n\n"
            + text.strip()
        )

    def diagnose(self):
        self._reset_flags()
        fatal = self._preflight()
        if fatal:
            return [Check("fail", "Vault", fatal.detail, fatal.fix)]
        checks = [Check("ok", "Vault", str(self.path))]
        if self.sync:
            checks.append(Check("ok", "Sync do vault", f"branch {self.branch_name}"))
        else:
            checks.append(
                Check("warn", "Sync do vault", "desligado por JARVIS_VAULT_SYNC")
            )
        name = self._git("config", "user.name").out.strip()
        email = self._git("config", "user.email").out.strip()
        if name and email:
            checks.append(Check("ok", "Identidade git", f"{name}"))
        else:
            checks.append(
                Check(
                    "fail" if self.sync else "warn",
                    "Identidade git",
                    "user.name ou user.email ausente",
                    "configure user.name e user.email neste clone",
                )
            )
        if (self.path / "AGENTS.md").is_file():
            checks.append(Check("ok", "AGENTS.md", "presente na raiz"))
        else:
            checks.append(
                Check(
                    "warn",
                    "AGENTS.md",
                    "ausente na raiz",
                    "o cérebro segue esse arquivo para criar notas no formato do vault",
                )
            )
        if (self.path / "CLAUDE.md").is_file():
            checks.append(Check("ok", "CLAUDE.md", "presente na raiz"))
        else:
            checks.append(Check("warn", "CLAUDE.md", "ausente na raiz"))
        if self.sync:
            if self._fetch():
                checks.append(Check("ok", "Remoto do vault", "acesso ao git concluído"))
            elif "tempo esgotado" in (self._last_git_error or ""):
                checks.append(
                    Check(
                        "warn",
                        "Remoto do vault",
                        f"tempo esgotado ao consultar o remoto ({self.timeout}s)",
                        "confira a rede. O diagnóstico não espera além desse tempo",
                    )
                )
            else:
                checks.append(
                    Check(
                        "warn",
                        "Remoto do vault",
                        "sem acesso agora",
                        "o Jarvis segue com as notas locais e tenta de novo depois",
                    )
                )
        return checks

    def prepare(self):
        try:
            with fila_escrita():
                try:
                    result = self._prepare()
                except VaultError as error:
                    self.blocked = True
                    result = self._fatal("blocked", str(error))
        except TravaOcupada:
            self.blocked = True
            result = SyncResult(
                False,
                "busy",
                "O vault está no meio de uma operação git. Não alterei nada.",
                read_only=True,
            )
        self._remember(result)
        return result

    def publish(self, text, pending=False):
        try:
            from .privacidade import modo_privado_ativo
        except Exception:
            modo_privado_ativo = None
        if modo_privado_ativo is not None and modo_privado_ativo():
            return SyncResult(True, "privado", "modo privado")
        if pending:
            self._snapshot = None
        try:
            with fila_escrita():
                try:
                    result = self._publish(text)
                except VaultError as error:
                    self.blocked = True
                    result = self._fatal("blocked", str(error))
        except TravaOcupada:
            self.blocked = True
            result = SyncResult(
                False,
                "busy",
                "O vault está no meio de uma operação git. Não alterei nada.",
                read_only=True,
            )
        self._remember(result)
        return result

    def resync_snapshot(self):
        self._snapshot = self._fingerprint()

    def push_pending_count(self):
        if not self.path.is_dir():
            return None
        upstream = self._git("rev-parse", "--abbrev-ref", "@{upstream}")
        if upstream.code != 0 or not upstream.out.strip():
            return None
        counts = self._git(
            "rev-list", "--left-right", "--count", f"HEAD...{upstream.out.strip()}"
        )
        if counts.code != 0:
            return None
        parts = counts.out.split()
        if len(parts) != 2:
            return None
        try:
            return int(parts[0])
        except ValueError:
            return None

    def hud_payload(self):
        result = self.last_result
        pending = self.push_pending_count()
        return {
            "type": "vault",
            "action": result.action if result else "",
            "detail": result.detail if result else "Vault ainda sem sincronização.",
            "pending": 0 if pending is None else pending,
            "pending_known": pending is not None,
            "ok": bool(result and result.ok),
        }

    def _remember(self, result):
        self.last_result = result
        self.last_sync_at = datetime.now(timezone.utc)

    def _prepare(self):
        self._reset_flags()
        fatal = self._preflight()
        if fatal:
            return fatal
        if not self.sync:
            self._snapshot = self._fingerprint()
            return SyncResult(
                True,
                "sync_off",
                "Vault em uso sem sincronização git.",
            )
        if self._in_progress():
            self.blocked = True
            return SyncResult(
                False,
                "busy",
                "Há uma operação git pela metade no vault. Não alterei nada.",
                read_only=True,
            )
        self._guardado = "clean"
        try:
            outcome = self._attempt_sync(retry=True, guardar=True)
        except VaultError:
            self._abort_if_merging()
            if self._guardado == "stashed":
                self._restore_stash()
            raise
        stashed = self._guardado
        if outcome == "stash_error":
            self.blocked = True
            self._snapshot = self._fingerprint()
            return SyncResult(
                False,
                "stash_error",
                "Há notas locais abertas e não consegui guardá-las de lado para atualizar. "
                "Não alterei nada. Nada foi apagado.",
                read_only=True,
            )
        self._abort_if_merging()
        restored = "ok"
        if stashed == "stashed":
            restored = self._restore_stash()
        self._snapshot = self._fingerprint()
        if restored == "conflict":
            return SyncResult(
                False,
                "stash_conflict",
                "A atualização do GitHub não coube nas notas locais ainda abertas. "
                "Elas continuam no stash do git. Nada foi apagado e nada foi enviado à força.",
                read_only=True,
            )
        result = self._result_from_outcome(
            outcome, False, idle="Sincronizado com o GitHub."
        )
        if stashed == "stashed" and restored == "ok" and result.action == "error":
            result.kept_open = True
            result.detail = (
                "Não consegui atualizar o vault com o GitHub. "
                "As notas que já estavam abertas continuam na pasta. Nada foi apagado."
            )
        return result

    def _publish(self, text):
        if not self.sync or self.blocked:
            return SyncResult(True, "skipped", "Sincronização não executada.")
        state = self._commit_paths(commit_message(text))
        if state == "error":
            return SyncResult(
                False,
                "commit_error",
                self._commit_error_detail(),
                read_only=True,
                committed=False,
            )
        committed = state == "committed"
        if self.remote_unavailable:
            if committed:
                return SyncResult(
                    True,
                    "offline",
                    "Notas gravadas neste computador. Não consegui enviá-las ao GitHub agora.",
                    offline=True,
                    committed=True,
                )
            return SyncResult(True, "offline", "Sem acesso ao GitHub. Nada novo para enviar.", offline=True)
        fatal = self._preflight()
        if fatal:
            fatal.committed = committed
            return fatal
        outcome = self._attempt_sync(retry=True)
        return self._result_from_outcome(
            outcome,
            committed,
            idle="Nada novo para enviar." if not committed else "Sincronizado com o GitHub.",
        )

    def _result_from_outcome(self, outcome, committed, idle="Sincronizado com o GitHub."):
        if outcome == "offline":
            detail = "Não consegui falar com o GitHub. As notas locais foram mantidas."
            if committed:
                detail = "Notas gravadas neste computador. Não consegui enviá-las ao GitHub agora."
            return SyncResult(True, "offline", detail, offline=True, committed=committed)
        if outcome == "conflict":
            return SyncResult(
                False,
                "conflict",
                "O histórico local e o remoto divergiram. Não apaguei notas nem forcei o envio.",
                read_only=True,
                committed=committed,
            )
        if outcome == "no_remote_branch":
            return SyncResult(
                False,
                "no_remote_branch",
                f"A branch {self.branch_name} não existe no remoto. Não criei branch nova.",
                read_only=True,
                committed=committed,
            )
        if outcome == "rejected":
            return SyncResult(
                False,
                "rejected",
                "O GitHub recusou o envio. As notas locais foram mantidas.",
                read_only=True,
                committed=committed,
            )
        if outcome == "error":
            return SyncResult(
                False,
                "error",
                "Não consegui atualizar o vault com o GitHub. "
                "As notas locais foram mantidas. Nada foi apagado.",
                committed=committed,
            )
        if outcome == "synced":
            return SyncResult(
                True,
                "synced",
                "Atualizado com o GitHub e notas enviadas.",
                committed=committed,
                pushed=True,
            )
        if outcome == "pushed":
            detail = "Notas enviadas ao GitHub."
            if committed:
                detail = "Notas gravadas e enviadas ao GitHub."
            return SyncResult(True, "pushed", detail, committed=committed, pushed=True)
        if outcome == "merged":
            return SyncResult(
                True,
                "pulled",
                "Atualizado com as notas do GitHub.",
                committed=committed,
            )
        return SyncResult(True, "ready", idle, committed=committed)

    def _attempt_sync(self, retry, guardar=False):
        if not self._fetch():
            self.remote_unavailable = True
            return "offline"
        integrated = self._integrate(guardar)
        if integrated in {"conflict", "error", "no_remote_branch", "stash_error"}:
            return integrated
        pushed = self._push()
        if pushed == "rejected" and retry:
            return self._attempt_sync(retry=False, guardar=guardar)
        if pushed == "pushed" and integrated == "merged":
            return "synced"
        if pushed == "ready" and integrated == "merged":
            return "merged"
        return pushed

    def _preflight(self):
        if not self._git_available():
            return self._fatal("no_git", "Não encontrei o git.", "instale o git e deixe-o no PATH")
        if not self.path.is_dir():
            return self._fatal(
                "missing",
                f"A pasta do vault não existe: {self.path}",
                "clone o repositório e aponte JARVIS_VAULT para essa pasta",
            )
        inside = self._git("rev-parse", "--is-inside-work-tree")
        if inside.code != 0 or inside.out.strip() != "true":
            return self._fatal(
                "not_repo",
                "A pasta do vault não é um repositório git.",
                "use um clone do vault, não uma cópia solta",
            )
        head = self._git("rev-parse", "-q", "--verify", "HEAD")
        if head.code != 0:
            return self._fatal(
                "no_commit",
                "O vault ainda não tem commits.",
                "faça o clone de novo",
            )
        branch = self._git("symbolic-ref", "--short", "HEAD")
        if branch.code != 0:
            return self._fatal(
                "detached",
                "O vault está com HEAD desanexado. Volte para a branch de trabalho. Não alterei nada.",
            )
        current = branch.out.strip()
        if not _valid_branch(current):
            return self._fatal("bad_branch", "O nome da branch atual não é seguro para sincronizar.")
        if self.branch_override:
            if not _valid_branch(self.branch_override):
                return self._fatal("bad_branch", "JARVIS_VAULT_BRANCH tem um nome inválido.")
            if self.branch_override != current:
                return self._fatal(
                    "bad_branch",
                    (
                        f"A branch atual é {current} e JARVIS_VAULT_BRANCH pede "
                        f"{self.branch_override}. Não troquei de branch."
                    ),
                )
        remote = self._match_remote()
        if not remote:
            return self._fatal(
                "mismatch",
                "O remoto do vault não é o repositório esperado. Não enviei nada.",
                "confira o remoto origin e JARVIS_VAULT_REMOTE",
            )
        self.branch_name = current
        self.remote_name = remote
        return None

    def _match_remote(self):
        listing = self._git("remote")
        if listing.code != 0:
            return None
        names = [name for name in listing.out.split() if name]
        expected = normalize_remote(self.expected_remote)
        if not expected:
            if "origin" in names:
                return "origin"
            if len(names) == 1:
                return names[0]
            return None
        for name in names:
            url = self._git("remote", "get-url", name).out.strip()
            if normalize_remote(url) == expected:
                return name
        return None

    def _integrate(self, guardar=False):
        counts = self._ahead_behind()
        if counts is None:
            return "no_remote_branch"
        ahead, behind = counts
        if behind == 0:
            return "up_to_date"
        ref = f"{self.remote_name}/{self.branch_name}"
        if ahead == 0:
            result = self._git("merge", "--ff-only", ref)
            if result.code != 0 and guardar and not self._in_progress():
                if self._guardar_abertas() == "error":
                    return "stash_error"
                if self._guardado == "stashed":
                    result = self._git("merge", "--ff-only", ref)
        else:
            if guardar and self._guardar_abertas() == "error":
                return "stash_error"
            result = self._git("merge", "-m", MERGE_MESSAGE, ref)
        if result.code == 0:
            return "merged"
        if self._in_progress():
            self._git("merge", "--abort")
            return "conflict"
        return "error"

    def _push(self):
        counts = self._ahead_behind()
        if counts is None:
            return "no_remote_branch"
        ahead, behind = counts
        if behind > 0:
            return "rejected"
        if ahead == 0:
            return "ready"
        result = self._git("push", self.remote_name, f"HEAD:{self.branch_name}")
        if result.code == 0:
            return "pushed"
        return "rejected"

    def _commit_paths(self, message):
        paths = self._paths_to_commit()
        if not paths:
            return "clean"
        added = self._git("add", "--", *paths)
        if added.code != 0:
            self._last_git_error = added.err or added.out
            return "error"
        if self._git("diff", "--cached", "--quiet").code == 0:
            return "clean"
        result = self._git("commit", "-m", message)
        if result.code != 0:
            self._last_git_error = result.err or result.out
            return "error"
        return "committed"

    def _paths_to_commit(self):
        if self._snapshot is None:
            changed = list(self._status_paths())
        else:
            after = self._fingerprint()
            changed = []
            for path, digest in after.items():
                if path not in self._snapshot or self._snapshot[path] != digest:
                    changed.append(path)
        accepted = []
        for path in changed:
            motivo = self._motivo_publicacao(path)
            if motivo:
                from .guardas import registrar_recusa

                registrar_recusa(motivo)
                # .obsidian e credencial ficam no disco e fora do commit.
                if motivo not in {"obsidian", "credencial"}:
                    self._desfazer_escrita(path)
                continue
            accepted.append(path)
        return accepted

    def _motivo_publicacao(self, path):
        from .guardas import motivo_arquivo

        if not self._committable(path):
            normalized = path.replace("\\", "/")
            if normalized == ".obsidian" or normalized.startswith(".obsidian/") or "/.obsidian/" in "/" + normalized:
                return "obsidian"
            return "credencial"
        return motivo_arquivo(self.path, path)

    def _desfazer_escrita(self, relative):
        raw = self.path / relative
        try:
            if raw.is_symlink():
                raw.unlink()
                return
        except OSError:
            return
        existed = self._existia(relative)
        tracked = self._git("ls-files", "--error-unmatch", "--", relative)
        if tracked.code == 0:
            self._git("checkout", "--", relative)
            return
        if existed:
            return
        try:
            if raw.is_file():
                raw.unlink()
        except OSError:
            return

    def _existia(self, path):
        if self._snapshot is None:
            return True
        return path in self._snapshot and self._snapshot[path] is not None

    def _fingerprint(self):
        found = {}
        for path in self._status_paths():
            full = self.path / path
            if full.is_file():
                found[path] = hashlib.sha256(full.read_bytes()).hexdigest()
            elif not full.exists():
                found[path] = None
            else:
                found[path] = "other"
        return found

    def _status_paths(self):
        result = self._git(
            "-c", "core.quotepath=false", "status", "--porcelain=v1", "-uall", "-z"
        )
        if result.code != 0 or not result.out:
            return []
        records = result.out.split("\0")
        paths = []
        index = 0
        while index < len(records):
            entry = records[index]
            index += 1
            if len(entry) < 4:
                continue
            status = entry[:2]
            path = entry[3:]
            if "R" in status or "C" in status:
                if index < len(records):
                    path = records[index]
                    index += 1
            if path:
                paths.append(path)
        return paths

    def _committable(self, path):
        normalized = path.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        normalized = normalized.lstrip("/")
        if normalized == ".obsidian" or normalized.startswith(".obsidian/"):
            return False
        name = Path(normalized).name
        if name == ".env" or name.startswith(".env."):
            return False
        if name.endswith((".pem", ".key")):
            return False
        return True

    def _guardar_abertas(self):
        if self._guardado == "stashed":
            return "stashed"
        estado = self._stash_if_dirty()
        if estado != "error":
            self._guardado = estado
        return estado

    def _stash_if_dirty(self):
        if not self._is_dirty():
            return "clean"
        result = self._git(
            "stash", "push", "--include-untracked", "-m", STASH_MESSAGE
        )
        if result.code != 0 or self._is_dirty():
            self._last_git_error = result.err or result.out
            return "error"
        return "stashed"

    def _restore_stash(self):
        result = self._git("stash", "pop")
        if result.code == 0:
            return "ok"
        verify = self._git("rev-parse", "-q", "--verify", "stash@{0}")
        if verify.code != 0:
            return "conflict"
        self._allow_merge_reset = True
        try:
            reset = self._git("reset", "--merge")
        finally:
            self._allow_merge_reset = False
        if reset.code != 0:
            return "conflict"
        still = self._git("rev-parse", "-q", "--verify", "stash@{0}")
        if still.code != 0:
            return "conflict"
        return "conflict"

    def _is_dirty(self):
        result = self._git("status", "--porcelain")
        return bool(result.out.strip())

    def _abort_if_merging(self):
        if self._in_progress():
            self._git("merge", "--abort")

    def _in_progress(self):
        for ref in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            result = self._git("rev-parse", "-q", "--verify", ref)
            if result.code == 0:
                return True
        return False

    def _ahead_behind(self):
        ref = f"{self.remote_name}/{self.branch_name}"
        verify = self._git("rev-parse", "-q", "--verify", ref)
        if verify.code != 0:
            return None
        result = self._git("rev-list", "--left-right", "--count", f"HEAD...{ref}")
        if result.code != 0:
            return None
        parts = result.out.split()
        if len(parts) != 2:
            return None
        return int(parts[0]), int(parts[1])

    def _fetch(self):
        return self._git("fetch", self.remote_name).code == 0

    def _commit_error_detail(self):
        return (
            "Não consegui criar o commit. Confira user.name e user.email do git. "
            "As notas continuam na pasta."
        )

    def _fatal(self, action, detail, fix=""):
        self.blocked = True
        return SyncResult(False, action, detail, fatal=True, read_only=True, fix=fix)

    def _reset_flags(self):
        self.remote_unavailable = False
        self.blocked = False
        self.remote_name = ""
        self.branch_name = ""
        self._last_git_error = ""
        self._snapshot = None
        self._allow_merge_reset = False
        self._guardado = "clean"

    def _git_available(self):
        candidate = Path(self.git_bin)
        if candidate.is_file():
            return True
        return shutil.which(self.git_bin) is not None

    def _git(self, *args):
        from .procutil import command_argv, run_text

        self._guard(args)
        command = command_argv(self.git_bin, "-C", str(self.path), *args)
        if command is None:
            return GitResult(1, "", "git não encontrado")
        result = run_text(command, self.timeout, env=self._env())
        if result.timed_out:
            self._last_git_error = "tempo esgotado"
            if args and args[0] == "merge":
                self._abort_merge_process()
            return GitResult(124, "", "tempo esgotado")
        if result.os_error:
            return GitResult(1, "", result.err)
        return GitResult(result.code, result.out, result.err)

    def _abort_merge_process(self):
        from .procutil import command_argv, run_text

        command = command_argv(self.git_bin, "-C", str(self.path), "merge", "--abort")
        if command is None:
            return
        run_text(command, 15, env=self._env())

    def _guard(self, args):
        if not args:
            return
        command = args[0]
        if command == "reset":
            allowed = self._allow_merge_reset and list(args) == ["reset", "--merge"]
            if not allowed:
                raise VaultError("comando git bloqueado")
            return
        if command in {"clean", "rebase"}:
            raise VaultError("comando git bloqueado")
        if command != "push":
            return
        for arg in args[1:]:
            if arg in {"-f", "--force", "--force-with-lease", "--force-if-includes"}:
                raise VaultError("push forçado bloqueado")
            if arg.startswith("--force") or arg.startswith("+"):
                raise VaultError("push forçado bloqueado")

    def _env(self):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        env.update(self.extra_env)
        return env


def _print_checks(checks):
    code = 0
    for item in checks:
        print(f"[{item.level}] {item.name}: {item.detail}")
        if item.fix and item.level != "ok":
            print(f"    {item.fix}")
        if item.level == "fail":
            code = 1
    return code


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    vault = Vault.from_env()
    if vault is None:
        print("Defina JARVIS_VAULT com o caminho do clone local do vault.")
        return 1
    if not args:
        return _print_checks(vault.diagnose())
    code = 0
    if "--pull" in args:
        result = vault.prepare()
        print(result.detail)
        if not result.ok or result.fatal:
            code = 1
    if "--publish" in args:
        text = " ".join(part for part in args if not part.startswith("--"))
        result = vault.publish(text, pending=True)
        print(result.detail)
        if not result.ok or result.fatal:
            code = 1
    if "--pull" not in args and "--publish" not in args:
        return _print_checks(vault.diagnose())
    return code


if __name__ == "__main__":
    sys.exit(main())
