"""Break reminders — eyes and back, on a timer, without being a nag."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("BREAK REMINDERS for long sessions at the screen — 'remind me to take "
               "breaks', 'break reminders every 45 minutes', 'nudge me to rest my "
               "eyes', 'stop reminding me to take breaks', 'when's my next break'. "
               "ANY request about taking breaks, resting eyes or standing up on a "
               "schedule belongs here, even when it is phrased as 'remind me to...' "
               "— it is an ongoing habit, not one reminder. NOT for reminders about "
               "a specific errand or a one-off time (those are timers).")
ARGS = {"action": "'on', 'off', or 'status'",
        "minutes": "how often to nudge, in minutes (default 45)"}

STATE = BASE / "breaks.json"


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"on": False, "every": 45, "last": None}


def run(args: dict) -> str:
    import datetime

    state = _load()
    action = (args.get("action") or "").strip().lower()
    raw = str(args.get("minutes", "") or "")
    digits = "".join(c for c in raw if c.isdigit())

    if action.startswith(("off", "stop", "disable", "cancel")):
        state["on"] = False
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
        return "Break reminders off. I'll leave you to it."

    if action.startswith(("status", "next", "when")) and not digits:
        if not state.get("on"):
            return "Break reminders are off. Say remind me to take breaks to turn them on."
        left = ""
        if state.get("last"):
            try:
                gone = (datetime.datetime.now()
                        - datetime.datetime.fromisoformat(state["last"])).total_seconds()
                left = f" Next one in about {max(1, round(state['every'] - gone / 60))} minutes."
            except ValueError:
                pass
        return f"Break reminders are on, every {state['every']} minutes.{left}"

    state["every"] = max(10, min(180, int(digits))) if digits else state.get("every", 45)
    state["on"] = True
    state["last"] = datetime.datetime.now().isoformat()
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return (f"Break reminders on — I'll nudge you every {state['every']} minutes, "
            "and stay quiet during quiet hours or while you're mid-game.")
