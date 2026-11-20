import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import config

LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]*\)")
BULLET_PATTERN = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
MARKDOWN_CHARS = re.compile(r"[*_`#>|~]")

IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
_STOP = threading.local()


def bind_stop(stop_event):
    _STOP.event = stop_event


def _stopped():
    event = getattr(_STOP, "event", None)
    return event is not None and event.is_set()


def _wait_proc(proc):
    from .procutil import esquecer, matar

    try:
        while proc.poll() is None:
            if _stopped():
                matar(proc)
                return "stop"
            time.sleep(0.05)
    except KeyboardInterrupt:
        matar(proc)
        raise
    finally:
        if proc.poll() is not None:
            esquecer(proc)
    return proc.returncode == 0


def clean(text):
    text = LINK_PATTERN.sub(r"\1", text)
    text = BULLET_PATTERN.sub("", text)
    text = MARKDOWN_CHARS.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _say(text):
    if not IS_MACOS or not shutil.which("say"):
        return False
    from .procutil import popen_vigiado

    proc = popen_vigiado(
        ["say", "-v", config.VOICE, "-r", str(config.SPEECH_RATE)],
        stdin=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        proc.stdin.write(text)
        proc.stdin.close()
    except Exception:
        proc.kill()
        return False
    return _wait_proc(proc)


def _edge_tts(text):
    try:
        import asyncio

        import edge_tts
    except ImportError:
        return False

    path = Path(tempfile.gettempdir()) / "jarvis_tts.mp3"

    async def synth():
        communicate = edge_tts.Communicate(
            text, config.EDGE_VOICE, rate=config.EDGE_RATE
        )
        await communicate.save(str(path))

    try:
        asyncio.run(asyncio.wait_for(synth(), timeout=config.EDGE_TIMEOUT))
    except Exception:
        return False
    if _stopped():
        path.unlink(missing_ok=True)
        return "stop"

    try:
        return _play(path)
    finally:
        path.unlink(missing_ok=True)


def _play(path):
    try:
        import sounddevice as sd
        import soundfile as sf

        data, samplerate = sf.read(str(path), dtype="float32")
        sd.play(data, samplerate)
        frames = len(data)
        duration = frames / float(samplerate) if samplerate else 0
        elapsed = 0.0
        while elapsed < duration + 0.15:
            if _stopped():
                sd.stop()
                return "stop"
            time.sleep(0.05)
            elapsed += 0.05
        sd.stop()
        return True
    except KeyboardInterrupt:
        try:
            sd.stop()
        except Exception:
            pass
        raise
    except Exception:
        pass

    if IS_WINDOWS:
        safe_path = str(path).replace("'", "''")
        script = (
            "Add-Type -AssemblyName presentationCore; "
            "$p = New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([uri]'{safe_path}'); $p.Play(); "
            "$tries = 0; "
            "while (-not $p.NaturalDuration.HasTimeSpan) "
            "{ if ($tries -ge 100) { exit 1 }; "
            "Start-Sleep -Milliseconds 100; $tries++ }; "
            "Start-Sleep -Milliseconds "
            "([int]$p.NaturalDuration.TimeSpan.TotalMilliseconds + 200)"
        )
        from .procutil import popen_vigiado

        proc = popen_vigiado(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _wait_proc(proc)

    for player in ("afplay", "ffplay", "mpg123"):
        binary = shutil.which(player)
        if binary:
            args = [binary, str(path)]
            if player == "ffplay":
                args = [binary, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
            from .procutil import popen_vigiado

            proc = popen_vigiado(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result = _wait_proc(proc)
            if result:
                return result
    return False


def _sapi(text):
    if not IS_WINDOWS:
        return False
    rate = max(-10, min(10, config.SAPI_RATE))
    script = (
        "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$v = $s.GetInstalledVoices() | "
        "Where-Object { $_.VoiceInfo.Culture.Name -like 'pt*' } | "
        "Select-Object -First 1; "
        "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
        f"$s.Rate = {rate}; "
        "$s.Speak([Console]::In.ReadToEnd())"
    )
    from .procutil import popen_vigiado

    proc = popen_vigiado(
        ["powershell", "-NoProfile", "-Command", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    try:
        proc.stdin.write(text)
        proc.stdin.close()
    except Exception:
        proc.kill()
        return False
    return _wait_proc(proc)


def _backends():
    if config.TTS_BACKEND == "say":
        return [_say]
    if config.TTS_BACKEND == "edge":
        return [_edge_tts]
    if config.TTS_BACKEND == "sapi":
        return [_sapi]
    if IS_MACOS:
        return [_say, _edge_tts]
    if IS_WINDOWS:
        return [_edge_tts, _sapi]
    return [_edge_tts, _say]


def speak(text, stop_event=None):
    text = clean(text)
    if not text:
        return
    previous = getattr(_STOP, "event", None)
    if stop_event is not None:
        bind_stop(stop_event)
    try:
        for backend in _backends():
            try:
                result = backend(text)
            except KeyboardInterrupt:
                return
            except Exception:
                continue
            if result == "stop" or result is True or _stopped():
                return
        print("[voz indisponível: resposta apenas em texto]")
    finally:
        bind_stop(previous)
