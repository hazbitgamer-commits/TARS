"""Real to-do and shopping lists by voice — TARS once bluffed having a
to-do list; now he actually does. Stored in lists.json, spoken on demand."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FILE = BASE / "lists.json"

DESCRIPTION = ("Jacob's voice LISTS — shopping list and to-do list. Add "
               "items ('add milk to the shopping list', 'put mow the lawn "
               "on my to-do list'), read a list ('what's on my shopping "
               "list'), remove items ('take milk off the list'), or clear "
               "one ('clear the shopping list'). NOT for timers or "
               "one-off reminders — those are the timers skill.")
ARGS = {"action": "'add', 'read', 'remove', or 'clear'",
        "list": "'shopping' or 'todo' (default: todo)",
        "item": "the item to add or remove"}


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _name(which: str) -> str:
    return "shopping" if "shop" in which.lower() else "todo"


def _spoken(which: str) -> str:
    return "shopping list" if which == "shopping" else "to-do list"


def run(args: dict) -> str:
    action = str(args.get("action", "read")).strip().lower()
    which = _name(str(args.get("list", "todo")))
    item = str(args.get("item", "")).strip().rstrip(".")
    data = _load()
    items = data.get(which, [])

    if action == "add":
        if not item:
            return "Add what, exactly?"
        if item.lower() in (i.lower() for i in items):
            return f"{item} is already on the {_spoken(which)}."
        items.append(item)
        data[which] = items
        _save(data)
        return f"Added {item}. The {_spoken(which)} has {len(items)} " \
               f"item{'s' if len(items) != 1 else ''}."
    if action == "remove":
        match = next((i for i in items if item.lower() in i.lower()), None)
        if not match:
            return f"I don't see {item} on the {_spoken(which)}."
        items.remove(match)
        data[which] = items
        _save(data)
        return f"Took {match} off. {len(items)} left."
    if action == "clear":
        data[which] = []
        _save(data)
        return f"The {_spoken(which)} is now empty."
    if not items:
        return f"The {_spoken(which)} is empty."
    return f"The {_spoken(which)}: " + ", ".join(items) + "."
