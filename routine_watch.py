"""Routines that fire themselves.

A routine can carry a trigger: a clock time ("bedtime at 22:30"), or a
context event — a game starting (game_watch), or Jacob going idle. Ticked
about once a second from main's standby loop; the real checks run once a
minute. Announcements say WHICH routine fired, so nothing happens to the
house without TARS saying so.
"""
import datetime
import json
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILE = BASE / "routines.json"
STATE = BASE / "routine_state.json"
_last = 0.0


def _routines() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _fire(name: str, why: str) -> None:
    def worker():
        try:
            import announce
            from skills_engine import SkillBox

            said = SkillBox(BASE).run("routines", {"name": name,
                                                   "action": "run"})
            announce.post(f"{why} — running your {name} routine. {said}",
                          hold_during_quiet=True)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def _check() -> None:
    now = datetime.datetime.now()
    today = now.date().isoformat()
    state = _state()
    fired = state.setdefault("fired", {})
    changed = False

    for name, entry in _routines().items():
        trigger = (entry or {}).get("when") or {}
        kind = str(trigger.get("type", ""))
        key = f"{name}:{today}"
        if fired.get(key):
            continue
        if kind == "time":
            try:
                hh, mm = (int(x) for x in str(trigger["at"]).split(":"))
            except (KeyError, ValueError):
                continue
            if (now.hour, now.minute) >= (hh, mm):
                fired[key] = True
                changed = True
                _fire(name, f"It's {trigger['at']}")
        elif kind == "game":
            try:
                import game_watch

                if game_watch.in_session():
                    fired[key] = True
                    changed = True
                    _fire(name, "You've started a game")
            except Exception:
                continue
    if changed:
        state["fired"] = {k: v for k, v in fired.items()
                          if k.endswith(today)}  # forget yesterday's
        _save(state)


def tick() -> None:
    global _last
    if time.time() - _last < 60:
        return
    _last = time.time()
    try:
        _check()
    except Exception:
        pass
