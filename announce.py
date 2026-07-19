"""Shared announcement queue: background work posts here, main.py speaks them."""
import json
from pathlib import Path

FILE = Path(__file__).parent / "announcements.json"


def post(message: str, hold_during_quiet: bool = False) -> None:
    """hold_during_quiet: don't SPEAK it while quiet hours are on (Kipp's
    3am upgrade reports wait for morning); normal announcements are
    unchanged — timers still ring whenever they're due."""
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        items = []
    items.append({"text": message, "hold": True} if hold_during_quiet
                 else message)
    FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def pop() -> list[str]:
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not items:
        return []
    try:
        import quiet

        quiet_now = quiet.is_active()
    except Exception:
        quiet_now = False
    speak, held = [], []
    for item in items:
        if isinstance(item, dict):
            (held if quiet_now else speak).append(
                item if quiet_now else item["text"])
        else:
            speak.append(item)
    FILE.write_text(json.dumps(held, indent=1), encoding="utf-8")
    return speak
