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


BREAKS_FILE = Path(__file__).parent / "breaks.json"
BREAK_LINES = [
    "Break time — look at something twenty metres away for twenty seconds.",
    "That's a while at the screen. Stand up, roll your shoulders back.",
    "Eyes off the monitor for a moment — long look out the window.",
    "Time to stretch your legs and get some water.",
]


def _breaks_due(now: datetime.datetime) -> list[str]:
    """Gentle nudges to rest. Silent at night and while a game is fullscreen."""
    try:
        state = json.loads(BREAKS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not state.get("on"):
        return []
    every = float(state.get("every", 45))
    try:
        last = datetime.datetime.fromisoformat(state["last"])
    except (KeyError, ValueError):
        last = now
    if (now - last).total_seconds() < every * 60:
        return []

    try:  # never interrupt the night
        import quiet

        if quiet.is_active()[0]:
            return []
    except Exception:
        pass
    try:  # nor a match in progress — the reminder can wait for the lobby
        import game_watch

        if getattr(game_watch, "in_game", lambda: False)():
            return []
    except Exception:
        pass

    state["last"] = now.isoformat()
    state["count"] = int(state.get("count", 0)) + 1
    try:
        BREAKS_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        return []
    return [BREAK_LINES[(state["count"] - 1) % len(BREAK_LINES)]]


def pop_due() -> list[str]:
    """Announcements for due timers; removes them from the file."""
    now = datetime.datetime.now()
    out = _recurring_due(now) + _breaks_due(now)
    try:
        timers = json.loads(TIMERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return out
    due = [t for t in timers if datetime.datetime.fromisoformat(t["due"]) <= now]
    if due:
        # leave a note of what just went off, so "snooze" knows what to re-arm
        try:
            (Path(__file__).parent / "last_fired.json").write_text(
                json.dumps({"label": due[-1].get("label", ""),
                            "at": now.isoformat()}), encoding="utf-8")
        except OSError:
            pass
        keep = [t for t in timers if t not in due]
        TIMERS_FILE.write_text(json.dumps(keep, indent=1), encoding="utf-8")
        out += [
            f"Reminder: {t['label']}." if t.get("label") else "Your timer is up."
            for t in due
        ]
    return out
