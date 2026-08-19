"""Snooze: re-arm the timer that just went off."""
import datetime
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("SNOOZE the alarm or reminder that just went off — 'snooze', "
               "'snooze ten minutes', 'give me five more minutes', 'remind me "
               "again shortly'. Re-arms the reminder that most recently rang. "
               "NOT for setting a brand-new timer (that's the timers skill).")
ARGS = {"minutes": "how many minutes to snooze for (default 9)"}

LAST = BASE / "last_fired.json"
TIMERS = BASE / "timers.json"
STALE_MINUTES = 60  # older than this and it isn't a snooze, it's a new timer


def run(args: dict) -> str:
    raw = str(args.get("minutes", "") or "").strip()
    digits = "".join(c for c in raw if c.isdigit())
    minutes = max(1, min(120, int(digits))) if digits else 9

    try:
        last = json.loads(LAST.read_text(encoding="utf-8"))
        fired = datetime.datetime.fromisoformat(last["at"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return "Nothing's gone off recently to snooze."
    if (datetime.datetime.now() - fired).total_seconds() > STALE_MINUTES * 60:
        return ("The last reminder was a while ago — say set a timer instead "
                "if you want a fresh one.")

    label = (last.get("label") or "").strip()
    due = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    try:
        timers = json.loads(TIMERS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        timers = []
    import uuid

    timers.append({"id": uuid.uuid4().hex[:8], "due": due.isoformat(),
                   "label": label})
    TIMERS.write_text(json.dumps(timers, indent=1), encoding="utf-8")
    what = f" for {label}" if label else ""
    return f"Snoozed{what} — I'll nudge you again in {minutes} minutes."
