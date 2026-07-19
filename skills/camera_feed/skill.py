import time
import webbrowser

DESCRIPTION = ("Open a live view of the desk webcam in the browser — only when Jacob "
               "explicitly says camera/webcam: 'show my camera feed', 'open the camera'.")
ARGS = {}

_last_opened = 0.0


def run(args: dict) -> str:
    global _last_opened
    if time.time() - _last_opened < 90:
        return ("The feed's already open. If you meant something else, say the "
                "whole request again without the word camera.")
    _last_opened = time.time()
    webbrowser.open("http://127.0.0.1:8765/camera")
    return "Camera feed's up. Close the tab to switch it off."
