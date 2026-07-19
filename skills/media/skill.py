import pyautogui

DESCRIPTION = "Control music/video playback: play, pause, next track, previous track."
ARGS = {"action": "play, pause, next, or previous"}

KEYS = {
    "play": "playpause",
    "pause": "playpause",
    "toggle": "playpause",
    "next": "nexttrack",
    "skip": "nexttrack",
    "previous": "prevtrack",
    "back": "prevtrack",
}


def run(args: dict) -> str:
    action = (args.get("action") or "toggle").strip().lower()
    key = KEYS.get(action)
    if not key:
        return f"I don't know the playback action {action}."
    pyautogui.press(key)
    return "Done."
