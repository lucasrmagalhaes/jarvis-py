"""Um processo só avisa lembrete, recado, check-in e Telegram."""

import os
import platform
import threading

from . import config
from .bridge import InboxService
from .checkins import (
    briefing_due,
    digest_due,
    digest_text,
    due_kind,
    lembrete_nota_due,
    local_now,
    mark_briefing,
    mark_digest,
    mark_lembrete_nota,
    mark_revisao_semanal,
    mark_toque_sequencia,
    revisao_semanal_due,
    toque_sequencia_due,
    mark_sent,
    render,
    settings_from_env,
)
from .log import LOG
from .offers import store_offer
from .radar import RadarService
from .reminders import ReminderService
from .state import load
from .telegram import TelegramRefused, TelegramService, build_bot


class NullBus:
    def transcript(self, role, text):
        return None

    def state(self, value):
        return None

    def publish(self, event):
        return None

    def has_message(self):
        return False


class Companion:
    def __init__(self, brain, speak=None, bus=None, lock=None, clock=None):
        self.brain = brain
        self.speak = speak
        self.bus = bus or NullBus()
        self.lock = lock or threading.RLock()
        self.clock = clock
        self.bot = None
        self.telegram = None
        self.reminders = None
        self.inbox = None
        self.radar = None
        self._held = False
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._registrar_sessao()

    def start(self):
        if not self._acquire():
            print("Avisos, check-ins e o Telegram ficam com o outro processo do Jarvis.")
            return False
        self._start_alerts()
        self._start_radar()
        self._start_telegram()
        self._thread = threading.Thread(target=self._loop, name="jarvis-checkins", daemon=True)
        self._thread.start()
        return True

    def allow_checkins(self):
        if not self._held:
            return
        self._ready.set()
        self.tick()

    def stop(self):
        self._stop.set()
        self._ready.set()
        if self.telegram is not None:
            self.telegram.stop()
        if self.reminders is not None:
            self.reminders.stop()
        if self.inbox is not None:
            self.inbox.stop()
        if self.radar is not None:
            self.radar.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._release()

    def tick(self, now=None):
        if not self._held:
            return None
        try:
            with self.lock:
                return self._tick(now)
        except Exception as error:
            LOG.error("check-in: %s", error)
            return None

    def deliver(self, text):
        if not text:
            return
        print(f"\nJARVIS: {text}")
        self.bus.transcript("reply", text)
        self.bus.state("speaking")
        try:
            if self.speak is not None:
                try:
                    self.speak(text)
                except Exception as error:
                    LOG.error("fala do check-in: %s", error)
            if self.bot is not None:
                try:
                    self.bot.send_text(text)
                except Exception as error:
                    LOG.error("telegram do check-in: %s", error)
        finally:
            self.bus.state("standby")

    def _tick(self, now):
        root = self.brain.vault.path if self.brain.vault else None
        moment = now or local_now(root, self.clock)
        self._sessao(moment)
        if self._adiar_sessao(moment):
            return None
        digest = self._maybe_digest(root, moment)
        lembranca = self._maybe_lembrete_nota(root, moment)
        ritual = self._maybe_revisao_semanal(root, moment)
        toque = self._maybe_toque_sequencia(root, moment)
        options = settings_from_env()
        kind = None
        if options["enabled"]:
            kind = due_kind(
                moment,
                load(),
                options["morning_on"],
                options["evening_on"],
                options["evening_at"],
            )
        cover = (
            kind == "morning"
            and config.briefing_telegram()
            and briefing_due(moment, load(), config.briefing_at())
        )
        scheduled = None if cover else self._maybe_briefing(root, moment)
        if not options["enabled"]:
            return scheduled or digest or lembranca or ritual or toque
        if not kind:
            return scheduled or digest or lembranca or ritual or toque
        vault = self.brain.vault
        read_only = bool(vault and getattr(vault, "blocked", False))
        try:
            text, pending = render(root, kind, moment, read_only=read_only)
        except Exception as error:
            LOG.error("check-in: %s", error)
            return scheduled or digest or ritual or toque
        mark_sent(kind, moment.date())
        if cover:
            mark_briefing(moment.date())
        if pending and getattr(self.brain, "pending", None) is None:
            self.brain.pending = pending
        if pending:
            store_offer(pending)
        LOG.info("check-in %s", kind)
        self.deliver(text)
        return text

    def _registrar_sessao(self):
        from .sessao import registrar_envio

        def enviar(texto):
            bot = self.bot
            if bot is None or not texto:
                return False
            return bot.send_text(texto)

        registrar_envio(enviar)

    def _sessao(self, moment):
        from .sessao import concluir_vencidas

        try:
            avisos = concluir_vencidas(moment)
        except Exception:
            LOG.info("sessao de estudo nao concluida")
            return
        for item in avisos:
            pending = item.get("pending")
            atual = getattr(self.brain, "pending", None)
            if pending and (not isinstance(atual, dict) or atual.get("kind") in {"sessao", ""}):
                try:
                    self.brain._definir_pending(pending)
                except Exception:
                    self.brain.pending = pending
            voz = item.get("voz") or ""
            if voz:
                self._falar_sessao(voz)

    def _falar_sessao(self, text):
        print(f"\nJARVIS: {text}")
        self.bus.transcript("reply", text)
        self.bus.state("speaking")
        try:
            if self.speak is not None:
                try:
                    self.speak(text)
                except Exception:
                    LOG.info("fala da sessao falhou")
        finally:
            self.bus.state("standby")

    def _adiar_sessao(self, moment):
        from .sessao import adiar_proativo

        try:
            return adiar_proativo(moment)
        except Exception:
            return False

    def _maybe_briefing(self, root, moment):
        if not config.briefing_telegram() or self.bot is None:
            return None
        if not briefing_due(moment, load(), config.briefing_at()):
            return None
        try:
            if root is None:
                text = "O vault não está configurado, senhor."
            else:
                from .routines import briefing_speech, load_places

                text = briefing_speech(root, load_places(root), moment)
        except Exception:
            LOG.error("briefing agendado falhou")
            return None
        if not text:
            return None
        try:
            enviado = self.bot.send_text(text)
        except Exception:
            LOG.error("briefing agendado no telegram falhou")
            return None
        if enviado is False:
            return None
        mark_briefing(moment.date())
        LOG.info("briefing agendado enviado no telegram")
        return text

    def _maybe_digest(self, root, moment):
        if not config.digest_enabled():
            return None
        if root is None or self.bot is None:
            return None
        if not digest_due(moment, load(), config.digest_at()):
            return None
        text = digest_text(root, moment)
        if not text:
            return None
        try:
            enviado = self.bot.send_text(text)
        except Exception:
            LOG.error("resumo semanal no telegram falhou")
            return None
        if enviado is False:
            return None
        mark_digest(moment.date())
        LOG.info("resumo semanal enviado no telegram")
        return text

    def _maybe_lembrete_nota(self, root, moment):
        if not config.lembrete_nota():
            return None
        if root is None or self.bot is None:
            return None
        if not lembrete_nota_due(moment, load(), config.lembrete_nota_at()):
            return None
        from .conhecimento import texto_lembrete_telegram

        try:
            text = texto_lembrete_telegram(root, moment)
        except Exception:
            LOG.error("lembrete de nota falhou")
            return None
        if not text:
            return None
        try:
            enviado = self.bot.send_text(text)
        except Exception:
            LOG.error("lembrete de nota no telegram falhou")
            return None
        if enviado is False:
            return None
        mark_lembrete_nota(moment.date())
        LOG.info("lembrete de nota enviado no telegram")
        return text

    def _maybe_revisao_semanal(self, root, moment):
        if not config.revisao_semanal():
            return None
        if root is None or self.bot is None:
            return None
        if not revisao_semanal_due(moment, load(), config.revisao_semanal_at()):
            return None
        from .reflexao import texto_revisao_semanal

        try:
            text = texto_revisao_semanal()
        except Exception:
            LOG.info("lembrete da revisao semanal falhou")
            return None
        if not text:
            return None
        try:
            enviado = self.bot.send_text(text)
        except Exception:
            LOG.info("lembrete da revisao semanal no telegram falhou")
            return None
        if enviado is False:
            return None
        mark_revisao_semanal(moment.date())
        LOG.info("lembrete da revisao semanal enviado")
        return text

    def _maybe_toque_sequencia(self, root, moment):
        if not config.toque_sequencia() or self.bot is None or root is None:
            return None
        if not toque_sequencia_due(moment, load(), config.toque_sequencia_at()):
            return None
        from .andamento import texto_toque

        try:
            text = texto_toque(root, moment)
        except Exception:
            LOG.info("toque de sequencia falhou")
            return None
        if text == "":
            return None
        if text is None:
            mark_toque_sequencia(moment.date())
            return None
        try:
            enviado = self.bot.send_text(text)
        except Exception:
            LOG.info("toque de sequencia no telegram falhou")
            return None
        if enviado is False:
            return None
        mark_toque_sequencia(moment.date())
        LOG.info("toque de sequencia enviado")
        return text

    def _loop(self):
        while not self._stop.wait(config.reminder_interval()):
            if not self._ready.is_set():
                continue
            try:
                self.tick()
            except Exception as error:
                LOG.error("check-in: %s", error)

    def _start_alerts(self):
        if not self.brain.vault:
            return
        self.reminders = ReminderService(
            self.brain.vault,
            speak=self.speak,
            bus=self.bus,
            lock=self.lock,
            interval=config.reminder_interval(),
            on_status=self.brain.on_status,
            also=self._relay,
        )
        self.inbox = InboxService(
            self.brain.vault,
            speak=self.speak,
            bus=self.bus,
            lock=self.lock,
            interval=config.reminder_interval(),
            on_status=self.brain.on_status,
            also=self._relay,
        )
        self.reminders.start()
        self.inbox.start()

    def _start_radar(self):
        if not config.radar_enabled():
            return
        self.radar = RadarService(
            speak=self.speak,
            bus=self.bus,
            lock=self.lock,
            interval=config.radar_interval(),
            also=self._relay,
            clock=self.clock,
            cooldown=config.radar_cooldown(),
        )
        self.radar.start()

    def _drop(self, spec):
        from .capture import drop_pedido, save_drop
        from .log import failure_speech

        vault = self.brain.vault
        if vault is None:
            return (
                "O vault não está configurado, senhor. "
                "Sem ele eu não leio nem gravo as notas. "
                "Rode python -m jarvis.setup."
            )
        prep = vault.prepare()
        print(f"Vault: {prep.detail}")
        if prep.fatal:
            return failure_speech(prep.detail) or "Não gravei a nota, senhor."
        if prep.read_only:
            return "Não gravei a nota, senhor. O vault está bloqueado para escrita agora."
        moment = self.brain._local_now()
        reply = save_drop(vault.path, spec, moment)
        if reply.startswith("Guardei") and vault.sync and not vault.blocked:
            published = vault.publish(drop_pedido(spec))
            self.brain.last_sync = published
            print(f"Vault: {published.detail}")
            if published and published.spoken():
                reply = (reply + " " + published.spoken()).strip()
        elif reply.startswith("Guardei") and prep.spoken():
            reply = (reply + " " + prep.spoken()).strip()
        if reply.startswith("Guardei") and getattr(self.brain, "memory", None) is not None:
            self.brain.memory.remember(drop_pedido(spec), reply)
        return reply

    def _relay(self, text):
        if self.bot is not None:
            self.bot.send_text(text)

    def _start_telegram(self):
        token = config.telegram_token()
        if not token and config.telegram_allowed_user_id() is None:
            return
        if not config.telegram_ready():
            print("Telegram sem usuário ou conversa autorizada. Não vou conectar.")
            return

        def on_text(text):
            with self.lock:
                return _answer(self.brain, text)

        def on_drop(spec):
            with self.lock:
                return self._drop(spec)

        try:
            self.bot = build_bot(on_text, on_drop=on_drop)
        except TelegramRefused as error:
            print(error)
            return
        self.telegram = TelegramService(self.bot)
        self.telegram.start()

    def _acquire(self):
        path = _lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if not _stale(path):
                return False
            try:
                path.unlink()
            except OSError:
                return False
            return self._acquire()
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        self._held = True
        return True

    def _release(self):
        if not self._held:
            return
        path = _lock_path()
        try:
            current = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            self._held = False
            return
        if current == os.getpid():
            try:
                path.unlink()
            except OSError:
                pass
        self._held = False


