"""Where TARS's voice comes out. Persisted in audio_out.json; applied at
startup and switchable by voice ("speak through the monitor speakers")."""
import json
from pathlib import Path

import sounddevice as sd

FILE = Path(__file__).parent / "audio_out.json"

# generic words → device-name fragments (virtual junk excluded for these)
ALIASES = {
    "monitor": ("g27",), "screen": ("g27",), "lenovo": ("g27",), "display": ("g27",),
    "headphones": ("headphones",), "headset": ("headphones",),
    "quest": ("oculus",), "oculus": ("oculus",),
}
VIRTUAL_JUNK = ("steam", "dualsense", "virtual", "sound mapper")


def outputs() -> list[tuple[int, str]]:
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["max_output_channels"] > 0 and d["hostapi"] == 0
            and "sound mapper" not in d["name"].lower()]


def resolve(target: str) -> tuple[int | None, str | None]:
    t = target.strip().lower()
    fragments = ALIASES.get(t, (t,))
    allow_virtual = t in ("quest", "oculus") or not ALIASES.get(t)
    for i, name in outputs():
        low = name.lower()
        if not allow_virtual and any(j in low for j in VIRTUAL_JUNK):
            continue
        if any(f in low for f in fragments):
            return i, name
    return None, None


def set_output(target: str) -> str | None:
    idx, name = resolve(target)
    if idx is None:
        return None
    current = sd.default.device
    sd.default.device = (current[0] if isinstance(current, (list, tuple)) else None, idx)
    FILE.write_text(json.dumps({"target": target, "name": name}), encoding="utf-8")
    return name


MIC_PREFER = ("hd-3000", "desktop microphone")  # the LifeCam — never a gamepad
# Mac: the built-in mic, NEVER the iPhone — macOS Continuity offers the
# phone as a wireless mic and grabbing it wrecks audio (glitchy speech,
# deaf wake word — the mate's MacBook found this the hard way)
MIC_PREFER_MAC = ("macbook", "built-in", "internal")
MIC_EXCLUDE_MAC = ("iphone", "ipad", "continuity")


_DEAD_MICS: set = set()  # devices that went silent while TARS was using them


def mark_dead(index) -> None:
    """Don't come back to a mic that went deaf mid-session.

    His LifeCam passes a quarter-second probe and then delivers digital
    silence through the long-lived stream — so proving it at startup isn't
    enough. When the listening loop notices sustained silence it calls
    this, and the next pick skips that device entirely."""
    if index is not None:
        _DEAD_MICS.add(int(index))


def pick_input() -> int | None:
    """The index of the mic TARS should use — pinned per platform, so a
    freshly connected DualSense (or a Continuity iPhone) can't hijack it."""
    import sys

    on_mac_like = sys.platform != "win32"
    prefer = MIC_PREFER_MAC if on_mac_like else MIC_PREFER
    candidates = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0 or i in _DEAD_MICS:
            continue
        if not on_mac_like and d["hostapi"] != 0:
            continue
        low = d["name"].lower()
        if any(j in low for j in VIRTUAL_JUNK) or "sound mapper" in low:
            continue
        if on_mac_like and any(j in low for j in MIC_EXCLUDE_MAC):
            continue
        if any(f in low for f in prefer):
            candidates.insert(0, i)  # preferred, but still has to WORK
        elif "dualsense" not in low and "oculus" not in low:
            candidates.append(i)
    if not candidates:
        return None
    # A pinned mic that delivers SILENCE is worse than no mic: TARS sits
    # there looking healthy, hearing nothing, for hours. His webcam mic did
    # exactly that — fine to sd.rec(), digital silence through the stream
    # TARS actually opens. So prove each candidate before trusting it.
    working = [i for i in candidates[:6] if _delivers_audio(i)]
    if working:
        return working[0]
    # LAST RESORT: nothing preferred is delivering. A gamepad headset is a
    # daft microphone for a desk assistant, but being deaf is worse — take
    # anything that actually carries sound. main() says which it chose.
    for i, d in enumerate(sd.query_devices()):
        if (d["max_input_channels"] > 0 and d["hostapi"] == 0
                and i not in candidates and i not in _DEAD_MICS
                and _delivers_audio(i)):
            return i
    return candidates[0]


def input_name(index) -> str:
    try:
        return str(sd.query_devices()[index]["name"])[:40]
    except Exception:
        return "unknown microphone"


def _delivers_audio(index: int, seconds: float = 0.25) -> bool:
    """Open it the same way the listening loop does and see if anything
    at all comes through. Digital silence = a dead endpoint."""
    import numpy as np

    try:
        with sd.RawInputStream(samplerate=16000, blocksize=1280,
                               dtype="int16", channels=1, device=index) as st:
            peak = 0.0
            for _ in range(max(2, int(seconds * 16000 / 1280))):
                data, _ = st.read(1280)
                pcm = np.frombuffer(bytes(data), dtype=np.int16)
                peak = max(peak, float(np.max(np.abs(pcm))) / 32768.0)
            # a live mic in a silent room still has a noise floor; a dead
            # endpoint returns zeros or a single stuck LSB
            # 1e-4 was too generous: his LifeCam returns a stuck
            # low-order bit (9e-05) that passes as "audio" while being
            # deaf. A real mic's room noise sits around 2e-3.
            return peak > 5e-4
    except Exception:
        return False


def apply_saved() -> None:
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
        set_output(saved.get("target", ""))
    except (FileNotFoundError, json.JSONDecodeError):
        pass


_out_cache: dict = {"t": 0.0, "idx": None}


def output_index() -> int | None:
    """The saved output device, re-resolved fresh (5s cache). tts passes
    this to EVERY play — sd.default silently reverts to system default
    whenever the mic-crash recovery reinitializes PortAudio, which once
    left the owner's voice on unworn headphones while he sat at the monitor."""
    import time

    if time.time() - _out_cache["t"] < 5:
        return _out_cache["idx"]
    idx = None
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
        idx, _ = resolve(saved.get("target", ""))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    _out_cache.update(t=time.time(), idx=idx)
    return idx
