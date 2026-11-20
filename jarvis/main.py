import queue
import sys
import threading

from . import config, panel, voice
from .barge import stdin_keys_if_tty
from .barge import watch as watch_barge
from .brain import Brain, BrainError
from .ears import Ears, EarsError
from .log import LOG, failure_speech, setup as setup_log
from .companion import Companion
from .routines import classify
from .deps import wakeword_hint
from .wakeword import WakeWord

BANNER = r"""
     _   _    ______     _____ ____
    | | / \  |  _ \ \   / /_ _/ ___|
 _  | |/ _ \ | |_) \ \ / / | |\___ \
| |_| / ___ \|  _ < \ V /  | | ___) |
 \___/_/   \_\_| \_\ \_/  |___|____/
"""

TEXT_PROMPT = "\n⏎ para falar | digite e ⏎ para enviar | /sair para encerrar\n> "

turn_lock = threading.RLock()


class _Audio:
    ears = None
    wake = None


audio = _Audio()


def listen_window(continuing):
    if continuing:
        return config.FOLLOWUP_NO_SPEECH_SECONDS
    return None


def ends_conversation(message):
    return classify(message).kind == "dismiss"


class _StopBridge:
    def __init__(self, stop, listen):
        self._stop = stop
        self._listen = listen

    def is_set(self):
        return self._stop.is_set()

    def set(self):
        self._listen.set()
        self._stop.set()


def speak_out(text, watch=True, frames=None, keys=None, player=None):
    stop = threading.Event()
    listen = threading.Event()
    bridge = _StopBridge(stop, listen)
    watcher = None
    ears = audio.ears
    wake = audio.wake
    can_watch = watch and (
        frames is not None
        or (wake is not None and getattr(wake, "model", None) is not None)
        or (ears is not None and getattr(ears, "model", None) is not None)
    )
    if keys is None and watch:
        keys = stdin_keys_if_tty()
    if can_watch or (watch and keys is not None):
        watcher = threading.Thread(
            target=watch_barge,
            args=(bridge, wake if watch else None, ears if watch else None),
            kwargs={"frames": frames, "keys": keys},
            daemon=True,
        )
        watcher.start()
    speaker = player or voice.speak
    try:
        speaker(text, stop_event=stop)
    finally:
        stop.set()
        if watcher is not None:
            watcher.join(timeout=2)
        model = getattr(wake, "model", None) if wake is not None else None
        if model is not None and frames is None:
            try:
                model.reset()
            except Exception:
                LOG.error("nao foi possivel reiniciar o wake word")
    if listen.is_set():
        return "listen"
    return "done"


def respond(brain, message, bus):
    with turn_lock:
        spoken = {"n": 0, "listen": False}
        try:
            print("Processando...")
            LOG.info("pedido: %s", " ".join((message or "").split())[:300])
            bus.state("processing")

            def on_sentence(sentence):
                if spoken["listen"]:
                    return False
                bus.state("speaking")
                print(sentence, flush=True)
                result = speak_out(sentence)
                spoken["n"] += 1
                if result == "listen":
                    spoken["listen"] = True
                    return False
                return True

            try:
                reply = brain.ask(message, on_sentence=on_sentence)
            except BrainError as error:
                from .privacidade import resumo_erro

                LOG.error("consulta: %s", resumo_erro(error))
                notice = ""
                sync = getattr(brain, "last_sync", None)
                if sync and sync.spoken():
                    notice = " " + sync.spoken()
                speech = failure_speech(error) + notice
                print(f"\nJARVIS [erro]: {resumo_erro(error)}")
                bus.transcript("error", speech)
                bus.state("speaking")
                if getattr(brain, "memory", None) is not None:
                    brain.memory.remember(message, speech)
                speak_out(speech, watch=False)
                return "done"
            if spoken["listen"]:
                bus.state("listening")
                return "listen"
            if not reply:
                reply = "Concluí a tarefa, senhor, mas não há nada a reportar."
            bus.transcript("reply", reply)
            if spoken["n"] == 0:
                print(f"\nJARVIS: {reply}")
                bus.state("speaking")
                result = speak_out(reply)
                if result == "listen":
                    bus.state("listening")
                    return "listen"
            else:
                print()
            return "done"
        finally:
            if not spoken["listen"]:
                bus.state("standby")


