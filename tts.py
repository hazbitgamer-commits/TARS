"""Text-to-speech: edge-tts (free MS neural voice, needs internet),
falling back to Windows' built-in SAPI voice when offline."""
import asyncio
import io
import json
from pathlib import Path

import soundfile as sf
import sounddevice as sd

VOICE = "en-GB-RyanNeural"  # dry British male
RATE = "+8%"
SMOOTH = False  # True: strip pause-punctuation so speech flows with fewer stops

# Jacob can change VOICE/RATE live via the voice_settings skill; whatever it
# last saved here is re-applied on startup.
_SETTINGS_FILE = Path(__file__).parent / "voice_settings.json"


def _load_saved() -> None:
    global VOICE, RATE, SMOOTH
    try:
        data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        VOICE = data.get("voice", VOICE)
        RATE = data.get("rate", RATE)
        SMOOTH = bool(data.get("smooth", SMOOTH))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


_load_saved()


def _prep(text: str) -> str:
    """Smooth mode: remove the punctuation that makes the voice pause."""
    if not SMOOTH:
        return text
    t = text.replace(" — ", " ").replace("—", " ").replace(";", "")
    t = t.replace(",", "")
    return " ".join(t.split())


# ---------- Kokoro: the local, more human voice (primary engine) ----------
_kokoro = None


def _kokoro_engine():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        base = Path(__file__).parent
        _kokoro = Kokoro(str(base / "models" / "kokoro-v1.0.onnx"),
                         str(base / "models" / "voices-v1.0.bin"))
    return _kokoro


def _rate_to_speed() -> float:
    try:
        pct = int(RATE.replace("%", "").replace("+", ""))
        if RATE.strip().startswith("-"):
            pct = -pct
    except ValueError:
        pct = 8
    return max(0.6, min(1.6, 1.0 + pct / 100))


def _synth(text: str):
    """(audio, samplerate) from the best engine available, else None.

    Kokoro voices are named like bm_george; edge-tts ones like en-GB-RyanNeural.
    """
    text = _prep(text)
    if "_" in VOICE and "-" not in VOICE:
        try:
            return _kokoro_engine().create(text, voice=VOICE, speed=_rate_to_speed())
        except Exception:
            pass
    try:
        mp3 = asyncio.run(_fetch_mp3(text))
        return sf.read(io.BytesIO(mp3), dtype="float32")
    except Exception:
        return None


async def _fetch_mp3(text: str) -> bytes:
    import edge_tts

    buf = io.BytesIO()
    async for chunk in edge_tts.Communicate(_prep(text), VOICE, rate=RATE).stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


# real words only — Kokoro mangles non-words like "Mm."/"Hmm." into noise
ACKS = ("Right.", "On it.", "Okay.")


class Speaker:
    def __init__(self):
        self._ack_cache: dict[str, tuple] = {}
        import threading

        threading.Thread(target=self._preload_acks, daemon=True).start()

    def _preload_acks(self):
        for phrase in ACKS:
            try:
                res = _synth(phrase)
                if res is not None:
                    audio, sr = res
                    self._ack_cache[phrase] = (audio * 0.75, sr)  # slightly soft
            except Exception:
                pass

    def ack(self) -> None:
        """A short instant 'I heard you' — fills the thinking silence."""
        import random

        if not self._ack_cache:
            return
        audio, sr = random.choice(list(self._ack_cache.values()))
        try:
            sd.play(audio, sr)
            sd.wait()
        except Exception:
            pass

    def say_stream(self, sentences) -> str:
        """Speak sentences as they arrive; fetch the next while one plays."""
        import queue
        import threading

        q: queue.Queue = queue.Queue(maxsize=3)
        DONE = object()

        def producer():
            for s in sentences:
                if not s:
                    continue
                res = _synth(s)
                if res is not None:
                    q.put((s, res[0], res[1]))
                else:
                    q.put((s, None, None))  # fall back to offline voice
            q.put(DONE)

        threading.Thread(target=producer, daemon=True).start()
        spoken = []
        while True:
            item = q.get()
            if item is DONE:
                break
            s, audio, sr = item
            spoken.append(s)
            if audio is not None:
                sd.play(audio, sr)
                sd.wait()
            else:
                self._say_offline(s)
        return " ".join(spoken)

    def say(self, text: str) -> None:
        if not text:
            return
        res = _synth(text)
        if res is not None:
            sd.play(res[0], res[1])
            sd.wait()
        else:
            self._say_offline(text)

    def _say_offline(self, text: str) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        for v in engine.getProperty("voices"):
            if "george" in v.name.lower() or "hazel" in v.name.lower():
                engine.setProperty("voice", v.id)
                break
        engine.say(text)
        engine.runAndWait()
