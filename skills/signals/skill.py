"""Hand signals — start and stop TARS watching the webcam for gestures.

Watching is ON DEMAND by the owner's explicit choice: the camera opens when he
asks and closes when he says so or the timer runs out. Nothing here ever
starts the camera on its own.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

DESCRIPTION = ("HAND SIGNALS through the webcam — 'watch for signals', "
               "'watch for hand signals', 'stop watching', 'are you "
               "watching for signals'. While watching: palm up stops TARS "
               "talking, thumbs up means yes, thumbs down means no. NOT for "
               "taking a photo or asking what's visible (camera) and NOT "
               "for the live feed window (camera_feed).")
ARGS = {"action": "'start' (default), 'stop', or 'status'",
        "minutes": "how long to watch, default 10"}


def run(args: dict) -> str:
    import gestures

    action = str(args.get("action") or "start").strip().lower()
    if action in ("stop", "off", "end", "quit"):
        return gestures.stop()
    if action in ("status", "check"):
        return gestures.status()
    try:
        minutes = float(str(args.get("minutes") or 10).strip() or 10)
    except ValueError:
        minutes = 10
    return gestures.start(max(1, min(60, minutes)))
