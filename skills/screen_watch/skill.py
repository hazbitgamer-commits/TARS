"""Screen watcher: "tell me when the download finishes" — TARS checks the
screen with his vision model every couple of minutes and announces the
moment the thing has happened. One watch at a time, gives up after 45
minutes so a forgotten watch can't burn the GPU forever."""
import base64
import json
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
STATE = BASE / "screen_watch.json"
VISION_MODEL = "qwen2.5vl:7b"
CHECK_EVERY = 120          # seconds between looks — light on the GPU
GIVE_UP_AFTER = 45 * 60

DESCRIPTION = ("WATCH the screen for something and announce when it happens: "
               "'tell me when the download finishes', 'let me know when the "
               "install is done', 'watch for the match to start'. Also 'stop "
               "watching' cancels. NOT for a one-off 'what's on my screen' "
               "question (that's look_at_screen).")
ARGS = {"for": "plain-English description of what to wait for, e.g. 'the "
               "download to finish', or 'stop' to cancel the current watch"}


def _grab_png():
    import cv2
    import numpy as np

    frame = None
    try:
        import dxcam

        cam = dxcam.create(output_color="BGR")
        frame = cam.grab()
        del cam
    except Exception:
        pass
    if frame is None:
        import mss

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            frame = np.array(shot)[:, :, :3]
    if frame.shape[1] > 1280:
        h = round(frame.shape[0] * 1280 / frame.shape[1])
        frame = cv2.resize(frame, (1280, h))
    ok, png = cv2.imencode(".png", frame)
    return png.tobytes() if ok else None


def _happened(condition: str) -> bool:
    import requests

    png = _grab_png()
    if not png:
        return False
    r = requests.post("http://127.0.0.1:11434/api/chat", json={
        "model": VISION_MODEL, "stream": False, "keep_alive": "30m",
        "messages": [{"role": "user",
                      "content": f"Screenshot of a Windows PC. Has this "
                                 f"happened yet: {condition}? If you can "
                                 f"clearly see it has, answer YES. If not, "
                                 f"or you're unsure, answer NO. One word "
                                 f"only.",
                      "images": [base64.b64encode(png).decode()]}],
        "options": {"num_predict": 8, "num_ctx": 8192}}, timeout=180)
    r.raise_for_status()
    return "yes" in r.json()["message"]["content"].strip().lower()


def _watcher(condition: str, started: float) -> None:
    import sys

    sys.path.insert(0, str(BASE))
    import announce

    while True:
        time.sleep(CHECK_EVERY)
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if state.get("started") != started:  # replaced or cancelled
            return
        if time.time() - started > GIVE_UP_AFTER:
            STATE.write_text("{}", encoding="utf-8")
            announce.post(f"I've been watching for {condition} for 45 "
                          f"minutes with no luck — calling it off. Ask me "
                          f"to watch again if it's still coming.")
            return
        try:
            if _happened(condition):
                STATE.write_text("{}", encoding="utf-8")
                announce.post(f"That thing you asked about — {condition} — "
                              f"it's done. Just spotted it on screen.")
                return
        except Exception:
            continue  # vision hiccup — try again next round


def run(args: dict) -> str:
    condition = str(args.get("for") or "").strip().rstrip(".")
    if not condition:
        return "What should I watch the screen for?"
    if condition.lower() in ("stop", "cancel", "stop watching", "nothing"):
        STATE.write_text("{}", encoding="utf-8")
        return "Okay, I've stopped watching the screen."

    started = time.time()
    STATE.write_text(json.dumps({"for": condition, "started": started}),
                     encoding="utf-8")
    threading.Thread(target=_watcher, args=(condition, started),
                     daemon=True).start()
    return (f"On it — I'll glance at the screen every couple of minutes "
            f"and sing out when {condition}.")
