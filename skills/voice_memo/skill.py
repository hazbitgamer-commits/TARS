"""Voice memos: say the thought out loud, get a written, summarised note.

Records from the mic, transcribes it locally, has the background model give
it a title and a one-line summary, and files it in the vault so the neuron
brain picks it up like any other memory.
"""
import datetime
import json
import re
import sys
from pathlib import Path

import numpy as np
import requests

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("VOICE MEMO — record a longer thought and save it as a written note: "
               "'take a voice memo', 'record a note', 'let me dictate a thought'. "
               "Records until the owner stops talking, writes it down in the vault "
               "with a summary. NOT for one-line facts ('remember that...' is the "
               "remember skill) and NOT for typing into a window (dictation).")
ARGS = {"seconds": "maximum recording length in seconds (default 120)"}

SAMPLE_RATE = 16000
FRAME = 1600                # 100 ms
SILENCE_STOP = 3.0          # end the memo after this much quiet
MIN_WORDS = 3
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"


def _bg_model() -> str:
    try:
        from platform_caps import bg_model

        return bg_model()
    except Exception:
        return "qwen3:8b"


def _record(max_seconds: int) -> np.ndarray | None:
    import sounddevice as sd

    try:
        from audio_out import pick_input

        device = pick_input()
    except Exception:
        device = None

    frames, heard, quiet_frames = [], False, 0
    per_second = SAMPLE_RATE / FRAME
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=FRAME, channels=1,
                            dtype="float32", device=device) as stream:
            for _ in range(int(max_seconds * per_second)):
                block, _ = stream.read(FRAME)
                mono = block[:, 0]
                frames.append(mono.copy())
                loud = float(np.sqrt(np.mean(mono ** 2))) > 0.012
                if loud:
                    heard, quiet_frames = True, 0
                elif heard:
                    quiet_frames += 1
                    if quiet_frames > SILENCE_STOP * per_second:
                        break
    except Exception:
        return None
    return np.concatenate(frames) if heard else None


def _write_note(text: str, meta: dict) -> Path:
    folder = BASE / "vault" / "Voice memos"
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    title = re.sub(r'[<>:"/\\|?*\[\]#^]', "", meta.get("title") or "Voice memo")[:60]
    path = folder / f"{title} {now:%Y-%m-%d}.md"
    tags = "".join(f"\n  - {re.sub(r'[^a-z0-9-]', '', str(t).lower())}"
                   for t in meta.get("tags", [])[:3])
    path.write_text(
        f"---\ncreated: {now:%Y-%m-%d}\ntags:{tags or ' []'}\n---\n\n"
        f"**{meta.get('summary', '').strip()}**\n\n"
        f"> Spoken at {now:%I:%M %p}, {now:%A %d %B %Y}\n\n{text}\n",
        encoding="utf-8")
    return path


def run(args: dict) -> str:
    raw = "".join(c for c in str(args.get("seconds", "") or "") if c.isdigit())
    max_seconds = max(10, min(300, int(raw))) if raw else 120

    audio = _record(max_seconds)
    if audio is None:
        return ("I couldn't get a clean recording — the mic may be busy. "
                "Try again, or just tell me and I'll remember it.")

    try:
        import stt

        text = stt.Transcriber().transcribe(audio).strip()
    except Exception:
        return "I recorded it but couldn't transcribe it. That's a first."
    if len(text.split()) < MIN_WORDS:
        return "That was too short to keep. Say the memo after the beep next time."

    meta = {"title": "Voice memo", "summary": "", "tags": []}
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": _bg_model(), "stream": False, "think": False, "format": "json",
            "messages": [{"role": "user", "content":
                f"A spoken memo, transcribed:\n{text}\n\n"
                'Reply JSON only: {"title": "<3-6 word title>", '
                '"summary": "<one sentence capturing the point>", '
                '"tags": ["<one-word>", ...max 3]}'}],
            "options": {"temperature": 0.2}}, timeout=90)
        meta.update(json.loads(r.json()["message"]["content"]))
    except Exception:
        meta["summary"] = text[:120]

    path = _write_note(text, meta)
    words = len(text.split())
    return (f"Memo saved as {path.stem} — {words} words. "
            f"{meta.get('summary', '').strip()}")
