"""Oferta de gravar o resumo do dia, compartilhada entre os processos do Jarvis."""

from .state import load, update


def load_offer():
    data = load().get("offer")
    if not isinstance(data, dict) or data.get("kind") != "day":
        return None
    relative = data.get("relative")
    body = data.get("body")
    if not isinstance(relative, str) or not isinstance(body, str):
        return None
    if not _safe_relative(relative) or not body.strip():
        return None
    return {"kind": "day", "relative": relative, "body": body}


def store_offer(pending):
    if not isinstance(pending, dict) or pending.get("kind") != "day":
        return
    relative = pending.get("relative") or ""
    body = pending.get("body") or ""
    if not _safe_relative(relative) or not str(body).strip():
        return

    def mutate(data):
        data["offer"] = {
            "kind": "day",
            "relative": relative,
            "body": str(body)[:20000],
        }

    update(mutate)


def clear_offer():
    def mutate(data):
        data.pop("offer", None)

    update(mutate)


def _safe_relative(relative):
    from .paths import relativo_oferta

    return relativo_oferta(relative)
