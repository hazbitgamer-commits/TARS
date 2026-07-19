"""Click something on screen by describing it: TARS's eyes (the vision model)
find the element's coordinates, then the mouse clicks it. Fully local."""
import base64
import io
import json
from pathlib import Path

import pyautogui
import requests
from mss import mss
from PIL import Image

DESCRIPTION = ("CLICK something visible on the screen, described in words — 'click the "
               "first video', 'press the play button', 'click accept'. TARS looks at "
               "the screen, finds it, and clicks it. Also 'double click the ...'.")
ARGS = {"target": "what to click, described in words",
        "monitor": "'left' for the left screen, otherwise the main one",
        "double": "'true' for a double-click"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
VISION_MODEL = "qwen2.5vl:7b"
VIEW_WIDTH = 1280  # what the vision model sees; coordinates get scaled back up


def _grab(which: str):
    with mss() as grabber:
        monitors = grabber.monitors[1:]
        if "left" in which and len(monitors) > 1:
            mon = min(monitors, key=lambda m: m["left"])
        else:
            mon = next((m for m in monitors if m["left"] == 0 and m["top"] == 0),
                       monitors[0])
        shot = grabber.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.rgb)
    scale = 1.0
    if img.width > VIEW_WIDTH:
        scale = img.width / VIEW_WIDTH
        img = img.resize((VIEW_WIDTH, round(img.height / scale)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), mon, scale


def locate(target: str, which: str = "main"):
    """(screen_x, screen_y) of the described element, or None."""
    png, mon, scale = _grab(which)
    r = requests.post(OLLAMA_URL, json={
        "model": VISION_MODEL, "stream": False, "format": "json",
        "keep_alive": "30m",
        "messages": [{
            "role": "user",
            "content": (f"Find this element in the screenshot: {target!r}. "
                        'Reply JSON: {"found": true/false, "x": <int>, "y": <int>} '
                        "where x,y is the CENTER of the element in this image's "
                        "pixel coordinates. found=false if it isn't visible."),
            "images": [base64.b64encode(png).decode()],
        }],
        "options": {"num_predict": 80, "num_ctx": 8192}}, timeout=180)
    r.raise_for_status()
    data = json.loads(r.json()["message"]["content"])
    if not data.get("found"):
        return None
    x = mon["left"] + int(int(data["x"]) * scale)
    y = mon["top"] + int(int(data["y"]) * scale)
    return x, y


def run(args: dict) -> str:
    target = (args.get("target") or "").strip()
    if not target:
        return "Click what, exactly?"
    try:
        spot = locate(target, (args.get("monitor") or "main").strip().lower())
    except requests.RequestException:
        return "My eyes aren't answering — is the vision model still loading?"
    except Exception:
        return f"I couldn't make sense of the screen looking for {target}."
    if spot is None:
        return f"I can't see {target} on that screen right now."
    if str(args.get("double", "")).lower() == "true":
        pyautogui.doubleClick(spot[0], spot[1])
        return f"Double-clicked {target}."
    pyautogui.click(spot[0], spot[1])
    return f"Clicked {target}."
