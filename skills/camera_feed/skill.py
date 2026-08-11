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
    if time.time() - _last_opened < 90:
        return ("The feed's already open. If you meant something else, say the "
                "whole request again without the word camera.")
    _last_opened = time.time()
    # the HUD, not the old bare feed page: ring, speaking cue and the
    # gesture legend, fullscreen on the second monitor
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
