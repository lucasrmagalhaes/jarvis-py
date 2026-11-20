"""Bloqueia escrita em .obsidian, em credencial e em texto com cara de segredo.

O mesmo critério vale para o Jarvis e para o hook gratuito do Claude Code.
"""

import json
import re
import shlex
import sys
from pathlib import Path

FALA_BLOQUEIO = "Não gravei, senhor. A escrita foi bloqueada."
HOOK_MATCHER = "Write|Edit|MultiEdit|NotebookEdit"
NEGAR_TUDO = "Read(./**)"
_CREDENTIAL_NAMES = {
    ".netrc",
    "credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "secrets.json",
}
_CREDENTIAL_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".kdbx")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"(?i)(?:^|[\s\"'`])(password|passwd|senha|api[_-]?key|secret|token|access[_-]?key)"
        r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-+/=]{12,})"
    ),
)


class GuardError(Exception):
    def __init__(self, motivo="escrita bloqueada"):
        self.motivo = "escrita bloqueada"
        super().__init__(self.motivo)


_MOTIVOS = {"obsidian", "credencial", "fora", "vazio", "segredo", "sigilo"}


def registrar_recusa(motivo):
    """Registra só o código. Não grava caminho, pergunta nem conteúdo."""
    from .log import LOG

    code = motivo if motivo in _MOTIVOS else "bloqueada"
    LOG.info("escrita recusada: %s", code)


def motivo_caminho(path, raiz=None):
    blocked = caminho_bloqueado(path)
    if blocked:
        if "obsidian" in blocked:
            return "obsidian"
        return "credencial"
    if raiz is not None and not caminho_dentro(raiz, path):
        return "fora"
    return None


def caminho_dentro(raiz, path):
    base = Path(raiz).expanduser()
    try:
        base_resolved = base.resolve()
    except OSError:
        return False
    raw = Path(path)
    if not raw.is_absolute():
        raw = base / raw
    try:
        resolved = raw.resolve()
        resolved.relative_to(base_resolved)
    except (OSError, ValueError):
        return False
    return True


def motivo_da_escrita(path, text, raiz=None, amostra=None):
    motivo = motivo_caminho(path, raiz)
    if motivo:
        return motivo
    if text is None or not str(text).strip():
        return "vazio"
    sample = text if amostra is None else amostra
    if texto_secreto(str(sample or "")):
        return "segredo"
    return None


def motivo_arquivo(raiz, path):
    motivo = motivo_caminho(path, raiz)
    if motivo:
        return motivo
    raw = Path(path)
    if not raw.is_absolute() and raiz is not None:
        raw = Path(raiz) / raw
    if not raw.is_file():
        return None
    try:
        data = raw.read_bytes()
    except OSError:
        return None
    if not data.strip():
        return "vazio"
    sample = data[:200_000].decode("utf-8", errors="replace")
    if texto_secreto(sample):
        return "segredo"
    return None


def validar_saida(path, text, raiz=None):
    motivo = motivo_da_escrita(path, text, raiz=raiz)
    if motivo:
        registrar_recusa(motivo)
    return motivo


def _parts(path):
    raw = str(path or "").replace("\\", "/")
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return parts


def caminho_bloqueado(path):
    parts = _parts(path)
    if not parts:
        return None
    if any(part == ".obsidian" for part in parts):
        return "escrita em .obsidian bloqueada"
    name = parts[-1]
    lower = name.casefold()
    if lower == ".env" or lower.startswith(".env."):
        return "arquivo de credencial bloqueado"
    if lower in _CREDENTIAL_NAMES or lower.endswith(_CREDENTIAL_SUFFIXES):
        return "arquivo de credencial bloqueado"
    return None


def texto_secreto(text):
    sample = text or ""
    if not sample.strip():
        return False
    for pattern in _SECRET_PATTERNS:
        if pattern.search(sample):
            return True
    return False


