"""Mede a busca: acerto nos 3 primeiros e a frase de falta de evidência.

O repositório só traz um vault inventado. As perguntas reais ficam em
~/.jarvis/avaliacao.yaml, fora do git.
"""

import re
import sys
from pathlib import Path

from . import config
from .busca import fold

EXAMPLE_ROOT = Path(__file__).resolve().parents[1] / "avaliacao"
EXAMPLE_VAULT = EXAMPLE_ROOT / "vault"
EXAMPLE_YAML = EXAMPLE_ROOT / "exemplo.yaml"
HELP = """\
Uso:
  python -m jarvis.avaliar
  python -m jarvis.avaliar --exemplo

Sem ~/.jarvis/avaliacao.yaml, mede o vault de exemplo deste repositório.
Com esse arquivo, mede as perguntas de lá no clone de JARVIS_VAULT.
--exemplo força o vault inventado e não lê o arquivo de fora do git.
"""


def pessoal_path():
    return config.jarvis_home() / "avaliacao.yaml"


def _yaml_str(value):
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]
    return text.strip()


def load_cases(text):
    casos = []
    current = None
    espera_list = False
    for raw in (text or "").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            espera_list = False
            continue
        if stripped == "casos:":
            espera_list = False
            continue
        item = re.match(r"^\s*-\s+pergunta\s*:\s*(.*)$", raw)
        if item:
            if current:
                casos.append(_finish(current))
            current = {
                "pergunta": _yaml_str(item.group(1)),
                "espera": [],
                "evidencia": None,
            }
            espera_list = False
            continue
        if current is None:
            continue
        espera = re.match(r"^\s+espera\s*:\s*(.*)$", raw)
        if espera:
            value = espera.group(1).strip()
            if not value:
                current["espera"] = []
                espera_list = True
            else:
                current["espera"] = [_yaml_str(value)]
                espera_list = False
            continue
        bullet = re.match(r"^\s+-\s+(.*)$", raw)
        if bullet and espera_list:
            current["espera"].append(_yaml_str(bullet.group(1)))
            continue
        flag = re.match(r"^\s+evidencia\s*:\s*(true|false|sim|nao|não)\s*$", raw, re.I)
        if flag:
            current["evidencia"] = flag.group(1).casefold() in {"true", "sim"}
            espera_list = False
            continue
        espera_list = False
    if current:
        casos.append(_finish(current))
    return [caso for caso in casos if caso["pergunta"]]


def _finish(caso):
    if caso["evidencia"] is None:
        caso["evidencia"] = bool(caso["espera"])
    return caso


def _declares_gap(result):
    text = (result.get("answer") or "").casefold()
    folded = fold(text)
    return "não há evidência" in text or "nao ha evidencia" in folded


def medir(root, casos, embedder=None):
    from .consult import answer

    positivos = [caso for caso in casos if caso["evidencia"]]
    negativos = [caso for caso in casos if not caso["evidencia"]]
    acertos = 0
    recusas = 0
    falhas = []
    for caso in positivos:
        result = answer(root, caso["pergunta"], embedder=embedder)
        paths = [source.get("path") for source in result["sources"][:3]]
        esperados = caso["espera"]
        hit = any(path in paths for path in esperados) if esperados else bool(result["evidence"])
        if hit and result["evidence"]:
            acertos += 1
        else:
            falhas.append(caso["pergunta"])
    for caso in negativos:
        result = answer(root, caso["pergunta"], embedder=embedder)
        if (not result["evidence"]) and _declares_gap(result):
            recusas += 1
        else:
            falhas.append(caso["pergunta"])
    return {
        "acertos": acertos,
        "positivos": len(positivos),
        "recusas": recusas,
        "negativos": len(negativos),
        "falhas": falhas,
        "ok": acertos == len(positivos) and recusas == len(negativos) and bool(casos),
    }


def format_report(report, origem):
    lines = [
        f"Origem: {origem}.",
        f"Acerto nos 3 primeiros: {report['acertos']}/{report['positivos']}.",
        f"Recusa quando não há evidência: {report['recusas']}/{report['negativos']}.",
    ]
    if report["falhas"]:
        lines.append("Fora do esperado: " + str(len(report["falhas"])) + " caso(s).")
    else:
        lines.append("Todos os casos do conjunto bateram.")
    return "\n".join(lines)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        print(HELP)
        return 0
    if any(item.startswith("-") and item != "--exemplo" for item in args):
        print(HELP)
        return 2
    exemplo = "--exemplo" in args
    pessoal = pessoal_path()
    if pessoal.is_file() and not exemplo:
        root = config.vault_dir()
        if root is None or not Path(root).is_dir():
            print(
                "Há perguntas em "
                + str(pessoal)
                + ", mas JARVIS_VAULT não aponta para uma pasta."
            )
            return 1
        try:
            casos = load_cases(pessoal.read_text(encoding="utf-8"))
        except OSError:
            print("Não consegui ler " + str(pessoal) + ".")
            return 1
        origem = "perguntas locais, fora do git"
        vault = root
    else:
        if not EXAMPLE_VAULT.is_dir() or not EXAMPLE_YAML.is_file():
            print("O vault de exemplo não está no repositório.")
            return 1
        casos = load_cases(EXAMPLE_YAML.read_text(encoding="utf-8"))
        origem = "vault de exemplo"
        vault = EXAMPLE_VAULT
    if not casos:
        print("Nenhum caso para medir.")
        return 1
    report = medir(vault, casos)
    print(format_report(report, origem))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
