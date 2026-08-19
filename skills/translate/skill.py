"""Translate — and say it in a native voice, not an English one reading foreign words."""
import json
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("TRANSLATE something into another language and SAY it properly — "
               "'how do you say good morning in Japanese', 'translate I'm hungry "
               "into Spanish', 'what's thank you in French'. Speaks the result in "
               "a native voice for that language.")
ARGS = {"text": "the words to translate",
        "language": "the language to translate into (e.g. japanese, spanish)"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

# language -> (kokoro voice, kokoro lang code, spoken name)
VOICES = {
    "spanish": ("ef_dora", "es", "Spanish"), "french": ("ff_siwis", "fr-fr", "French"),
    "italian": ("if_sara", "it", "Italian"), "japanese": ("jf_alpha", "ja", "Japanese"),
    "chinese": ("zf_xiaobei", "cmn", "Chinese"), "mandarin": ("zf_xiaobei", "cmn", "Chinese"),
    "portuguese": ("pf_dora", "pt-br", "Portuguese"), "brazilian": ("pf_dora", "pt-br", "Portuguese"),
    "hindi": ("hf_alpha", "hi", "Hindi"),
    "english": ("bm_george", "en-gb", "English"), "british": ("bm_george", "en-gb", "English"),
}


def _bg_model() -> str:
    try:
        from platform_caps import bg_model

        return bg_model()
    except Exception:
        return "qwen3:8b"


def run(args: dict) -> str:
    text = (args.get("text") or "").strip()
    language = (args.get("language") or "").strip().lower()
    if not text:
        return "Translate what, exactly?"
    if not language:
        return "Into which language?"
    for key in VOICES:
        if key in language:
            language = key
            break

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": _bg_model(), "stream": False, "think": False, "format": "json",
            "messages": [{"role": "user", "content":
                f"Translate into {language}: {text!r}\n"
                'Reply JSON only: {"translation": "<the translation>", '
                '"pronunciation": "<how an English speaker would say it, or empty '
                'if the language uses the Latin alphabet>"}'}],
            "options": {"temperature": 0}}, timeout=90)
        r.raise_for_status()
        data = json.loads(r.json()["message"]["content"])
    except Exception:
        return "My translator didn't answer just then. Try again in a moment."

    translation = str(data.get("translation", "")).strip()
    if not translation:
        return f"I couldn't get that into {language}."
    said = say_native(translation, language)
    how = str(data.get("pronunciation", "")).strip()
    # if the script isn't ours AND we couldn't speak it, the sounds are all he has
    if how and not said:
        return f"In {language}: {translation} — say it like: {how}."
    return f"In {language}: {translation}."


def say_native(translation: str, language: str) -> bool:
    """Speak the translation in that language's own voice. True if it played."""
    entry = VOICES.get(language)
    if not entry:
        return False
    voice, lang_code, _ = entry
    try:
        import sounddevice as sd
        import tts

        audio, rate = tts._kokoro_engine().create(
            translation, voice=voice, speed=0.95, lang=lang_code)
        sd.play(audio, rate)
        sd.wait()
        return True
    except Exception:
        return False
