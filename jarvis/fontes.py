"""Conta notas por pasta e por tipo de fonte. A fala não leva o texto da nota."""

from pathlib import Path

from .readwise import folder_from_env
from .review import parse_card_line
from .routines import _join_pt, _read, _safe_relative, _without_frontmatter, fold, iter_notes

_TYPE_KEYS = {"tipo", "type", "fonte", "source", "origem", "categoria", "category"}
_BOOKS = {"livro", "livros", "book", "books"}
_VIDEOS = {"video", "videos", "vídeo", "vídeos"}
_COURSES = {"curso", "cursos", "course", "courses"}
_READWISE = {"readwise"}


class SourceStats:
    def __init__(self):
        self.notes = 0
        self.folders = {}
        self.livros = 0
        self.videos = 0
        self.cursos = 0
        self.readwise = 0
        self.cards = 0


def sources_speech(root):
    if root is None or not Path(root).is_dir():
        return (
            "O vault não está configurado, senhor. "
            "Sem ele eu não conto as fontes. "
            "Rode python -m jarvis.setup."
        )
    stats = collect_sources(root)
    if stats.notes == 0:
        return "Não há nota no vault, senhor."
    folders = _folder_phrase(stats.folders)
    return (
        "Senhor, as notas por pasta: "
        + folders
        + ". Livros, "
        + str(stats.livros)
        + ". Vídeos, "
        + str(stats.videos)
        + ". Cursos, "
        + str(stats.cursos)
        + ". Readwise, "
        + str(stats.readwise)
        + ". Cartões de pergunta e resposta, "
        + str(stats.cards)
        + "."
    )


def collect_sources(root):
    stats = SourceStats()
    prefix = fold(_safe_relative(folder_from_env()))
    root = Path(root)
    for path in iter_notes(root):
        relative = _relative(root, path)
        if not relative:
            continue
        text = _read(path)
        stats.notes += 1
        top = relative.split("/", 1)[0]
        if top.endswith(".md"):
            top = "raiz"
        stats.folders[top] = stats.folders.get(top, 0) + 1
        kinds = _kinds(relative, _frontmatter(text), prefix)
        if "livros" in kinds:
            stats.livros += 1
        if "videos" in kinds:
            stats.videos += 1
        if "cursos" in kinds:
            stats.cursos += 1
        if "readwise" in kinds:
            stats.readwise += 1
        stats.cards += _cards(text)
    return stats


def _folder_phrase(folders):
    names = sorted(folders, key=fold)
    bits = [f"{count} em {name}" for name, count in ((name, folders[name]) for name in names)]
    return _join_pt(bits)


def _kinds(relative, meta, prefix):
    found = set()
    parts = [fold(part) for part in relative.split("/")]
    folders = parts[:-1]
    values = set()
    for key, value in meta.items():
        if key in _TYPE_KEYS or key == "tags":
            values.add(value)
    if _hit(folders, values, _BOOKS):
        found.add("livros")
    if _hit(folders, values, _VIDEOS):
        found.add("videos")
    if _hit(folders, values, _COURSES):
        found.add("cursos")
    folded = fold(relative)
    if _hit(folders, values, _READWISE) or (prefix and (folded == prefix or folded.startswith(prefix + "/"))):
        found.add("readwise")
    return found


def _hit(folders, values, names):
    folded_names = {fold(name) for name in names}
    if any(part in folded_names for part in folders):
        return True
    for value in values:
        tokens = set(fold(value).replace(",", " ").split())
        if tokens & folded_names:
            return True
    return False


def _cards(text):
    count = 0
    for line in _without_frontmatter(text).splitlines():
        if parse_card_line(line):
            count += 1
    return count


def _frontmatter(text):
    raw = text or ""
    if not raw.startswith("---"):
        return {}
    end = raw.find("\n---", 3)
    if end == -1:
        return {}
    found = {}
    for line in raw[3:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        key = fold(key.strip())
        value = value.strip().strip("\"'")
        if key and value:
            found[key] = value
    return found


def _relative(root, path):
    try:
        relative = path.resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        return ""
    parts = [part for part in relative.split("/") if part]
    if not parts or any(part == ".obsidian" or part.startswith(".") for part in parts):
        return ""
    return "/".join(parts)