def handle_panel_message(brain, bus, message):
    print(f"\nVocê (painel): {message}")
    bus.transcript("user", message)
    try:
        respond(brain, message, bus)
    except Exception as error:
        from .privacidade import resumo_erro

        aviso = resumo_erro(error)
        print(f"Falha ao responder o painel: {aviso}")
        bus.transcript("error", aviso)
        bus.state("standby")


def drain_panel(brain, bus):
    while True:
        message = bus.take_message()
        if message is None:
            return
        handle_panel_message(brain, bus, message)


def panel_worker(brain, bus, stop):
    while not stop.is_set():
        try:
            message = bus.inbox.get(timeout=0.4)
        except queue.Empty:
            continue
        except Exception:
            continue
        handle_panel_message(brain, bus, message)


def converse(brain, ears, bus):
    continuing = False
    while True:
        bus.state("listening")
        try:
            message = ears.listen(no_speech_seconds=listen_window(continuing))
        except EarsError as error:
            LOG.error("microfone: %s", error)
            speech = failure_speech(error)
            print(f"Problema no microfone: {error}.")
            bus.transcript("error", speech)
            bus.state("speaking")
            speak_out(speech, watch=False)
            bus.state("standby")
            return
        if not message:
            bus.state("standby")
            return
        print(f"Você: {message}")
        bus.transcript("user", message)
        outcome = respond(brain, message, bus)
        if ends_conversation(message):
            print("Conversa encerrada. Volto ao standby.")
            return
        continuing = True
        if outcome == "listen":
            print("Pode falar, senhor.")
        print(
            "Pode continuar sem repetir Hey Jarvis. "
            "Diga valeu, Jarvis para encerrar."
        )


def _escuta_permite(bus):
    from .bandeja import estado

    escuta = estado()
    if escuta.encerrada():
        return "sair"
    if escuta.pausada():
        bus.state("standby")
        if escuta.esperar(0.4):
            return "sair"
        return "pausado"
    return "seguir"


def run_handsfree(brain, ears, wake, bus, companion=None):
    greeting = "Sistemas online. Diga: Hey Jarvis, quando precisar de mim, senhor."
    print(f"\nJARVIS: {greeting}")
    bus.transcript("reply", greeting)
    speak_out(greeting)
    if companion is not None:
        companion.allow_checkins()
    while True:
        passo = _escuta_permite(bus)
        if passo == "sair":
            return
        if passo == "pausado":
            continue
        bus.state("standby")
        print('\nStandby. Diga "Hey Jarvis" para me chamar. Ctrl+C encerra.')
        try:
            woke = wake.wait(stop_when=bus.has_message)
        except KeyboardInterrupt:
            print()
            return
        except EarsError as error:
            LOG.error("microfone: %s", error)
            speech = failure_speech(error)
            print(f"Problema no microfone: {error}.")
            bus.transcript("error", speech)
            speak_out(speech, watch=False)
            return
        try:
            if not woke:
                drain_panel(brain, bus)
                continue
            print("Chamado detectado.")
            bus.state("speaking")
            speak_out("Sim, senhor?")
            converse(brain, ears, bus)
        except KeyboardInterrupt:
            print("\nConversa interrompida.")
            bus.state("standby")
        except Exception as error:
            from .privacidade import resumo_erro

            aviso = resumo_erro(error)
            print(f"Falha inesperada: {aviso}")
            bus.transcript("error", aviso)
            bus.state("standby")


def capture_voice(ears, bus):
    with turn_lock:
        print("Ouvindo... fale e faça uma pausa para encerrar.")
        bus.state("listening")
        try:
            return ears.listen()
        finally:
            bus.state("standby")


