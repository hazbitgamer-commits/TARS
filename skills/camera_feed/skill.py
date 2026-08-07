import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("Open a live view of the desk webcam in its own TARS window — only "
               "when Jacob explicitly says camera/webcam: 'show my camera feed', "
               "'open the camera'.")
ARGS = {}

_last_opened = 0.0


def run(args: dict) -> str:
    global _last_opened
    if time.time() - _last_opened < 90:
        return ("The feed's already open. If you meant something else, say the "
                "whole request again without the word camera.")
    _last_opened = time.time()
    import tars_window

    tars_window.open_page("camera", 900, 700)
    return "Camera feed's up. Close its window to switch it off."
