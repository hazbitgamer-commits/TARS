"""Voice control of TARS's personality settings: set, adjust, list, remove.

Creating new settings by voice is disabled by the owner's request — the set of
settings only shrinks unless he asks Claude to add one deliberately.
"""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / "settings.json"

DESCRIPTION = ("Adjust TARS's personality settings (humor, sarcasm, honesty, verbosity, "
               "formality, enthusiasm): set a level, nudge it, read them out, or REMOVE "
               "a setting entirely. Does NOT create new settings.")
ARGS = {"action": "'set', 'adjust', 'list', or 'remove'",
        "name": "the setting name",
        "value": "0-100 for set; +N or -N for adjust (relative words like 'down a bit' = -15)"}


def _load() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _save(settings: dict) -> None:
    SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def run(args: dict) -> str:
    action = (args.get("action") or "list").strip().lower()
    settings = _load()

    if action == "list":
        if not settings:
            return "No personality settings left. I'm a blank slate."
        parts = [f"{n.replace('_', ' ')} {s['value']}" for n, s in settings.items()]
        return "Current settings: " + "; ".join(parts) + ". All out of one hundred."

    name = (args.get("name") or "").strip().lower().replace(" ", "_")
    if not name:
        return "Which setting?"

    if name not in settings:
        names = ", ".join(n.replace("_", " ") for n in settings) or "none"
        return f"There's no setting called {name.replace('_', ' ')}. I have: {names}."

    if action == "remove":
        del settings[name]
        _save(settings)
        return f"Removed {name.replace('_', ' ')}. It's gone for good."

    current = settings[name]["value"]
    raw = str(args.get("value", "")).strip().rstrip("%")
    if raw.startswith(("+", "-")) and raw[1:].isdigit():
        new = max(0, min(100, current + int(raw)))
    elif raw.isdigit():
        new = max(0, min(100, int(raw)))
    else:
        return f"{name.replace('_', ' ')} is at {current} percent."
    settings[name]["value"] = new
    _save(settings)
    return f"{name.replace('_', ' ')} set to {new} percent."
