"""Shared quiet-hours check — any skill that makes noise in the house asks
this before acting. Schedule lives in quiet_hours.json (quiet_hours skill)."""
import datetime
import json
from pathlib import Path

FILE = Path(__file__).parent / "quiet_hours.json"


def is_active() -> tuple[bool, str]:
    """(active?, human-readable schedule) — inactive if no schedule set."""
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        start = datetime.time.fromisoformat(data["start"])
        end = datetime.time.fromisoformat(data["end"])
    except Exception:
        return False, ""
    now = datetime.datetime.now().time()
    active = (start <= now < end) if start <= end else (now >= start or now < end)
    span = (f"{start.strftime('%I %p').lstrip('0')} to "
            f"{end.strftime('%I %p').lstrip('0')}")
    return active, span
