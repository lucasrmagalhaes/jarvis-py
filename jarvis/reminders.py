"""Avisa lembretes gravados no vault enquanto o Jarvis está aberto."""

import threading
from datetime import datetime, timezone

from .routines import alert_speech, list_due, mark_reminded


class ReminderService:
    def __init__(self, vault, speak, bus, lock, interval=15, on_status=None, also=None):
        self.vault = vault
        self.speak = speak
        self.bus = bus
        self.lock = lock
        self.interval = interval
        self.on_status = on_status
        self.also = also
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="jarvis-lembretes", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def tick(self, now=None):
        with self.lock:
            self._tick(now)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as error:
                print(f"Lembrete: {error}")

    def _tick(self, now):
        moment = now or datetime.now(timezone.utc)
        from .alerts import is_paused, muted_ids, remember_last, reminder_identity
        from .sessao import adiar_proativo, concluir_vencidas

        try:
            avisos = concluir_vencidas(moment)
        except Exception:
            avisos = []
        for item in avisos:
            voz = item.get("voz") or ""
            if voz:
                self._anunciar(voz)
        if adiar_proativo(moment):
            if self.on_status:
                self.on_status(self.vault.hud_payload())
            return
        if is_paused(moment):
            if self.on_status:
                self.on_status(self.vault.hud_payload())
            return
        due = list_due(self.vault.path, moment)
        if due:
            muted = muted_ids(moment)
            audible = []
            for item in due:
                ident = reminder_identity(item.text)
                if ident and ident in muted:
                    continue
                audible.append(item)
            self.vault.resync_snapshot()
            marked = mark_reminded(due, moment, self.vault.path)
            if marked and self.vault.sync and not self.vault.blocked:
                self.vault.publish("lembrete avisado")
            spoken = [item for item in marked if item in audible]
            if spoken:
                text = alert_speech(spoken)
                print(f"\nJARVIS: {text}")
                self.bus.transcript("reply", text)
                self.bus.state("speaking")
                try:
                    if self.speak is not None:
                        self.speak(text)
                    self._also(text)
                finally:
                    self.bus.state("standby")
                idents = [reminder_identity(item.text) for item in spoken]
                try:
                    remember_last([ident for ident in idents if ident])
                except Exception:
                    print("Aviso: não guardei o silêncio do lembrete")
        if self.on_status:
            self.on_status(self.vault.hud_payload())

    def _anunciar(self, text):
        print(f"\nJARVIS: {text}")
        self.bus.transcript("reply", text)
        self.bus.state("speaking")
        try:
            if self.speak is not None:
                self.speak(text)
        finally:
            self.bus.state("standby")

    def _also(self, text):
        if self.also is None:
            return
        try:
            self.also(text)
        except Exception as error:
            print(f"Aviso extra: {error}")
