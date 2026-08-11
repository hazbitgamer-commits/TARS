"""Timers and reminders. Stored in timers.json; main.py watches and announces."""
import datetime
import json
import re
import uuid
from pathlib import Path

DESCRIPTION = ("Set, list, or cancel timers and reminders. E.g. 'set a timer for 10 minutes', "
               "'remind me to check the oven in 25 minutes', 'remind me to call mum at 5 pm', "
               "'cancel my timers', 'what timers are running'.")
ARGS = {"action": "'set', 'list', or 'cancel'",
        "when": "duration like '10 minutes' / '1 hour 30 minutes', or clock time like '5:30 pm'",
        "label": "what the reminder is for, if the owner said one"}

TIMERS_FILE = Path(__file__).resolve().parents[2] / "timers.json"


def _load() -> list[dict]:
    try:
        return json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(timers: list[dict]) -> None:
    TIMERS_FILE.write_text(json.dumps(timers, indent=1), encoding="utf-8")


def _parse_when(when: str) -> datetime.datetime | None:
    when = when.lower().strip()
    now = datetime.datetime.now()

    # clock time: "5 pm", "5:30 pm", "17:45"
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", when)
    if m and ("am" in when or "pm" in when or ":" in when) and "minute" not in when and "hour" not in when and "second" not in when:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and hour < 12:
            hour += 12
        if m.group(3) == "am" and hour == 12:
            hour = 0
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            due += datetime.timedelta(days=1)
        return due

    # duration: "10 minutes", "1 hour 30 minutes", "90 seconds"
    total = 0
    for num, unit in re.findall(r"(\d+)\s*(hour|minute|min|second|sec)", when):
        n = int(num)
        total += n * 3600 if "hour" in unit else n * 60 if "min" in unit else n
    if total:
        return now + datetime.timedelta(seconds=total)
    return None


def _say_due(due: datetime.datetime) -> str:
    delta = due - datetime.datetime.now()
    mins = round(delta.total_seconds() / 60)
    if mins < 1:
        return f"{round(delta.total_seconds())} seconds"
    if mins < 120:
        return f"{mins} minutes"
    return due.strftime("%I:%M %p").lstrip("0")


def run(args: dict) -> str:
    action = (args.get("action") or "set").strip().lower()
    timers = _load()

    if action == "list":
        if not timers:
            return "No timers running."
        parts = [f"{t['label'] or 'timer'} in {_say_due(datetime.datetime.fromisoformat(t['due']))}"
                 for t in timers]
        return "Running: " + "; ".join(parts) + "."

    if action == "cancel":
        if not timers:
            return "Nothing to cancel."
        _save([])
        return f"Cancelled {len(timers)} timer{'s' if len(timers) > 1 else ''}."

    when = (args.get("when") or "").strip()
    due = _parse_when(when) if when else None
    if due is None:
        return "For how long, or at what time?"
    label = (args.get("label") or "").strip()
    timers.append({"id": uuid.uuid4().hex[:8], "due": due.isoformat(), "label": label})
    _save(timers)
    what = f"Reminder set: {label}" if label else "Timer set"
    return f"{what}, in {_say_due(due)}."
