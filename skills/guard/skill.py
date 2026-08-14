"""Watch the room and text him who comes in.

Arming is explicit consent for the camera — TARS's standing rule is that it
only opens on camera words, and this skill is the one place that rule is
satisfied for an ongoing watch rather than a single look.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("GUARD THE ROOM with the webcam: watch for anyone coming in "
               "and text him a photo, with their name if it's a face I know. "
               "E.g. 'guard my room', 'watch my room while I'm out', 'keep "
               "an eye on my room', 'stand down' / 'stop guarding' to stop, "
               "'is the guard on'. NOT a single look at the camera (that's "
               "camera) and NOT a live view on screen (that's camera_feed).")
ARGS = {"action": "'on' to start watching, 'off' to stop, 'status' to check"}

_ON = ("on", "arm", "start", "guard", "watch", "yes", "enable")
_OFF = ("off", "disarm", "stop", "stand down", "cancel", "disable", "no")


def run(args: dict) -> str:
    import guard

    action = str(args.get("action") or "on").strip().lower()

    if any(w in action for w in _OFF):
        return guard.disarm()
    if "status" in action or "is the guard" in action:
        return guard.status()
    if any(w in action for w in _ON) or not action:
        try:
            import tars_phone

            if not tars_phone.paired():
                return ("I can watch the room, but your phone isn't paired to "
                        "me yet — so I'd have no way to tell you. Set up the "
                        "Telegram bridge first.")
        except Exception:
            pass
        return guard.arm()
    return guard.status()
