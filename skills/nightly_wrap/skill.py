"""The goodnight wrap-up: quick recap of today + tomorrow's calendar +
anything left on the to-do list. main.py speaks it when the owner says
goodnight, right before sleep mode."""
import datetime
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("The GOODNIGHT wrap-up — a short spoken end-of-day summary: "
               "what happened today, what's on tomorrow's calendar, and "
               "anything still on the to-do list. E.g. 'goodnight report', "
               "'wrap up my day'. Saying 'goodnight TARS' runs this and "
               "then sleeps automatically.")
ARGS = {}


def run(args: dict) -> str:
    from skills_engine import SkillBox

    sb = SkillBox(BASE)
    parts = []

    today = datetime.date.today()
    journal = BASE / "vault" / "Journal" / f"Journal {today.isoformat()}.md"
    if journal.exists():
        n = sum(1 for l in journal.read_text(encoding="utf-8").splitlines()
                if l.strip().startswith("-"))
        if n:
            parts.append(f"We got through {n} things together today")

    try:
        agenda = sb.run("calendar", {"action": "agenda", "when": "tomorrow"})
        if agenda and "isn't connected" not in agenda:
            if "nothing" in agenda.lower() or "clear" in agenda.lower():
                parts.append("tomorrow's calendar is clear")
            else:
                parts.append("tomorrow: " + agenda.rstrip("."))
    except Exception:
        pass

    try:
        todo = json.loads((BASE / "lists.json").read_text(encoding="utf-8")
                          ).get("todo", [])
        if todo:
            parts.append(f"and {len(todo)} thing"
                         f"{'s' if len(todo) != 1 else ''} still on the "
                         f"to-do list — {todo[0]}"
                         + (" among them" if len(todo) > 1 else ""))
    except (OSError, json.JSONDecodeError):
        pass

    if not parts:
        return "Quiet day, clear tomorrow. Sleep well, the owner."
    return ". ".join(p[0].upper() + p[1:] for p in parts) + ". Sleep well, the owner."
