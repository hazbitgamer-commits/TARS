"""TARS's eyes: screenshot the screen and describe it with a local vision
model (qwen2.5vl via Ollama). Captures via DXGI desktop duplication (dxcam),
which sees fullscreen games — the old GDI path (mss) only as a fallback."""
import base64
import datetime
import re
import time
from pathlib import Path

import requests

DESCRIPTION = ("LOOK at the owner's screen and describe or answer questions about what's "
               "visible. E.g. 'what's on my screen', 'look at my screen and tell me "
               "what game this is', 'read the error message on screen'.")
ARGS = {"question": "what the owner wants to know about the screen (default: describe it)",
        "monitor": "'left' for the left screen, otherwise the main one"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
VISION_MODEL = "qwen2.5vl:7b"


def _dxcam_grab(which: str):
    """Game-proof capture straight off the graphics card."""
    import dxcam

    outputs = re.findall(r"Output\[(\d+)\]: Res:\(\d+, \d+\).*?Primary:(True|False)",
                         dxcam.output_info())
    idx = 0
    if outputs:
        wanted = "False" if "left" in which else "True"
        hits = [o for o in outputs if o[1] == wanted]
        idx = int(hits[0][0]) if hits else int(outputs[0][0])
    cam = dxcam.create(output_idx=idx, output_color="BGR")
    try:
        for _ in range(20):
            frame = cam.grab()
            if frame is not None:
                return frame
            time.sleep(0.03)
        return None
    finally:
        del cam


def _mss_grab(which: str):
    import numpy as np
    from mss import mss

    with mss() as grabber:
        monitors = grabber.monitors[1:]
        if "left" in which and len(monitors) > 1:
            mon = min(monitors, key=lambda m: m["left"])
        else:
            mon = next((m for m in monitors if m["left"] == 0 and m["top"] == 0),
                       monitors[0])
        shot = grabber.grab(mon)
        return np.array(shot)[:, :, :3]  # BGRA -> BGR


def run(args: dict) -> str:
    question = (args.get("question") or "").strip() or "Describe what's on this screen."
    which = (args.get("monitor") or "main").strip().lower()

    frame = None
    try:
        frame = _dxcam_grab(which)
    except Exception:
        pass
    if frame is None or float(frame.mean()) < 1.5:
        try:
            alt = _mss_grab(which)
            if alt is not None and (frame is None or alt.mean() > frame.mean()):
                frame = alt
        except Exception:
            pass
    if frame is None:
        return "I couldn't capture the screen at all just now."

    import cv2

    if frame.shape[1] > 1280:
        h = round(frame.shape[0] * 1280 / frame.shape[1])
        frame = cv2.resize(frame, (1280, h))
    ok, png = cv2.imencode(".png", frame)
    if not ok:
        return "The screenshot came back unreadable."
    png = png.tobytes()

    out_dir = Path.home() / "Pictures" / "TARS"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"looked-{stamp}.png").write_bytes(png)

    if float(frame.mean()) < 1.5:
        return ("All I captured was a black frame — that game is blocking screen "
                "capture. Switching it to borderless windowed mode fixes that.")

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": VISION_MODEL, "stream": False, "keep_alive": "30m",
            "messages": [{
                "role": "user",
                "content": (f"{question}\nAnswer in one to three short spoken "
                            "sentences. Plain text, no markdown."),
                "images": [base64.b64encode(png).decode()],
            }],
            "options": {"num_predict": 160, "num_ctx": 8192}}, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except requests.RequestException:
        return ("My eyes aren't working — the vision model may still be "
                "loading. Try again in a moment.")
