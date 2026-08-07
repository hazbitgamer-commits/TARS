"""Reports what new skill(s) TARS has most recently taught himself — the real,
finished output of the self-teaching pipeline (each skills/<name>/skill.py
file, sorted by when it was written).

This is deliberately different from two existing skills:
  - improve (Kipp): Kipp's own queue of PROPOSED upgrades to TARS's existing
    core code — plans, not finished skills.
  - how_i_learn: explains the general PROCESS TARS uses to learn, not what
    has actually been learned lately.
This skill just reports the concrete, already-taught skills themselves —
the same data shown on the dashboard's "Learning" card.
"""
import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent

DESCRIPTION = ("Report what new skill or ability TARS is CURRENTLY learning / has "
               "most recently taught himself — actual finished skills, newest "
               "first. E.g. 'what are you currently learning', 'what's the newest "
               "skill you've taught yourself', 'what have you learned lately'. NOT "
               "Kipp's queue of planned upgrades to existing code (that's the "
               "improve skill) and NOT an explanation of how the learning process "
               "works (that's how_i_learn).")
ARGS = {"count": "how many recently learned skills to mention, default 1"}


def _recent(limit: int) -> list[dict]:
    from skills_engine import SkillBox

    catalog = {c["skill"]: c for c in SkillBox(BASE).catalog()}
    rows = []
    for name, info in catalog.items():
        py = BASE / "skills" / name / "skill.py"
        try:
            mtime = py.stat().st_mtime
        except OSError:
            continue
        rows.append({"name": name, "desc": info["description"], "mtime": mtime})
    rows.sort(key=lambda r: -r["mtime"])
    return rows[:limit]


def run(args: dict) -> str:
    try:
        count = max(1, min(5, int(args.get("count", 1))))
    except (TypeError, ValueError):
        count = 1

    recent = _recent(count)
    if not recent:
        return "I can't find any skills on record — that shouldn't happen."

    newest = recent[0]
    when = datetime.date.fromtimestamp(newest["mtime"]).strftime("%d %B")
    sentence = f"The newest skill I taught myself is '{newest['name']}', learned on {when}."

    if len(recent) == 1:
        return sentence

    others = ", ".join(r["name"] for r in recent[1:])
    return f"{sentence} Before that: {others}."
