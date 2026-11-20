"""Ícone da bandeja do sistema. O pystray é opcional.

Pausar, retomar e sair são a parte testável. A janela só abre
se pystray e Pillow estiverem instalados e JARVIS_BANDEJA não for off.
"""

import threading

_ESTADO = None
_LOCK = threading.Lock()
_ICONE = None
_ULTIMO = None


class Escuta:
    def __init__(self):
        self._paused = threading.Event()
        self._quit = threading.Event()

    def pausada(self):
        return self._paused.is_set()

    def pausar(self):
        self._paused.set()

    def retomar(self):
        self._paused.clear()

    def alternar(self):
        if self.pausada():
            self.retomar()
            return "ouvindo"
        self.pausar()
        return "pausado"

    def encerrada(self):
        return self._quit.is_set()

    def pedir_saida(self, interromper=False):
        self._quit.set()
        if interromper:
            import _thread

            _thread.interrupt_main()

    def esperar(self, segundos):
        return self._quit.wait(segundos)

    def rotulo(self):
        if self.pausada():
            return "Retomar escuta"
        return "Pausar escuta"


def estado():
    global _ESTADO
    with _LOCK:
        if _ESTADO is None:
            _ESTADO = Escuta()
        return _ESTADO


def reiniciar_escuta():
    global _ESTADO
    with _LOCK:
        _ESTADO = Escuta()
        return _ESTADO


def itens_menu(escuta):
    return [
        (escuta.rotulo(), "alternar"),
        ("Sair", "encerrar"),
    ]


def aplicar(escuta, acao):
    if acao == "alternar":
        return escuta.alternar()
    if acao == "encerrar":
        escuta.pedir_saida(False)
        return "saindo"
    return ""


def definir_icone(icon):
    global _ICONE
    _ICONE = icon


def avisar(titulo, corpo):
    """Aviso da bandeja. Sem ícone, só guarda o texto para o teste."""
    global _ULTIMO
    aviso = {
        "titulo": " ".join(str(titulo or "").split())[:80],
        "corpo": " ".join(str(corpo or "").split())[:180],
    }
    _ULTIMO = aviso
    notificar = getattr(_ICONE, "notify", None)
    if notificar is not None:
        try:
            notificar(aviso["corpo"], aviso["titulo"])
        except Exception:
            pass
    return aviso


def ultimo_aviso():
    return _ULTIMO


def pystray_disponivel():
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def anexar(escuta=None):
    from . import config

    if not config.bandeja_ligada():
        return None
    if not pystray_disponivel():
        return None
    alvo = escuta or estado()
    try:
        return _subir(alvo)
    except Exception:
        return None


def _subir(escuta):
    import pystray
    from PIL import Image

    image = Image.new("RGB", (64, 64), (8, 28, 48))

    def pausar(_icon, _item):
        aplicar(escuta, "alternar")

    def sair(icon, _item):
        escuta.pedir_saida(True)
        try:
            icon.stop()
        except Exception:
            pass

    menu = pystray.Menu(
        pystray.MenuItem(lambda _item: escuta.rotulo(), pausar),
        pystray.MenuItem("Sair", sair),
    )
    icon = pystray.Icon("jarvis", image, "Jarvis", menu)
    definir_icone(icon)
    thread = threading.Thread(target=icon.run, name="jarvis-bandeja", daemon=True)
    thread.start()
    return icon
