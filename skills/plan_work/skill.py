"""When to START school work, not just when it's due.

The school skill reads out a list of due dates. This turns that list into a
plan: what to do tonight, what to leave, and when to begin the big ones.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("PLAN school work — what to do TONIGHT and WHEN TO START "
               "things, worked backwards from the due dates. E.g. 'what "
               "should I work on', 'what should I do tonight', 'plan my "
               "week', 'when should I start the history test', 'am I behind'. "
               "NOT for simply listing what's due (that's school) and NOT "
               "for revision content or notes (that's revision/study).")
ARGS = {"action": "'today' for tonight (default), 'week' for the fortnight, "
                  "or 'when' with a named assessment",
        "what": "for 'when' — which assessment he's asking about"}


def run(args: dict) -> str:
    import planner

    action = str(args.get("action") or "today").strip().lower()
    what = str(args.get("what") or "").strip()

    try:
        if what or action in ("when", "start"):
            return planner.when_to_start(what or action)
        if action in ("week", "fortnight", "plan", "schedule"):
            return planner.week_plan()
        return planner.today_plan()
    except Exception as e:
        return f"I couldn't work out a plan ({type(e).__name__})."
