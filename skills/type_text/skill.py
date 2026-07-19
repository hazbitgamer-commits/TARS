import time

import pyautogui

DESCRIPTION = "Type text into whatever window is focused right now. E.g. 'type hello there'."
ARGS = {"text": "the exact text to type"}


def run(args: dict) -> str:
    text = args.get("text") or ""
    if not text:
        return "Type what, exactly?"
    time.sleep(0.6)  # give focus a beat to settle after the voice command
    pyautogui.write(text, interval=0.02)
    return "Typed."
