"""Who's talking? — voice fingerprints (vosk x-vectors), so TARS knows
Jacob from Sophie from a mate without anyone toggling guest mode.

voices.json holds a few 128-dim vectors per person. enroll() adds one from
a recorded command; identify() names the speaker of an audio clip. Unknown
voices get the guest treatment: no personal facts, polite and generic.
"""
import json
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
FILE = BASE / "voices.json"
SPK_MODEL = BASE / "wakeword" / "vosk-model-spk-0.4"
WAKE_MODEL = BASE / "wakeword" / "vosk-model-small-en-us-0.15"
MATCH = 0.55        # cosine similarity floor — above this it's a match
MIN_SECONDS = 0.8   # shorter clips give unreliable fingerprints

_rec = None


def _recognizer():
    global _rec
    if _rec is None:
        from vosk import KaldiRecognizer, Model, SpkModel

        _rec = KaldiRecognizer(Model(str(WAKE_MODEL)), 16000)
        _rec.SetSpkModel(SpkModel(str(SPK_MODEL)))
    return _rec


def _db() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(db: dict) -> None:
    FILE.write_text(json.dumps(db, indent=1), encoding="utf-8")


def fingerprint(audio: np.ndarray) -> list | None:
    """A voice vector from float32 mono 16k audio, or None if too short."""
    if audio is None or len(audio) < 16000 * MIN_SECONDS:
        return None
    try:
        rec = _recognizer()
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()
        rec.AcceptWaveform(pcm)
        result = json.loads(rec.FinalResult())
        vec = result.get("spk")
        return vec if vec else None
    except Exception:
        return None


def _cos(a: list, b: list) -> float:
    x, y = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    return float(x @ y / ((np.linalg.norm(x) * np.linalg.norm(y)) + 1e-9))


def identify(audio: np.ndarray) -> str | None:
    """Name of the speaker, or None for unknown/too-short."""
    vec = fingerprint(audio)
    if vec is None:
        return None
    best, score = None, 0.0
    for name, prints in _db().items():
        for known in prints:
            s = _cos(vec, known)
            if s > score:
                best, score = name, s
    return best if score >= MATCH else None


def enroll(name: str, audio: np.ndarray) -> str:
    vec = fingerprint(audio)
    if vec is None:
        return ("That clip was too short to fingerprint — say a full "
                "sentence and I'll learn your voice.")
    db = _db()
    db.setdefault(name, [])
    db[name] = (db[name] + [vec])[-5:]
    _save(db)
    return (f"Learned your voice, {name} — {len(db[name])} sample"
            f"{'s' if len(db[name]) != 1 else ''} on file. The more you "
            f"talk, the surer I get.")


def known() -> list[str]:
    return sorted(_db().keys())


def forget(name: str) -> str:
    db = _db()
    if name not in db:
        return f"I don't have a voice profile for {name}."
    del db[name]
    _save(db)
    return f"Forgotten {name}'s voice."
