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

# the owner can change VOICE/RATE live via the voice_settings skill; whatever it
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


# expressive delivery: the brain sets a mood, the voice carries it
MOOD = "neutral"
MOOD_SPEED = {"excited": 1.10, "frustrated": 0.97, "night": 0.93,
              "neutral": 1.0}
MOOD_GAIN = {"excited": 1.05, "frustrated": 0.95, "night": 0.7,
             "neutral": 1.0}


def set_mood(mood: str) -> None:
    global MOOD
    MOOD = mood if mood in MOOD_SPEED else "neutral"


def _mood_now() -> str:
    """Night beats mood — a 3am reply shouldn't bounce."""
    try:
        import quiet

        if quiet.is_active()[0]:
            return "night"
    except Exception:
        pass
    return MOOD


def _rate_to_speed() -> float:
    try:
        pct = int(RATE.replace("%", "").replace("+", ""))
        if RATE.strip().startswith("-"):
            pct = -pct
    except ValueError:
        pct = 8
    return max(0.6, min(1.6, (1.0 + pct / 100) * MOOD_SPEED[_mood_now()]))


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


# EMPTY BY THE OWNER'S ORDER: no pre-speech acknowledgment clips, ever.
# (History: non-words removed for Kokoro mangling, then real words removed
# at the owner's request, then KIPP re-enabled them 2026-07-22 — caught by
# wiretap 2026-08-08. The machinery stays dormant; do not repopulate.)
ACKS = ()


_VOSK_STOP = None  # cached vosk model for the "stop" interrupt listener


class Speaker:
    def __init__(self):
        self._ack_cache: dict[str, tuple] = {}
        import threading

        self._stop = threading.Event()  # set = the owner said "stop", shut up
        # ...or held his palm up: gestures.py needs the same off switch the
        # voice "stop" uses, without knowing how speech playback works
        threading.Thread(target=self._preload_acks, daemon=True).start()

    @staticmethod
    def _night(audio):
        """Delivery gain: softer at night, a touch livelier when the owner's
        excited, gentler when he's annoyed."""
        return audio * MOOD_GAIN[_mood_now()]

    def _play(self, audio, sr) -> bool:
        """Play, interruptibly: polls the stop flag while audio runs.
        Returns False if the owner cut it off."""
        import time as _t

        device = None
        try:
            import audio_out

            device = audio_out.output_index()  # survives PortAudio resets
        except Exception:
            pass
        try:
            sd.play(self._night(audio), sr, device=device)
        except Exception:
            sd.play(self._night(audio), sr)  # any trouble → default device
        total = len(audio) / float(sr)
        t0 = _t.time()
        while _t.time() - t0 < total + 0.25:
            if self._stop.is_set():
                sd.stop()
                return False
            _t.sleep(0.05)
        sd.wait()
        return True

    def _arm_stop_listener(self):
        """While TARS talks, a tiny keyword-spotter listens for 'stop'.
        Returns a disarm() callable. Fails safe: no listener, no harm."""
        import json as _json
        import sys as _sys
        import threading

        if _sys.platform != "win32":
            # Mac Lite: a second live mic stream during playback stuttered
            # the mate's speech badly (worse when Continuity grabbed the
            # iPhone). No "stop" interrupt off-Windows until proven safe.
            return lambda: None
        global _VOSK_STOP
        try:
            from pathlib import Path

            from vosk import KaldiRecognizer, Model

            if _VOSK_STOP is None:
                _VOSK_STOP = Model(str(Path(__file__).parent / "wakeword"
                                       / "vosk-model-small-en-us-0.15"))
            rec = KaldiRecognizer(_VOSK_STOP, 16000, '["stop", "[unk]"]')
            import audio_out

            device = audio_out.pick_input()
            alive = {"on": True}

            def listen():
                try:
                    with sd.RawInputStream(samplerate=16000, blocksize=1600,
                                           dtype="int16", channels=1,
                                           device=device) as stream:
                        while alive["on"] and not self._stop.is_set():
                            data, _ = stream.read(1600)
                            if rec.AcceptWaveform(bytes(data)):
                                heard = _json.loads(rec.Result()).get("text", "")
                                if "stop" in heard:
                                    self._stop.set()
                                    return
                except Exception:
                    pass

            threading.Thread(target=listen, daemon=True).start()
            return lambda: alive.update(on=False)
        except Exception:
            return lambda: None

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
                if self._stop.is_set():
                    break  # the owner cut it off — stop synthesizing too
                if not s:
                    continue
                res = _synth(s)
                item = (s, res[0], res[1]) if res is not None else (s, None, None)
                while not self._stop.is_set():
                    try:
                        q.put(item, timeout=0.5)
                        break
                    except queue.Full:
                        continue
            # DONE must ARRIVE — dropping it on a full queue once left TARS
            # frozen in "Speaking…" for 60s after every long reply
            while not self._stop.is_set():
                try:
                    q.put(DONE, timeout=0.5)
                    break
                except queue.Full:
                    continue

        threading.Thread(target=producer, daemon=True).start()
        spoken = []
        import duck
        self._stop.clear()
        disarm = self._arm_stop_listener()
        duck.duck()  # games/music dip while TARS talks
        try:
            idle = 0
            while not self._stop.is_set() and idle < 16:  # 8s dead air = bail
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    idle += 1
                    continue
                idle = 0
                if item is DONE:
                    break
                s, audio, sr = item
                spoken.append(s)
                if audio is not None:
                    if not self._play(audio, sr):
                        break  # the owner said stop — drop the rest
                else:
                    self._say_offline(s)
            while not q.empty():  # unblock the producer
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        finally:
            disarm()
            duck.restore()
        return " ".join(spoken)

    def shut_up(self) -> None:
        """Cut the current reply off mid-word. Same switch the spoken
        "stop" flips — used by the palm-up hand signal."""
        self._stop.set()

    def say(self, text: str) -> None:
        if not text:
            return
        res = _synth(text)
        import duck
        self._stop.clear()
        disarm = self._arm_stop_listener()
        duck.duck()  # games/music dip while TARS talks
        try:
            if res is not None:
                self._play(res[0], res[1])
            else:
                self._say_offline(text)
        finally:
            disarm()
            duck.restore()

    def _say_offline(self, text: str) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        for v in engine.getProperty("voices"):
            if "george" in v.name.lower() or "hazel" in v.name.lower():
                engine.setProperty("voice", v.id)
                break
        engine.say(text)
        engine.runAndWait()
