import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("Open a live view of the desk webcam in its own TARS window — only "
               "when the owner explicitly says camera/webcam: 'show my camera feed', "
               "'open the camera'.")
ARGS = {}

_last_opened = 0.0


def run(args: dict) -> str:
    global _last_opened
    # The dashboard first, always. If one is open the camera simply appears
    # in it — no new window, nothing to close afterwards. His ask:
    # "EVERYTHING is on 1 tab when i ask for it."
    #
    # No cooldown on this path either. The ninety-second block below exists
    # because opening a whole window twice in a row is a mess; switching a
    # panel that is already showing costs nothing, and refusing to do it
    # just reads as TARS ignoring him.
    try:
        import dashboard

        if dashboard.dashboard_open():
            dashboard.show("camera")
            return "Camera's up on the dashboard."
    except Exception:
        pass

    if time.time() - _last_opened < 90:
        return ("The feed's already open. If you meant something else, say the "
                "whole request again without the word camera.")
    _last_opened = time.time()
    # no dashboard open — the fullscreen HUD on the second monitor, which is
    # still the nicer thing when he isn't looking at a dashboard at all
    try:
        import gestures

        if gestures.open_hud():
            return ("Camera's up on your second screen. Close that window to "
                    "switch it off, or say watch for signals for gestures.")
    except Exception:
        pass
    import tars_window

    tars_window.open_page("hud", 1100, 760)
    return "Camera feed's up. Close its window to switch it off."
