"""Sleep timer: stop the music (or the PC) after a while, without being asked twice."""
import datetime
import json
import sys
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("SLEEP TIMER — do something to the PC after a delay: 'stop the music "
               "in 20 minutes', 'pause the music in half an hour', 'mute everything "
               "in 10 minutes', 'sleep the computer in an hour', 'cancel the sleep "
               "timer'. NOT a reminder that speaks to the owner (that's timers).")
ARGS = {"action": "'music' (pause playback), 'mute', 'sleep' (PC to sleep), "
                  "'lock', or 'cancel'",
        "minutes": "how many minutes from now"}

STATE = BASE / "sleep_timer.json"
_timer: threading.Timer | None = None


def _fire(action: str) -> None:
    STATE.unlink(missing_ok=True)
    try:
        from skills_engine import SkillBox

        skills = SkillBox(BASE)
        if action == "music":
            skills.run("media", {"action": "pause"})
        elif action == "mute":
            skills.run("volume", {"level": "mute"})
        elif action == "lock":
            skills.run("lock_pc", {})
        elif action == "sleep":
            import ctypes

            ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
    except Exception:
        pass


def run(args: dict) -> str:
    global _timer

    action = (args.get("action") or "music").strip().lower()
    raw = str(args.get("minutes", "") or "")
    digits = "".join(c for c in raw if c.isdigit())

    if action.startswith("cancel") or "cancel" in raw.lower():
        if _timer:
            _timer.cancel()
            _timer = None
        was = STATE.exists()
        STATE.unlink(missing_ok=True)
        return "Sleep timer cancelled." if was else "There's no sleep timer running."

    if "half" in raw.lower():
        minutes = 30
    elif "hour" in raw.lower() and not digits:
        minutes = 60
    else:
        minutes = int(digits) if digits else 20
    minutes = max(1, min(600, minutes))

    for word, name in (("music", "music"), ("song", "music"), ("mute", "mute"),
                       ("sleep", "sleep"), ("lock", "lock")):
        if word in action:
            action = name
            break
    if action not in ("music", "mute", "sleep", "lock"):
        action = "music"

    if _timer:
        _timer.cancel()
    _timer = threading.Timer(minutes * 60, _fire, args=(action,))
    _timer.daemon = True
    _timer.start()

    due = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
    STATE.write_text(json.dumps({"action": action, "due": due.isoformat()}, indent=1),
                     encoding="utf-8")
    what = {"music": "pause the music", "mute": "mute everything",
            "sleep": "put the PC to sleep", "lock": "lock the PC"}[action]
    warning = " Say cancel the sleep timer if you change your mind." \
        if action == "sleep" else ""
    return (f"Sleep timer set — I'll {what} in {minutes} minutes, "
            f"at {due.strftime('%I:%M %p').lstrip('0')}.{warning}")
