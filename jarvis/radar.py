"""Avisos somente leitura: PR com review pedido, status no Jira e e-mail importante.

A primeira consulta de cada fonte só memoriza. O mesmo item não se repete.
Há um intervalo mínimo entre falas. Não comenta, não altera issue e não envia e-mail.
"""

import threading
from datetime import datetime, timezone

from .log import LOG
from .state import load, update

CAP = 3
SEEN_LIMIT = 200
SOURCES = ("github", "jira", "mail")


class RadarService:
    def __init__(
        self,
        speak,
        bus,
        lock,
        interval=300,
        also=None,
        clock=None,
        fetch=None,
        cooldown=900,
    ):
        self.speak = speak
        self.bus = bus
        self.lock = lock or threading.RLock()
        self.interval = interval
        self.also = also
        self.clock = clock
        self.fetch = fetch or fetch_samples
        self.cooldown = cooldown
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="jarvis-radar", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def tick(self, now=None):
        with self.lock:
            return self._tick(now)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:
                LOG.error("radar: ciclo falhou")

    def _tick(self, now):
        moment = now or (self.clock() if self.clock else datetime.now(timezone.utc))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        try:
            samples = self.fetch()
        except Exception:
            LOG.error("radar: consulta falhou")
            return ""
        if not isinstance(samples, dict):
            return ""
        current = load().get("radar")
        if not isinstance(current, dict):
            current = {}
        from .alerts import control_for, remember_last

        speech, nxt = decide(
            current,
            samples,
            moment,
            self.cooldown,
            control=control_for(moment),
        )
        spoken_ids = nxt.pop("spoken_ids", []) if isinstance(nxt, dict) else []
        if nxt != _normalize(current):
            try:
                update(lambda data: data.__setitem__("radar", nxt))
            except Exception:
                LOG.error("radar: não guardei o estado")
                return ""
        if speech:
            if spoken_ids:
                try:
                    remember_last(spoken_ids)
                except Exception:
                    LOG.error("radar: não guardei o aviso")
            self._deliver(speech)
        return speech

    def _deliver(self, text):
        print(f"\nJARVIS: {text}")
        if self.bus is not None:
            self.bus.transcript("reply", text)
            self.bus.state("speaking")
        try:
            if self.speak is not None:
                self.speak(text)
            if self.also is not None:
                self.also(text)
        finally:
            if self.bus is not None:
                self.bus.state("standby")


def fetch_samples():
    from .external import github_review_sample, important_mail_sample, jira_status_sample

    samples = {}
    for name, func in (
        ("github", github_review_sample),
        ("jira", jira_status_sample),
        ("mail", important_mail_sample),
    ):
        try:
            samples[name] = func()
        except Exception:
            LOG.error("radar: %s falhou", name)
            samples[name] = ("error", [])
    return samples


def decide(state, samples, now, cooldown, cap=CAP, control=None):
    previous = _normalize(state)
    working = _copy(previous)
    events = []
    for source in SOURCES:
        sample = _sample(samples, source)
        if sample is None or sample[0] != "ok":
            continue
        items = _clean(source, sample[1])
        if not working["seeded"].get(source):
            working["seeded"][source] = True
            working[source] = _baseline(source, items)
            continue
        events.extend(_changes(source, working, items))
    control = control or {}
    if control.get("paused"):
        return "", previous
    if not events:
        _absorb(working, samples)
        working["spoken_ids"] = []
        return "", working
    speak, hold = _split_muted(events, control)
    if not speak:
        _absorb(working, samples)
        _restore_held(previous, working, hold)
        working["spoken_ids"] = []
        return "", working
    last = _parse_time(previous.get("last_spoken"))
    if last is not None and cooldown > 0 and (now - last).total_seconds() < cooldown:
        return "", previous
    _absorb(working, samples)
    _restore_held(previous, working, hold)
    working["last_spoken"] = now.isoformat()
    shown = speak[:cap]
    working["spoken_ids"] = [ident for ident in (_event_id(event) for event in shown) if ident]
    return _speech(speak, cap), working


def _sample(samples, source):
    if not isinstance(samples, dict):
        return None
    sample = samples.get(source)
    if not isinstance(sample, tuple) or len(sample) != 2:
        return None
    return sample


def _normalize(state):
    raw = state if isinstance(state, dict) else {}
    seeded = raw.get("seeded") if isinstance(raw.get("seeded"), dict) else {}
    jira = raw.get("jira") if isinstance(raw.get("jira"), dict) else {}
    return {
        "seeded": {source: bool(seeded.get(source)) for source in SOURCES},
        "github": _id_list(raw.get("github")),
        "jira": {str(key): str(value) for key, value in jira.items() if str(key) and str(value)},
        "mail": _id_list(raw.get("mail")),
        "last_spoken": str(raw.get("last_spoken") or ""),
    }


