"""Weekly repeating reminders: "remind me to take the bins out every
Tuesday at 8 pm." Stored in recurring.json; timers_watch fires them."""
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FILE = BASE / "recurring.json"

DESCRIPTION = ("REPEATING weekly reminders — 'remind me to take the bins out "
               "every Tuesday at 8 pm', 'what are my weekly reminders', "
               "'remove the bins reminder'. Survives restarts and repeats "
               "every week. NOT for one-off timers ('in 20 minutes') — "
               "that's the timers skill.")
ARGS = {"action": "'add', 'list', or 'remove'",
        "label": "what to be reminded about",
        "day": "weekday name, e.g. tuesday",
        "time": "clock time, e.g. '8 pm' or '19:30'"}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"]


def _load() -> list:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _parse_time(raw: str):
    raw = raw.strip().lower().replace(".", "")
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", raw)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and hh < 12:
        hh += 12
    if m.group(3) == "am" and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm:02d}" if 0 <= hh < 24 and 0 <= mm < 60 else None


def run(args: dict) -> str:
    action = str(args.get("action", "list")).strip().lower()
    entries = _load()

    if action == "add":
        label = str(args.get("label", "")).strip().rstrip(".")
        day = str(args.get("day", "")).strip().lower()
        weekday = next((i for i, n in enumerate(WEEKDAYS) if n in day), None)
        hhmm = _parse_time(str(args.get("time", "")))
        if not label or weekday is None or not hhmm:
            return ("I need the what, the day, and the time — like 'bins "
                    "every Tuesday at 8 pm'.")
        entries.append({"label": label, "weekday": weekday, "time": hhmm})
        FILE.write_text(json.dumps(entries, indent=1), encoding="utf-8")
        nice = f"{int(hhmm[:2]) % 12 or 12} {'pm' if int(hhmm[:2]) >= 12 else 'am'}"
        return f"Done — every {WEEKDAYS[weekday].title()} at {nice}: {label}."

    if action == "remove":
        label = str(args.get("label", "")).strip().lower()
        match = next((e for e in entries if label and label in
                      e["label"].lower()), None)
        if not match:
            return f"I don't have a weekly reminder about {label}."
        entries.remove(match)
        FILE.write_text(json.dumps(entries, indent=1), encoding="utf-8")
        return f"Removed the {match['label']} reminder."

    if not entries:
        return "No weekly reminders set."
    return "Your weekly reminders: " + "; ".join(
        f"{e['label']} every {WEEKDAYS[e['weekday']].title()} at {e['time']}"
        for e in entries) + "."
