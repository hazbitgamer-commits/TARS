"""Checked by main.py's standby loop: returns timers that are now due."""
import datetime
import json
from pathlib import Path

TIMERS_FILE = Path(__file__).parent / "timers.json"


def pop_due() -> list[str]:
    """Announcements for due timers; removes them from the file."""
    try:
        timers = json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    now = datetime.datetime.now()
    due = [t for t in timers if datetime.datetime.fromisoformat(t["due"]) <= now]
    if not due:
        return []
    keep = [t for t in timers if t not in due]
    TIMERS_FILE.write_text(json.dumps(keep, indent=1), encoding="utf-8")
    return [
        f"Reminder: {t['label']}." if t.get("label") else "Your timer is up."
        for t in due
    ]
