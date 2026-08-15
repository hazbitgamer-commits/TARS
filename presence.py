"""Noticing whether he's actually there.

Locks the PC when he walks off, welcomes him back by name, pauses whatever
was playing and starts it again when he sits down, and says who came in
while he was gone.

TWO RULES THIS OBEYS, both of them his:

1. The camera only ever opens when he says so. There is a standing rule that
   the webcam turns on for explicit camera words and nothing else, and a
   feature that quietly holds the camera open all day would drive straight
   through it. So this is ARMED, like the room guard: it does nothing at all
   until he says "watch for me", and "stop watching" ends it. Off is the
   default and survives a restart.

2. It locks, and it never unlocks. Locking a machine is a thing anyone can
   do; unlocking one is defeating the lock, and no assistant should hold
   that. When he comes back he types his own password, and TARS says hello
   afterwards.

The recognising is the part that was rebuilt to cope with him lying on his
bed with his head on its side, so "away" means genuinely away rather than
"at an angle the recogniser gave up on".
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "presence_state.json"

LOOK_EVERY = 6.0         # seconds between glances
AWAY_AFTER = 90.0        # gone this long before it counts as away
BACK_AFTER = 2           # this many sightings in a row before "he's back"
LOCK_AFTER = 300.0       # away this long before the screen is locked
STRANGER_GAP = 600.0     # don't mention the same unknown face more than this

_state = {"on": False, "lock": True, "pause": True, "greet": True}
_seen = {"him": 0.0, "sightings": 0, "away_since": 0.0, "locked": False,
         "stranger": 0.0, "who": []}


def _load() -> None:
    try:
        _state.update(json.loads(STATE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass


def _save() -> None:
    try:
        STATE.write_text(json.dumps(_state, indent=1), encoding="utf-8")
    except OSError:
        pass


def _owner_name() -> str:
    try:
        import profile

        return (profile.get("name") or "").strip()
    except Exception:
        return ""


def lock_screen() -> bool:
    """Lock, and only lock. There is deliberately no unlock in this file."""
    try:
        if sys.platform == "win32":
            import ctypes

            return bool(ctypes.windll.user32.LockWorkStation())
        if sys.platform == "darwin":
            subprocess.run(["pmset", "displaysleepnow"], timeout=5)
            return True
    except Exception:
        pass
    return False


def _media(action: str) -> None:
    """Tap the play/pause key — the same key on the keyboard, nothing more."""
    try:
        if sys.platform == "win32":
            import ctypes

            VK_PLAY_PAUSE = 0xB3
            ctypes.windll.user32.keybd_event(VK_PLAY_PAUSE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_PLAY_PAUSE, 0, 2, 0)
    except Exception:
        pass


def _say(line: str) -> None:
    try:
        import announce

        announce.post(line, hold_during_quiet=True)
    except Exception:
        pass


def _look() -> tuple:
    """(is he there, other names seen). Camera only — no other sensor."""
    try:
        import faces

        frame = faces.get_frame()
        if frame is None:
            return None, []
        found = faces.identify(frame, wait=False)
        me = _owner_name().lower()
        names = [f.get("name") for f in found if f.get("name")]
        return (any((n or "").lower() == me for n in names) if me
                else bool(names)), [n for n in names
                                    if (n or "").lower() != me]
    except Exception:
        return None, []


def _watch() -> None:
    was_playing = False
    while True:
        time.sleep(LOOK_EVERY)
        if not _state.get("on"):
            continue
        try:
            here, others = _look()
            now = time.time()

            if here:
                _seen["sightings"] += 1
                gone_for = now - _seen["him"] if _seen["him"] else 0
                _seen["him"] = now
                _seen["away_since"] = 0.0
                if (_seen["sightings"] >= BACK_AFTER and gone_for > AWAY_AFTER):
                    name = _owner_name() or "you"
                    if _state.get("greet"):
                        line = f"Welcome back, {name}."
                        if _seen["who"]:
                            line += (" While you were gone I saw "
                                     + ", ".join(sorted(set(_seen["who"]))) + ".")
                        _say(line)
                    _seen["who"] = []
                    if _state.get("pause") and was_playing:
                        _media("play")
                        was_playing = False
                    _seen["locked"] = False
            else:
                _seen["sightings"] = 0
                if not _seen["away_since"]:
                    _seen["away_since"] = now
                away_for = now - _seen["away_since"]
                if away_for > AWAY_AFTER and not was_playing and _state.get("pause"):
                    _media("pause")
                    was_playing = True
                if (away_for > LOCK_AFTER and not _seen["locked"]
                        and _state.get("lock")):
                    _seen["locked"] = lock_screen()

            for other in others:
                _seen["who"].append(other)
                if now - _seen["stranger"] > STRANGER_GAP and not here:
                    _seen["stranger"] = now
                    _say(f"{other} just came into the room.")
        except Exception:
            pass          # a camera hiccup must never end the watch


def armed() -> bool:
    """Is the camera actually watching right now? Asked by the bare
    'stop watching' handler, which has to turn off every camera and not
    just the one it was written for."""
    _load()
    return bool(_state.get("on"))


def turn(on: bool) -> str:
    _load()
    _state["on"] = on
    _save()
    if on:
        _seen.update(him=time.time(), sightings=0, away_since=0.0,
                     locked=False, who=[])
        return ("Watching for you now — the camera's on until you say stop "
                "watching. I'll pause things when you go, lock the screen if "
                "you're gone five minutes, and say hello when you're back. "
                "I can't unlock it though — you'll type your own password.")
    return "Stopped watching — camera's off."


def settings(lock=None, pause=None, greet=None) -> str:
    _load()
    for key, value in (("lock", lock), ("pause", pause), ("greet", greet)):
        if value is not None:
            _state[key] = bool(value)
    _save()
    return status()


def status() -> str:
    _load()
    if not _state.get("on"):
        return ("I'm not watching for you — the camera stays off until you "
                "say 'watch for me'.")
    bits = [name for name, on in (("lock the screen", _state.get("lock")),
                                  ("pause what's playing", _state.get("pause")),
                                  ("say hello", _state.get("greet"))) if on]
    ago = int(time.time() - _seen["him"]) if _seen["him"] else None
    where = ("I can see you now" if ago is not None and ago < AWAY_AFTER
             else f"last saw you {ago // 60} minutes ago" if ago
             else "haven't spotted you yet")
    return f"Watching for you — {where}. I'll " + ", ".join(bits) + "."


def start() -> None:
    """Started every boot, but it watches NOTHING until he arms it."""
    _load()
    threading.Thread(target=_watch, daemon=True).start()
