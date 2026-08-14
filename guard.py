"""Watching his room while he isn't in it, and texting him who walked in.

Only ever runs when he has ARMED it. TARS's standing rule is that the
camera opens on explicit camera words and nothing else, and a watcher that
could start itself would drive straight through that. Arming is the explicit
consent; disarming is one word; and it announces both, so the camera can
never be quietly recording without him having said so.

What he gets: a Telegram photo, and a name if it recognises the face —
"Dad walked in" rather than "motion detected", because a motion alert from
your own bedroom is noise and a name is information.

Deliberately not built:
  - no continuous recording. It grabs a frame when something changes and
    keeps nothing else.
  - no storage of strangers' faces. An unrecognised person is reported as
    unrecognised; it doesn't enrol anyone behind his back.
  - it never arms itself, not on a schedule, not when he leaves.
"""
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
SHOTS = BASE / "workshop" / "guard"

CHECK_EVERY = 3.0        # seconds between looks
SETTLE = 45              # after an alert, stay quiet this long about the same person
MOTION_PIXELS = 0.012    # fraction of the frame that must change to look closer

_state = {"armed": False, "since": 0.0, "last": {}, "thread": None,
          "seen": 0, "alerts": 0}
_lock = threading.Lock()


def armed() -> bool:
    return bool(_state["armed"])


def status() -> str:
    if not armed():
        return "Guard's off. Say 'guard my room' and I'll watch it."
    mins = int((time.time() - _state["since"]) / 60)
    return (f"Guard's on — {mins} minute{'s' if mins != 1 else ''} so far, "
            f"{_state['alerts']} alert{'s' if _state['alerts'] != 1 else ''}.")


def _notify(text: str, image_path: Path | None) -> None:
    try:
        import tars_phone

        if not tars_phone.paired():
            return
        if image_path and image_path.exists():
            if tars_phone.send_photo(image_path, text):
                return
        tars_phone.send(text, force=True)
    except Exception:
        pass


def _describe(people: list) -> str:
    """Who's there, in words. Names when it knows them, honest when it
    doesn't — never a guess dressed up as a name."""
    named = [p["name"] for p in people if p.get("name")]
    unknown = len([p for p in people if not p.get("name")])
    bits = []
    if named:
        bits.append(", ".join(sorted(set(named))))
    if unknown:
        bits.append(f"{unknown} person I don't recognise"
                    if unknown == 1 else
                    f"{unknown} people I don't recognise")
    return " and ".join(bits) if bits else "someone"


def _should_tell(who: str) -> bool:
    """One alert per person per settle window — a person standing in the
    room is not news forty times a minute."""
    now = time.time()
    last = _state["last"].get(who, 0)
    if now - last < SETTLE:
        return False
    _state["last"][who] = now
    return True


def _watch() -> None:
    import cv2
    import numpy as np

    import faces

    previous = None
    SHOTS.mkdir(parents=True, exist_ok=True)
    while _state["armed"]:
        time.sleep(CHECK_EVERY)
        try:
            frame = faces.get_frame()
            if frame is None:
                continue
            small = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
            if previous is None:
                previous = small
                continue
            changed = float(np.mean(cv2.absdiff(previous, small) > 25))
            previous = small
            if changed < MOTION_PIXELS:
                continue

            # something moved — now look properly, which is the expensive bit
            people = faces.identify(frame, wait=False)
            if not people:
                continue
            _state["seen"] += 1
            who = _describe(people)
            if not _should_tell(who):
                continue

            shot = SHOTS / f"guard-{int(time.time())}.jpg"
            try:
                cv2.imwrite(str(shot), frame)
            except Exception:
                shot = None
            stamp = time.strftime("%H:%M")
            _state["alerts"] += 1
            _notify(f"{who} in your room — {stamp}.", shot)
        except Exception:
            time.sleep(5)      # a wobble must not kill the watch


def arm() -> str:
    with _lock:
        if _state["armed"]:
            return status()
        _state.update({"armed": True, "since": time.time(), "last": {},
                       "seen": 0, "alerts": 0})
        thread = threading.Thread(target=_watch, daemon=True)
        _state["thread"] = thread
        thread.start()
    try:
        import faces

        threading.Thread(target=faces.warmup, daemon=True).start()
    except Exception:
        pass
    return ("Guard's on. I'm watching the room and I'll text you a photo if "
            "anyone comes in. Say 'stand down' to stop.")


def disarm() -> str:
    with _lock:
        if not _state["armed"]:
            return "Guard was already off."
        _state["armed"] = False
        alerts = _state["alerts"]
    return (f"Guard's off. {alerts} alert{'s' if alerts != 1 else ''} while "
            f"I was watching.")
