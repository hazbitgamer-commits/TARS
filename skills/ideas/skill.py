"""the owner's idea inbox — "TARS, idea: a shot-tracker overlay for Goal Mystro"
lands in ideas.json instead of evaporating, tagged to a project when one is
mentioned, and resurfaced on demand ("what were my ideas for Undergrid")."""
import datetime
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FILE = BASE / "ideas.json"
PROJECTS = ("tars", "goal mystro", "goal_mystro", "undergrid", "case",
            "hackquest", "chameleon", "rested", "solax", "solar", "vision",
            "fc26", "market tracker", "cad")

DESCRIPTION = ("the owner's IDEA INBOX — capture a passing idea ('idea: add a "
               "shot tracker to Goal Mystro', 'note down an idea for "
               "Undergrid'), hear them back ('what were my ideas', 'ideas "
               "for Undergrid'), or clear done ones ('drop the shot tracker "
               "idea'). NOT for to-do chores (lists) and NOT for durable "
               "facts about the owner (remember).")
ARGS = {"action": "'add' (default), 'list', or 'remove'",
        "idea": "the idea text",
        "project": "optional project it belongs to"}


def _load() -> list:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list) -> None:
    FILE.write_text(json.dumps(items, indent=1), encoding="utf-8")


def _guess_project(text: str) -> str:
    low = text.lower()
    for p in PROJECTS:
        if p in low:
            return p.replace("_", " ")
    return ""


def run(args: dict) -> str:
    action = str(args.get("action") or "add").strip().lower()
    idea = str(args.get("idea") or "").strip().rstrip(".")
    project = str(args.get("project") or "").strip() or _guess_project(idea)
    items = _load()

    if action in ("list", "read", "recall"):
        wanted = project.lower()
        hits = [i for i in items
                if not wanted or wanted in (i.get("project", "") + " "
                                            + i["idea"]).lower()]
        if not hits:
            return (f"No ideas saved for {project}." if project
                    else "Your idea inbox is empty.")
        recent = hits[-6:]
        lead = (f"{len(hits)} idea{'s' if len(hits) != 1 else ''}"
                + (f" for {project}" if project else "") + ": ")
        return lead + "; ".join(
            i["idea"] + (f" ({i['project']})" if i.get("project")
                         and not project else "") for i in recent) + "."

    if action in ("remove", "drop", "delete", "done"):
        match = next((i for i in reversed(items)
                      if idea.lower() in i["idea"].lower()), None)
        if not match:
            return f"I don't have an idea like {idea}."
        items.remove(match)
        _save(items)
        return f"Dropped it. {len(items)} left in the inbox."

    if not idea:
        return "What's the idea?"
    items.append({"idea": idea, "project": project,
                  "day": datetime.date.today().isoformat()})
    _save(items)
    return (f"Saved{' under ' + project if project else ''} — "
            f"{len(items)} idea{'s' if len(items) != 1 else ''} banked.")
