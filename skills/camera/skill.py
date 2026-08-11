"""TARS's third eye: the desk webcam. Grabs a frame and describes it with the
local vision model — nothing leaves the PC. A copy lands in Pictures\\TARS."""
import base64
import datetime
import re
import time
from pathlib import Path

import requests

DESCRIPTION = ("LOOK through the desk webcam — only when the owner explicitly says "
               "camera/webcam: 'access my camera', 'check the camera, what am I "
               "holding'. NOT for the screen — that's look_at_screen.")
ARGS = {"question": "what the owner wants to know (default: describe what you see)"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
VISION_MODEL = "qwen2.5vl:7b"

# If the owner asks the exact same thing again shortly after (e.g. "what are the
# dimensions of this?" then "what are the dimensions?"), skip the camera grab
# and vision model round-trip and just repeat the answer instantly.
_CACHE_TTL = 300  # seconds
_last = {"question": "", "answer": "", "time": 0.0}


def _normalize(q: str) -> str:
    return re.sub(r"[^\w\s]", "", q.lower()).strip()


def run(args: dict) -> str:
    question = (args.get("question") or "").strip() or \
        "Describe what you see through this webcam."

    norm = _normalize(question)
    if norm and norm == _last["question"] and time.time() - _last["time"] < _CACHE_TTL:
        return _last["answer"]

    import sys

    import cv2

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from faces import get_frame  # stream-first: never disturbs a live feed

    frame = get_frame()
    if frame is None:
        return "The camera didn't answer. Is something else using it?"
    ok, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return "The camera gave me a frame I couldn't read."
    img = enc.tobytes()

    out_dir = Path.home() / "Pictures" / "TARS"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"camera-{stamp}.jpg").write_bytes(img)

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": VISION_MODEL, "stream": False, "keep_alive": "30m",
            "messages": [{
                "role": "user",
                "content": (f"{question}\nThis is the webcam on the owner's desk, "
                            "probably showing the owner himself. Answer in one to "
                            "three short spoken sentences. Plain text."),
                "images": [base64.b64encode(img).decode()],
            }],
            "options": {"num_predict": 160, "num_ctx": 8192}}, timeout=180)
        r.raise_for_status()
        answer = r.json()["message"]["content"].strip()
        _last.update(question=norm, answer=answer, time=time.time())
        return answer
    except requests.RequestException:
        return "My vision model isn't answering — try again in a moment."