def _answer(brain, text):
    from .brain import BrainError
    from .log import failure_speech

    try:
        reply = brain.ask(text)
    except BrainError as error:
        LOG.error("consulta: %s", error)
        return failure_speech(error)
    except Exception as error:
        LOG.error("consulta: %s", error)
        return failure_speech(error)
    return reply or "Concluí a tarefa, senhor, mas não há nada a reportar."


def _lock_path():
    return config.jarvis_home() / "companion.lock"


def _stale(path):
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    if pid == os.getpid():
        return False
    return not _process_alive(pid)


def _process_alive(pid):
    if pid <= 0:
        return False
    if platform.system() == "Windows":
        import ctypes

        access = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(access, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def run_background():
    import time

    from .brain import Brain, BrainError
    from .log import setup as setup_log
    from .voice import speak

    setup_log()
    try:
        brain = Brain()
    except BrainError as error:
        print(f"JARVIS: {error}")
        return 1
    companion = Companion(brain, speak=speak, bus=NullBus(), lock=threading.RLock())
    if not companion.start():
        return 0
    companion.allow_checkins()
    print("Jarvis em segundo plano. Ctrl+C encerra.")
    if config.telegram_ready():
        print("Telegram ligado, só para o usuário autorizado.")
    else:
        print("Telegram desligado. Check-ins e lembretes seguem neste processo.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print()
    finally:
        companion.stop()
        from .encerrar import encerrar

        encerrar(brain)
    return 0
