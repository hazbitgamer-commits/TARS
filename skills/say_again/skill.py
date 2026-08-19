"""Repeat the last thing TARS said — again, slower, or spelled out."""
import datetime
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("REPEAT what TARS just said — 'say that again', 'what did you say', "
               "'repeat that slower', 'spell that'. Reads back its own last answer. "
               "NOT for repeating something the owner said.")
ARGS = {"style": "'again' (default), 'slower', or 'spell' to spell the key part out"}

ECHOES = ("i said:", "letter by letter")


def _last_said() -> str:
    log = BASE / "logs" / f"{datetime.date.today().isoformat()}.jsonl"
    if not log.exists():
        return ""
    for line in reversed(log.read_text(encoding="utf-8").splitlines()):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("kind") != "said":
            continue
        text = (entry.get("text") or "").strip()
        # never echo a previous repeat — that way lies a hall of mirrors
        if text and not text.lower().startswith(ECHOES):
            return text
    return ""


def run(args: dict) -> str:
    style = (args.get("style") or "again").strip().lower()
    text = _last_said()
    if not text:
        return "I haven't said anything worth repeating yet today."

    if style.startswith("spell"):
        words = [w.strip(".,!?:;") for w in text.split() if w.strip(".,!?:;")]
        # the useful thing to spell is usually a code, a number or the longest word
        target = max(words, key=lambda w: (any(c.isdigit() for c in w), len(w)))
        return "Letter by letter: " + ", ".join(target.upper())

    if style.startswith(("slow", "clear", "again slow")):
        # commas and full stops are what the voice breathes on
        return "I said, slowly: " + text.replace(", ", ", ... ").replace(". ", ". ... ")
    return f"I said: {text}"
