"""List the text-to-speech VOICES TARS can speak with, and name the one
that's active right now. Read-only companion to the voice_settings skill,
which actually changes the voice."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("List the text-to-speech VOICES TARS can speak with (names and "
               "accents), and say which one is active right now. E.g. 'list your "
               "voices', 'what voices do you have', 'what voices can you use'. "
               "NOT for changing the voice or speed, and NOT for which speaker/"
               "device the sound plays through — those are different skills.")
ARGS = {}

VOICE_MENU = ("the new local voices: George (British male, default), Fable, Lewis "
              "and Daniel (British males), Emma and Isabella (British females) — "
              "plus the older internet voices: Ryan, Sonia, Guy, Jenny, William "
              "and Natasha")

# voice id -> the friendly name Jacob knows it by
_NAMES = {
    "bm_george": "George", "bm_fable": "Fable", "bm_lewis": "Lewis", "bm_daniel": "Daniel",
    "bf_emma": "Emma", "bf_isabella": "Isabella",
    "en-GB-RyanNeural": "Ryan", "en-GB-SoniaNeural": "Sonia",
    "en-US-GuyNeural": "Guy", "en-US-JennyNeural": "Jenny", "en-US-AriaNeural": "Aria",
    "en-US-DavisNeural": "Davis",
    "en-AU-WilliamNeural": "William", "en-AU-NatashaNeural": "Natasha",
}


def _current_name() -> str:
    try:
        import tts
        return _NAMES.get(tts.VOICE, tts.VOICE)
    except Exception:
        return ""


def run(args: dict) -> str:
    current = _current_name()
    tail = f" Right now I'm using {current}." if current else ""
    return f"I can sound like: {VOICE_MENU}.{tail}"
