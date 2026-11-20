"""Memória curta da sessão.

Fica na memória do processo. Se JARVIS_CONTEXTO não estiver off, também
grava em ~/.jarvis/contexto.json só o que o senhor disse e a fala do
Jarvis quando ela não é trecho de nota.
"""

import json
import threading


def _clip(text, limit=400):
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _public_reply(text):
    """Tira da cópia em disco o que parece trecho de nota."""
    cleaned = _clip(text)
    folded = cleaned.casefold()
    if ".md" in folded or "caminho " in folded:
        return ""
    if folded.startswith("uma nota que faz tempo"):
        return ""
    return cleaned


def context_file():
    from . import config

    return config.context_file()


class SessionMemory:
    def __init__(self, limit=None, persist=None):
        from . import config

        self.limit = config.context_turns() if limit is None else limit
        if persist is None:
            persist = config.context_persist()
        self.persist = bool(persist)
        self.turns = []
        self._lock = threading.RLock()
        if self.persist:
            self._load()

    def remember(self, user, reply):
        with self._lock:
            self.turns.append(("Senhor", _clip(user)))
            self.turns.append(("Jarvis", _clip(reply)))
            extra = len(self.turns) - self.limit * 2
            if extra > 0:
                del self.turns[:extra]
            self._save()

    def clear(self):
        with self._lock:
            self.turns.clear()
            self._save()

    def last_reply(self):
        with self._lock:
            for who, text in reversed(self.turns):
                if who == "Jarvis" and text:
                    return text
            return ""

    def as_prompt(self):
        with self._lock:
            if not self.turns:
                return ""
            lines = [f"{who}: {text}" for who, text in self.turns if text]
            if not lines:
                return ""
            return (
                "Contexto recente desta sessão, só para entender uma pergunta de seguimento:\n"
                + "\n".join(lines)
            )

    def _load(self):
        path = context_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        rows = data.get("turnos") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return
        loaded = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            user = _clip(row.get("senhor") or "")
            reply = _public_reply(row.get("jarvis") or "")
            if not user and not reply:
                continue
            loaded.append(("Senhor", user))
            loaded.append(("Jarvis", reply))
        extra = len(loaded) - self.limit * 2
        if extra > 0:
            del loaded[:extra]
        self.turns = loaded

    def _save(self):
        if not self.persist:
            return
        with self._lock:
            self._gravar()

    def _gravar(self):
        path = context_file()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        turnos = []
        index = 0
        while index + 1 < len(self.turns):
            user = self.turns[index][1] if self.turns[index][0] == "Senhor" else ""
            reply = self.turns[index + 1][1] if self.turns[index + 1][0] == "Jarvis" else ""
            turnos.append({"senhor": user, "jarvis": _public_reply(reply)})
            index += 2
        raw = json.dumps({"versao": 1, "turnos": turnos}, ensure_ascii=False).encode("utf-8")
        from .trava import TravaOcupada, gravar_atomico, trava_arquivo

        try:
            with trava_arquivo(path.with_name(path.name + ".lock"), espera=2):
                gravar_atomico(path, raw, mode=0o600)
        except (OSError, TravaOcupada):
            return