def _copy(state):
    return {
        "seeded": dict(state["seeded"]),
        "github": list(state["github"]),
        "jira": dict(state["jira"]),
        "mail": list(state["mail"]),
        "last_spoken": state["last_spoken"],
    }


def _id_list(value):
    if not isinstance(value, list):
        return []
    found = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in found:
            found.append(text)
    return found[-SEEN_LIMIT:]


def _clean(source, items):
    cleaned = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if source == "jira":
            key = str(item.get("key") or "").strip()
            status = " ".join(str(item.get("status") or "").split())
            summary = _clip(item.get("summary") or "", 80)
            if key and status:
                cleaned.append({"key": key, "status": status, "summary": summary})
            continue
        ident = str(item.get("id") or "").strip()
        if not ident:
            continue
        if source == "github":
            cleaned.append({"id": ident, "label": _clip(item.get("label") or ident, 120)})
        else:
            cleaned.append(
                {
                    "id": ident,
                    "sender": _clip(item.get("sender") or "remetente", 60),
                    "subject": _clip(item.get("subject") or "sem assunto", 80),
                }
            )
    return cleaned


def _baseline(source, items):
    if source == "jira":
        return {item["key"]: item["status"] for item in items}
    return [item["id"] for item in items][-SEEN_LIMIT:]


def _changes(source, state, items):
    if source == "jira":
        known = state["jira"]
        found = []
        for item in items:
            previous = known.get(item["key"])
            if previous is not None and previous != item["status"]:
                found.append(
                    {
                        "kind": "jira",
                        "key": item["key"],
                        "status": item["status"],
                        "summary": item["summary"],
                    }
                )
        return found
    known = set(state[source])
    found = []
    for item in items:
        if item["id"] in known:
            continue
        if source == "github":
            found.append({"kind": "github", "id": item["id"], "label": item["label"]})
        else:
            found.append(
                {
                    "kind": "mail",
                    "id": item["id"],
                    "sender": item["sender"],
                    "subject": item["subject"],
                }
            )
    return found


def _absorb(state, samples):
    for source in SOURCES:
        sample = _sample(samples, source)
        if sample is None or sample[0] != "ok" or not state["seeded"].get(source):
            continue
        items = _clean(source, sample[1])
        if source == "jira":
            current = dict(state["jira"])
            for item in items:
                current[item["key"]] = item["status"]
            if len(current) > SEEN_LIMIT:
                keep = {item["key"] for item in items}
                current = {key: value for key, value in current.items() if key in keep}
            state["jira"] = current
            continue
        merged = list(state[source])
        have = set(merged)
        for item in items:
            if item["id"] not in have:
                merged.append(item["id"])
                have.add(item["id"])
        state[source] = merged[-SEEN_LIMIT:]


def _split_muted(events, control):
    always = set(control.get("always") or [])
    today = set(control.get("today") or [])
    speak = []
    hold = []
    for event in events:
        ident = _event_id(event)
        if ident and ident in always:
            continue
        if ident and ident in today:
            hold.append(event)
            continue
        speak.append(event)
    return speak, hold


def _restore_held(previous, working, held):
    for event in held:
        kind = event.get("kind")
        if kind == "jira":
            key = event.get("key")
            if key in previous["jira"]:
                working["jira"][key] = previous["jira"][key]
            else:
                working["jira"].pop(key, None)
            continue
        if kind not in {"github", "mail"}:
            continue
        ident = event.get("id")
        if ident not in previous[kind]:
            working[kind] = [item for item in working[kind] if item != ident]


def _event_id(event):
    from .alerts import event_identity

    return event_identity(event)


def _speech(events, cap):
    shown = events[:cap]
    extra = len(events) - len(shown)
    parts = [_line(event) for event in shown]
    if parts:
        parts[0] = parts[0][0].lower() + parts[0][1:]
    text = "Senhor, " + " ".join(parts)
    if extra:
        text += f" E mais {extra}."
    return text


def _line(event):
    kind = event.get("kind")
    if kind == "github":
        return f"Há um review pedido no seu PR {event.get('label')}."
    if kind == "jira":
        base = f"A issue {event.get('key')} mudou para {event.get('status')}"
        summary = event.get("summary") or ""
        if summary:
            return base + f": {summary}."
        return base + "."
    return (
        "E-mail importante não lido, de "
        + str(event.get("sender") or "remetente")
        + ": "
        + str(event.get("subject") or "sem assunto")
        + "."
    )


def _clip(text, limit):
    cleaned = " ".join(
        str(text or "").replace("\u2014", " ").replace("\u2013", " ").split()
    )
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
