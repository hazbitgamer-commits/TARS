"""Checked by main.py's standby loop: returns timers that are now due."""
import datetime
import json
from pathlib import Path

TIMERS_FILE = Path(__file__).parent / "timers.json"


RECURRING_FILE = Path(__file__).parent / "recurring.json"


def _recurring_due(now: datetime.datetime) -> list[str]:
    """Weekly repeating reminders (bins every Tuesday 8pm) — fire once on
    their day at/after their time, marked by date so restarts are safe."""
    try:
        entries = json.loads(RECURRING_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    spoken, changed = [], False
    today = now.date().isoformat()
    for e in entries:
        try:
            if int(e["weekday"]) != now.weekday() or e.get("last") == today:
                continue
            hh, mm = (int(x) for x in e["time"].split(":"))
            if (now.hour, now.minute) >= (hh, mm):
                e["last"] = today
                changed = True
                spoken.append(f"Weekly reminder: {e['label']}.")
        except (KeyError, ValueError):
            continue
    if changed:
        RECURRING_FILE.write_text(json.dumps(entries, indent=1),
                                  encoding="utf-8")
    return spoken


def pop_due() -> list[str]:
    """Announcements for due timers; removes them from the file."""
    now = datetime.datetime.now()
    out = _recurring_due(now)
    try:
        timers = json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return out
    due = [t for t in timers if datetime.datetime.fromisoformat(t["due"]) <= now]
    if due:
        keep = [t for t in timers if t not in due]
        TIMERS_FILE.write_text(json.dumps(keep, indent=1), encoding="utf-8")
        out += [
            f"Reminder: {t['label']}." if t.get("label") else "Your timer is up."
            for t in due
        ]
    return out