def run_text(brain, ears, voice_ready, bus, companion=None):
    greeting = "Sistemas online. Às suas ordens, senhor."
    print(f"\nJARVIS: {greeting}")
    bus.transcript("reply", greeting)
    speak_out(greeting)
    if companion is not None:
        companion.allow_checkins()

    stop = threading.Event()
    worker = threading.Thread(
        target=panel_worker, args=(brain, bus, stop), daemon=True
    )
    worker.start()

    try:
        while True:
            passo = _escuta_permite(bus)
            if passo == "sair":
                return
            if passo == "pausado":
                continue
            bus.state("standby")
            try:
                typed = input(TEXT_PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if typed.lower() in {"/sair", "/exit", "/quit"}:
                return
            if typed:
                message = typed
            elif not voice_ready:
                print("O modo de voz está indisponível; digite a mensagem.")
                continue
            else:
                try:
                    message = capture_voice(ears, bus)
                except KeyboardInterrupt:
                    print("Captura cancelada.")
                    continue
                except EarsError as error:
                    LOG.error("microfone: %s", error)
                    speech = failure_speech(error)
                    print(f"Problema no microfone: {error}.")
                    bus.transcript("error", speech)
                    speak_out(speech, watch=False)
                    continue
                except Exception as error:
                    print(f"Falha inesperada na captura de voz: {error}")
                    continue
                if not message:
                    print("Não captei nada, senhor.")
                    continue
                print(f"Você: {message}")
            bus.transcript("user", message)
            try:
                respond(brain, message, bus)
            except KeyboardInterrupt:
                print("Consulta cancelada.")
                continue
    finally:
        stop.set()
        worker.join(timeout=5)


def _warm_search_index(brain):
    vault = getattr(brain, "vault", None)
    root = getattr(vault, "path", None) if vault is not None else None
    if root is None:
        return
    try:
        from .indice_vetor import warm_index

        report = warm_index(root)
    except Exception:
        LOG.error("indice de busca indisponivel")
        return
    if not report:
        return
    print(
        "Índice de busca: {refeitas} notas novas de {total}, em {segundos:.2f}s.".format(
            **report
        )
    )


def run():
    from .primeiro_uso import preparar_se_preciso

    if not preparar_se_preciso():
        return
    text_mode = bool({"--texto", "-t"} & set(sys.argv[1:]))
    setup_log()
    print(BANNER)
    try:
        brain = Brain()
    except BrainError as error:
        print(f"JARVIS: {error}")
        return
    companion = None
    from .encerrar import encerrar, instalar

    instalar()
    try:
        ears = Ears()
        bus = panel.PanelBus()

        if config.PANEL_ENABLED:
            try:
                _, url = panel.start(bus)
                print(f"Painel: {url}")
            except OSError as error:
                print(f"Painel indisponível: {error}")

        print("Inicializando os modelos de voz, um momento...")
        voice_ready = True
        try:
            ears.load()
        except Exception as error:
            voice_ready = False
            print(failure_speech(error))
            LOG.error("modelos: %s", error)

        wake = None
        audio.ears = ears if voice_ready else None
        if not text_mode and voice_ready:
            wake = WakeWord()
            try:
                wake.load()
            except Exception as error:
                wake = None
                print(f"Falha ao carregar a palavra de ativação: {error}")
                print(wakeword_hint())
        audio.wake = wake
        _warm_search_index(brain)

        def push_status(payload):
            bus.publish(payload)

        brain.on_status = push_status
        brain.on_wait = lambda text: speak_out(text, watch=False)
        if brain.vault:
            push_status(brain.vault.hud_payload())
        companion = Companion(
            brain,
            speak=voice.speak,
            bus=bus,
            lock=turn_lock,
        )
        companion.start()
        from .bandeja import anexar

        anexar()

        try:
            if wake:
                run_handsfree(brain, ears, wake, bus, companion)
            else:
                if not text_mode:
                    print("Seguindo no modo texto.")
                run_text(brain, ears, voice_ready, bus, companion)
        finally:
            companion.stop()

        try:
            with turn_lock:
                farewell = "Encerrando os sistemas. Até logo, senhor."
                print(f"JARVIS: {farewell}")
                bus.transcript("reply", farewell)
                bus.state("standby")
                speak_out(farewell, watch=False)
        except KeyboardInterrupt:
            print()
    finally:
        encerrar(brain)


if __name__ == "__main__":
    run()
