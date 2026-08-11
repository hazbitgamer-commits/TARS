"""Customize TARS's own speaking VOICE (which neural voice, how fast) —
not which speaker it comes out of (that's voice_output) and not personality
traits like humor/sarcasm (that's personality)."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

SETTINGS_FILE = BASE / "voice_settings.json"

DESCRIPTION = ("Customize TARS's own text-to-speech VOICE: pick a different voice "
               "(accent/gender) or change how fast TARS talks, or read the current "
               "settings back. E.g. 'sound like an American male', 'talk faster', "
               "'set your speed to 20', 'what voice are you using'. NOT for which "
               "speaker/device the sound plays through, and NOT for personality "
               "traits like humor or sarcasm — those are different skills.")
ARGS = {"voice": "a name/description like 'ryan', 'sonia', 'british female', "
                 "'us male', 'australian', 'list' to hear the options, or blank "
                 "to leave the voice unchanged",
        "rate": "+N or -N to nudge speaking speed percent, a plain number for an "
                "absolute speed percent (e.g. '20' means +20%), or 'get' to just "
                "read the current settings",
        "style": "'smooth' when the owner wants fewer pauses at commas/full stops, "
                 "'normal' to restore standard pausing"}

# friendly words -> voice ids (bm_/bf_ = the local Kokoro voices, more human;
# en-XX-...Neural = the older internet voices, kept as options)
ALIASES = {
    "george": "bm_george", "default": "bm_george", "tars": "bm_george",
    "new voice": "bm_george", "deep british": "bm_george",
    "fable": "bm_fable", "lewis": "bm_lewis", "daniel": "bm_daniel",
    "emma": "bf_emma", "isabella": "bf_isabella",
    "ryan": "en-GB-RyanNeural", "british male": "bm_george", "british": "bm_george",
    "old voice": "en-GB-RyanNeural",
    "sonia": "en-GB-SoniaNeural", "british female": "en-GB-SoniaNeural",
    "guy": "en-US-GuyNeural", "us male": "en-US-GuyNeural", "american male": "en-US-GuyNeural",
    "american": "en-US-GuyNeural", "us": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural", "us female": "en-US-JennyNeural", "american female": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "davis": "en-US-DavisNeural",
    "william": "en-AU-WilliamNeural", "australian male": "en-AU-WilliamNeural", "australian": "en-AU-WilliamNeural",
    "natasha": "en-AU-NatashaNeural", "australian female": "en-AU-NatashaNeural",
}
VOICE_MENU = ("the new local voices: George (British male, default), Fable, Lewis "
              "and Daniel (British males), Emma and Isabella (British females) — "
              "plus the older internet voices: Ryan, Sonia, Guy, Jenny, William "
              "and Natasha")


def _load() -> dict:
    import tts
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"voice": tts.VOICE, "rate": tts.RATE}


def _save(voice: str, rate: str) -> None:
    SETTINGS_FILE.write_text(json.dumps({"voice": voice, "rate": rate}, indent=2),
                              encoding="utf-8")


def _rate_pct(rate: str) -> int:
    try:
        return int(rate.strip().rstrip("%").lstrip("+"))
    except ValueError:
        return 0


def _speak_name(voice_id: str) -> str:
    for nice, vid in ALIASES.items():
        if vid == voice_id:
            return nice.title()
    return voice_id


def run(args: dict) -> str:
    import tts

    saved = _load()
    voice_id, rate = saved.get("voice", tts.VOICE), saved.get("rate", tts.RATE)

    voice_req = str(args.get("voice", "")).strip().lower()
    rate_req = str(args.get("rate", "")).strip().lower().rstrip("%")
    style_req = str(args.get("style", "")).strip().lower()

    if voice_req == "list":
        return f"I can sound like: {VOICE_MENU}."

    if not voice_req and rate_req in ("", "get") and not style_req:
        return f"I'm using {_speak_name(voice_id)} at speed {_rate_pct(rate):+d} percent."

    changed = []
    if voice_req:
        if voice_req in ALIASES:
            voice_id = ALIASES[voice_req]
        elif voice_req.startswith(("bm_", "bf_", "am_", "af_")):
            voice_id = voice_req  # already a Kokoro voice id
        elif voice_req.count("-") == 2 and voice_req.lower().endswith("neural"):
            voice_id = voice_req  # already a real edge-tts voice id
        else:
            return (f"I don't know a voice called {voice_req}. Say 'list voices' "
                     "to hear the options.")
        changed.append(f"voice to {_speak_name(voice_id)}")

    if rate_req and rate_req != "get":
        current = _rate_pct(rate)
        if rate_req.startswith(("+", "-")) and rate_req[1:].isdigit():
            new_pct = current + int(rate_req)
        elif rate_req.isdigit():
            new_pct = int(rate_req)
        else:
            return f"Speed is at {current:+d} percent."
        new_pct = max(-50, min(100, new_pct))
        rate = f"{new_pct:+d}%"
        changed.append(f"speed to {new_pct:+d} percent")

    smooth = getattr(tts, "SMOOTH", False)
    if style_req in ("smooth", "fewer pauses", "less pauses", "flowing"):
        smooth = True
        changed.append("speech to smooth — fewer pauses")
    elif style_req in ("normal", "standard"):
        smooth = False
        changed.append("speech back to normal pausing")

    tts.VOICE = voice_id
    tts.RATE = rate
    tts.SMOOTH = smooth
    SETTINGS_FILE.write_text(
        json.dumps({"voice": voice_id, "rate": rate, "smooth": smooth}, indent=2),
        encoding="utf-8")

    if not changed:
        return f"I'm using {_speak_name(voice_id)} at speed {_rate_pct(rate):+d} percent."
    return "Changed " + " and ".join(changed) + ". Testing, testing."