def escrever(path, text, checar=None, raiz=None):
    motivo = motivo_da_escrita(path, text, raiz=raiz, amostra=checar)
    if motivo:
        registrar_recusa(motivo)
        raise GuardError("escrita bloqueada")
    from .trava import fila_escrita, gravar_atomico

    with fila_escrita():
        gravar_atomico(Path(path), text)


def tentar(path, text, checar=None, raiz=None):
    try:
        escrever(path, text, checar=checar, raiz=raiz)
    except GuardError:
        return False
    return True


def avaliar_ferramenta(payload):
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("tool_name") or "")
    if name not in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        return None
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    paths = []
    samples = []
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if file_path:
        paths.append(str(file_path))
    for key in ("content", "new_string", "new_source"):
        value = tool_input.get(key)
        if value:
            samples.append(str(value))
    edits = tool_input.get("edits") or []
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict) and edit.get("new_string"):
                samples.append(str(edit.get("new_string")))
    raiz = _raiz_configurada()
    for item in paths:
        try:
            from .privacidade import bloqueio_nuvem
        except Exception:
            bloqueio_nuvem = None
        if bloqueio_nuvem is not None and bloqueio_nuvem(raiz, item, "escrita"):
            registrar_recusa("sigilo")
            return bloqueio_nuvem(raiz, item, "escrita")
        motivo = motivo_caminho(item, raiz)
        if motivo:
            registrar_recusa(motivo)
            if motivo == "fora":
                return "Escrita bloqueada: caminho fora do vault."
            return "Escrita bloqueada nesse caminho."
    if name in {"Write", "NotebookEdit"}:
        blob = tool_input.get("content")
        if blob is None:
            blob = tool_input.get("new_source")
        if not str(blob or "").strip():
            registrar_recusa("vazio")
            return "Escrita bloqueada: conteúdo vazio."
    for sample in samples:
        if texto_secreto(sample):
            registrar_recusa("segredo")
            return "Escrita bloqueada: o texto tem cara de segredo."
    return None


def _raiz_configurada():
    try:
        from . import config
    except Exception:
        return None
    return config.vault_dir()


def comando_do_hook():
    root = Path(__file__).resolve().parents[1]
    script = (
        "import sys; sys.path.insert(0, "
        + json.dumps(str(root))
        + "); from jarvis.guardas import main; raise SystemExit(main())"
    )
    return shlex.quote(sys.executable) + " -c " + shlex.quote(script)


def documento_de_hooks(command=None, negar=None):
    documento = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": HOOK_MATCHER,
                    "hooks": [
                        {
                            "type": "command",
                            "command": command or comando_do_hook(),
                            "timeout": 15,
                        }
                    ],
                },
                {
                    "matcher": "Read|Glob|Grep",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command or comando_do_hook(),
                            "timeout": 15,
                        }
                    ],
                },
            ]
        }
    }
    if negar:
        documento["permissions"] = {"deny": list(negar)}
    return documento


def regras_de_negacao():
    raiz = _raiz_configurada()
    if raiz is None:
        return []
    try:
        from .privacidade import regras_de_leitura

        return regras_de_leitura(raiz)
    except Exception:
        from .log import LOG

        LOG.error("sigilo: lista indisponivel, leitura fechada neste turno")
        return [NEGAR_TUDO]


def arquivo_de_hooks():
    from . import config

    home = config.jarvis_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    path = home / "claude-hooks.json"
    try:
        path.write_text(
            json.dumps(
                documento_de_hooks(negar=regras_de_negacao()),
                ensure_ascii=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError:
        return None
    return path


def main(argv=None):
    del argv
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    try:
        from .privacidade import avaliar_leitura
    except Exception:
        avaliar_leitura = None
    reason = avaliar_ferramenta(payload)
    if not reason and avaliar_leitura is not None:
        reason = avaliar_leitura(payload)
    if not reason:
        return 0
    sys.stderr.write(reason + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
