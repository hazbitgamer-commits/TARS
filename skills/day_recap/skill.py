"""'What did I do today?' — a spoken recap mined from the day's journal
(every skill action lands there) and conversation notes. Local model."""
import datetime
import json
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()

DESCRIPTION = ("Spoken recap of Jacob's day with TARS — 'what did I do "
               "today', 'recap my day', 'what happened today'. Summarizes "
               "the day's journal and conversations. NOT for calendar "
               "agendas (calendar) and NOT for recalling stored facts "
               "(recall).")
ARGS = {"day": "'today' (default) or 'yesterday'"}


def run(args: dict) -> str:
    day = datetime.date.today()
    if "yester" in str(args.get("day", "")).lower():
        day -= datetime.timedelta(days=1)
    lines = []
    journal = BASE / "vault" / "Journal" / f"Journal {day.isoformat()}.md"
    if journal.exists():
        lines += [l for l in journal.read_text(encoding="utf-8").splitlines()
                  if l.strip().startswith("-")][-40:]
    convo = BASE / "vault" / "Conversations" / f"Conversation {day.isoformat()}.md"
    if convo.exists():
        lines += [l for l in convo.read_text(encoding="utf-8").splitlines()
                  if "Jacob:" in l][-30:]
    if not lines:
        which = "today" if day == datetime.date.today() else "yesterday"
        return f"Nothing logged {which} — a quiet one, or I slept through it."
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content":
                "From these journal lines from Jacob's day with his "
                "assistant, give a SPOKEN three-sentence recap — what he "
                "did, most notable first, plain conversational text, no "
                "markdown, no invented details:\n" + "\n".join(lines)}]},
            timeout=120)
        r.raise_for_status()
        summary = r.json()["message"]["content"].strip()
        return summary[:600] if summary else "The log's there but I couldn't sum it up."
    except Exception:
        return "My summarizer brain isn't answering right now."
