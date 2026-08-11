"""Routines — one phrase, several actions. "Movie night" dips the lights
of the house TARS can reach, silences his announcements, parks the vacuum
and sets the scene; "work mode" and "bedtime" likewise.

Routines live in routines.json so the owner can invent his own by voice:
"make a routine called gaming that mutes announcements and pauses Basel".
Each step is just a skill call, so anything TARS can do, a routine can do.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
FILE = BASE / "routines.json"

DESCRIPTION = ("ROUTINES — one phrase that does several things: 'movie "
               "night', 'work mode', 'bedtime', 'good morning'. Also "
               "'what routines do I have', 'add X to movie night', or "
               "'make a routine called gaming'. NOT for single commands "
               "and NOT for the goodnight wrap-up (nightly_wrap).")
ARGS = {"name": "which routine to run, or 'list'",
        "action": "'run' (default), 'list', 'create', 'add'",
        "steps": "for create/add: what it should do, in the owner's words"}

# sensible starters, all built from skills TARS already has
DEFAULTS = {
    "movie night": {
        # say ONLY what the steps actually do — the first draft promised
        # "lights down" and the owner has no smart lights
        "say": "Movie night. Kitchen speaker down, Basel parked, quiet hours on.",
        "steps": [["speakers", {"action": "volume", "room": "kitchen",
                                "level": "20"}],
                  ["vacuum", {"action": "dock"}],
                  ["quiet_hours", {"action": "on"}]],
    },
    "work mode": {
        "say": "Work mode. Announcements muted, timer running, desk clear.",
        "steps": [["quiet_hours", {"action": "on"}],
                  ["timers", {"action": "set", "when": "50 minutes",
                              "label": "stretch break"}],
                  ["manage_window", {"action": "minimize_all"}]],
    },
    "bedtime": {
        "say": "Night then.",
        "steps": [["nightly_wrap", {}],
                  ["vacuum", {"action": "dock"}],
                  ["quiet_hours", {"action": "on"}]],
    },
    "good morning": {
        "say": "Morning, the owner.",
        "steps": [["agents", {"action": "briefing"}],
                  ["quiet_hours", {"action": "off"}]],
    },
}


def _load() -> dict:
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    merged = dict(DEFAULTS)
    merged.update(saved)          # the owner's edits win over the starters
    return merged


def _save(data: dict) -> None:
    FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _compose(wanted: str) -> list:
    """Turn 'mute announcements and park Basel' into real skill calls, so
    the owner can invent routines by voice without anyone wiring them by hand."""
    import requests

    from skills_engine import SkillBox

    # WHITELIST, not a blocklist: a routine fires unattended, so it may only
    # use safe, reversible skills. (The composer's first attempt tried to
    # put "sudo systemctl stop vacuum_service" in a routine via run_command.)
    SAFE = {"vacuum", "vacuum_room", "vacuum_speed", "quiet_hours", "timers",
            "recurring", "volume", "music", "media", "lists", "speakers",
            "manage_window", "open_app", "weather", "agents", "nightly_wrap",
            "voice_output", "brightness", "day_recap", "lock_pc", "improve",
            "guest_mode", "solar", "pc_health", "notes_box", "cad",
            "open_dashboard", "open_brain", "screen_watch", "work_queue"}
    catalog = [{"skill": s["skill"], "args": s["args"]}
               for s in SkillBox(BASE).catalog() if s["skill"] in SAFE]
    try:
        r = requests.post("http://127.0.0.1:11434/api/chat", json={
            "model": "qwen2.5:7b", "stream": False, "format": "json",
            "keep_alive": "2h",
            "messages": [{"role": "user", "content":
                "TARS's skills and their arguments:\n"
                + json.dumps(catalog)[:9000]
                + f"\n\nThe owner wants a routine that: {wanted!r}\n"
                'Reply JSON: {"steps": [{"skill": "<exact skill name>", '
                '"args": {...}}, ...]} — only skills from the list, real '
                "argument names, 1 to 5 steps, nothing that spends money or "
                "sends messages. Empty list if nothing fits."}],
            "options": {"temperature": 0}}, timeout=120)
        r.raise_for_status()
        proposed = json.loads(r.json()["message"]["content"]).get("steps", [])
    except Exception:
        return []
    allowed_args = {s["skill"]: set(s["args"]) for s in catalog}
    steps = []
    for p in proposed[:5]:
        if not isinstance(p, dict) or p.get("skill") not in allowed_args:
            continue  # invented or unsafe skill — drop it silently
        args = {k: v for k, v in (p.get("args") or {}).items()
                if k in allowed_args[p["skill"]]}  # drop invented arguments
        steps.append([p["skill"], args])
    return steps


def _match(name: str, routines: dict) -> str | None:
    import difflib

    name = name.strip().lower()
    if name in routines:
        return name
    for key in routines:
        if key in name or name in key:
            return key
    close = difflib.get_close_matches(name, list(routines), n=1, cutoff=0.6)
    return close[0] if close else None


def run(args: dict) -> str:
    from skills_engine import SkillBox

    action = str(args.get("action") or "run").strip().lower()
    name = str(args.get("name") or "").strip().lower()
    routines = _load()

    if action == "list" or name in ("list", ""):
        return ("Your routines: " + ", ".join(routines)
                + ". Say one of them, or 'make a routine called ...'.")

    if action in ("schedule", "trigger", "when"):
        key = _match(name, routines)
        if key is None:
            return f"I don't have a routine called {name}."
        raw = str(args.get("steps") or "").lower()
        import re

        entry = dict(routines[key])
        m = re.search(r"(\d{1,2})[:. ]?(\d{2})?\s*(am|pm)?", raw)
        if "game" in raw or "gaming" in raw:
            entry["when"] = {"type": "game"}
            spoken = "whenever you start a game"
        elif m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            if m.group(3) == "pm" and hh < 12:
                hh += 12
            if m.group(3) == "am" and hh == 12:
                hh = 0
            entry["when"] = {"type": "time", "at": f"{hh:02d}:{mm:02d}"}
            spoken = f"every day at {hh:02d}:{mm:02d}"
        elif "never" in raw or "stop" in raw or "off" in raw:
            entry.pop("when", None)
            spoken = "only when you say it"
        else:
            return ("When should it run? A time like 'ten thirty pm', or "
                    "'when I start a game'.")
        routines[key] = entry
        _save({k: v for k, v in routines.items()
               if k not in DEFAULTS or v != DEFAULTS.get(k)})
        return f"Done — {key} runs {spoken}."

    if action in ("create", "add", "edit"):
        steps_text = str(args.get("steps") or "").strip()
        if not name:
            return "What should the routine be called?"
        key = _match(name, routines) or name
        entry = routines.get(key, {"say": f"{key.title()}.", "steps": []})
        new_steps = _compose(steps_text) if steps_text else []
        entry["steps"] = entry.get("steps", []) + new_steps
        routines[key] = entry
        _save({k: v for k, v in routines.items()
               if k not in DEFAULTS or v != DEFAULTS.get(k)})
        if not new_steps:
            return (f"I've made a routine called {key}, but I couldn't work "
                    f"out the steps from that — try naming the actions, like "
                    f"'park the vacuum and mute announcements'.")
        return (f"Done — saying {key} will now "
                + " and ".join(s[0].replace('_', ' ') for s in new_steps)
                + ".")

    key = _match(name, routines)
    if key is None:
        return (f"I don't have a routine called {name}. Say 'what routines "
                f"do I have'.")
    sb = SkillBox(BASE)
    done, failed = [], []
    for skill, params in routines[key].get("steps", []):
        try:
            result = sb.run(skill, dict(params))
            (done if result else failed).append(skill)
        except Exception:
            failed.append(skill)
    spoken = routines[key].get("say", f"{key.title()} done.")
    if failed:
        spoken += f" ({len(failed)} step{'s' if len(failed) != 1 else ''} "
        spoken += f"didn't work: {', '.join(failed)}.)"
    return spoken
