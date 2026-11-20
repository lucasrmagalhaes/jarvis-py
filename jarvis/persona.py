"""Persona falada. A nota do vault, se existir, entra no prefixo estável."""

import re
from pathlib import Path

DEFAULT_RELATIVE = "Jarvis/Persona.md"
MAX_CHARS = 4000
PREVIEW_CHARS = 320

PERSONA = """Você é o JARVIS, assistente pessoal de inteligência artificial no estilo do assistente de Tony Stark.

Personalidade:
- Trate o usuário como "senhor", com cortesia britânica e humor seco ocasional.
- Seja preciso, competente e levemente espirituoso, nunca bajulador.

Formato das respostas (elas serão convertidas em fala):
- Responda sempre em português do Brasil.
- Use frases curtas e naturais, próprias para serem ditas em voz alta.
- Nunca use markdown, listas com marcadores, emojis, URLs longas ou blocos de código na resposta final.
- Se a tarefa envolver código, arquivos ou pesquisa, execute o trabalho com suas ferramentas e resuma o resultado verbalmente.
- Conversas casuais: no máximo três frases. Relatórios de tarefas: no máximo seis frases.
"""

_FRONT = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)


def persona_relative():
    from . import config

    return _safe_relative(config.persona_relativa())


def load_persona(root):
    """Devolve (texto, origem, caminho). origem é 'nota' ou 'padrao'."""
    relative = persona_relative()
    if root is None or not relative:
        return PERSONA, "padrao", relative or DEFAULT_RELATIVE
    path = (Path(root) / relative).resolve()
    if not _inside(path, root) or not path.is_file():
        return PERSONA, "padrao", relative
    if _blocked(path, root):
        return PERSONA, "padrao", relative
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return PERSONA, "padrao", relative
    body = _normalize(_strip_frontmatter(raw))
    if not body:
        return PERSONA, "padrao", relative
    return body, "nota", relative


def persona_text(root):
    text, _origin, _relative = load_persona(root)
    return text


def persona_speech(root):
    text, origin, relative = load_persona(root)
    if origin == "nota":
        preview = _preview(text)
        speech = f"A persona vem da nota {relative}, senhor."
        if preview:
            speech += " " + preview
        return speech
    return (
        "Estou com a persona padrão, senhor. "
        "Trato o senhor com cortesia, falo em português do Brasil e uso frases curtas."
    )


def _strip_frontmatter(text):
    return _FRONT.sub("", text or "", count=1)


def _normalize(text):
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u2014", ", ").replace("\u2013", ", ")
    cleaned = "".join(char for char in cleaned if char in "\n\t" or char >= " ")
    cleaned = cleaned.strip()
    if len(cleaned) > MAX_CHARS:
        cleaned = cleaned[:MAX_CHARS].rstrip()
    return cleaned


def _preview(text):
    plain = re.sub(r"[#>*_`\[\]]", " ", text or "")
    plain = " ".join(plain.split())
    if len(plain) <= PREVIEW_CHARS:
        return plain
    cut = plain[:PREVIEW_CHARS].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "."


def _safe_relative(raw):
    from .paths import caminho_relativo

    text = (raw or "").strip().replace("\\", "/")
    if not text.lower().endswith(".md"):
        return ""
    return caminho_relativo(text, exigir_md=True)


def _blocked(path, root):
    try:
        relative = path.resolve().relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return True
    return any(part == ".obsidian" or part.startswith(".") for part in relative.parts)


def _inside(path, root):
    from .paths import esta_dentro

    return esta_dentro(path, root, oserror=True)
