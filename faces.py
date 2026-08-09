"""TARS's face memory (DeepFace + the light SFace model).

faces/faces.json holds named face signatures; enroll() learns a face from the
camera, identify() names everyone in a frame. Each person gets a vault note in
People/ so details attach to them like any other memory.
"""
import datetime
import difflib
import json
import time
from pathlib import Path

import numpy as np

import truststore

truststore.inject_into_ssl()  # deepface downloads model weights on first use

BASE = Path(__file__).parent
FACES_DIR = BASE / "faces"
DB_FILE = FACES_DIR / "faces.json"

MODEL = "SFace"           # small + quick on CPU
DETECTOR = "yunet"        # opencv-5 wheels dropped the old haar files
MATCH_THRESHOLD = 0.55    # cosine distance — lower is stricter
MIN_FACE = 60             # px — ignore tiny background "faces"


ready = False  # models loaded? the live feed won't wait for them


def warmup() -> None:
    """Load the detector+recognizer off-thread so the feed never blocks."""
    global ready
    if ready:
        return
    try:
        _faces_in(np.zeros((240, 320, 3), dtype=np.uint8))
        ready = True
    except Exception:
        pass


def _db() -> dict:
    try:
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_db(db: dict) -> None:
    FACES_DIR.mkdir(exist_ok=True)
    DB_FILE.write_text(json.dumps(db, indent=1), encoding="utf-8")


def get_frame():
    """A fresh camera frame (BGR array).

    STREAM FIRST: if the live feed is running, use its latest frame and never
    touch the hardware — opening the device while the feed holds it kills the
    feed. Only grab the device directly when no stream is active.
    """
    import cv2

    try:
        import dashboard

        t, jpg = dashboard.LATEST_JPEG
        if jpg and time.time() - t < 2:  # feed is live right now
            return cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        pass
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            ok = cap.isOpened()
            if ok:
                for _ in range(6):
                    ok, frame = cap.read()
            if ok:
                return frame
        finally:
            cap.release()
    except Exception:
        pass
    return None


def _faces_in(frame) -> list[dict]:
    """[{embedding, box(x,y,w,h)}] for every real face in the frame."""
    from deepface import DeepFace

    try:
        reps = DeepFace.represent(frame, model_name=MODEL,
                                  detector_backend=DETECTOR,
                                  enforce_detection=False)
    except Exception:
        return []
    out = []
    for r in reps:
        area = r.get("facial_area") or {}
        w, h = area.get("w", 0), area.get("h", 0)
        # enforce_detection=False returns the whole frame as one "face" when
        # nothing was found — filter that and background specks out
        if w < MIN_FACE or h < MIN_FACE or w > frame.shape[1] * 0.9:
            continue
        vec = np.array(r["embedding"], dtype=np.float32)
        vec /= (np.linalg.norm(vec) + 1e-9)
        out.append({"embedding": vec,
                    "box": (area.get("x", 0), area.get("y", 0), w, h)})
    return out


def _match(vec: np.ndarray, db: dict) -> str | None:
    best_name, best_dist = None, 1.0
    for name, info in db.items():
        for known in info.get("embeddings", []):
            k = np.array(known, dtype=np.float32)
            dist = 1.0 - float(vec @ k)
            if dist < best_dist:
                best_name, best_dist = name, dist
    return best_name if best_dist < MATCH_THRESHOLD else None


def _pick(found: list, which: str):
    """Choose WHICH face Jacob means. Enrolling always took the biggest
    face, so 'add Emma, the girl in the background' tagged Jacob himself."""
    which = (which or "").lower()
    by_size = sorted(found, key=lambda f: -(f["box"][2] * f["box"][3]))
    by_x = sorted(found, key=lambda f: f["box"][0])
    if any(w in which for w in ("background", "behind", "further",
                                "furthest", "back", "smaller", "other",
                                "not me", "second")):
        return by_size[-1], "the one further back"
    if "left" in which:
        return by_x[0], "the one on the left"
    if "right" in which:
        return by_x[-1], "the one on the right"
    if any(w in which for w in ("closest", "front", "nearest", "me", "this")):
        return by_size[0], "the closest one"
    return None if len(found) > 1 else (by_size[0], "")


def enroll(name: str, frame=None, which: str = "") -> str:
    import cv2

    if frame is None:
        frame = get_frame()
    if frame is None:
        return "The camera didn't answer, so I can't learn a face right now."
    if float(frame.mean()) < 12:
        return "It's pitch black in here — turn a light on and try again."
    found = _faces_in(frame)
    if not found:
        return "I can't make out a face — more light, or come closer."
    picked = _pick(found, which)
    if picked is None:  # several faces, no hint — ASK instead of guessing
        return (f"I can see {len(found)} faces. Which one is {name} — the "
                f"closest one, the one further back, or left or right?")
    target, note = picked
    extra = f" (I took {note}.)" if note and len(found) > 1 else ""

    db = _db()
    entry = db.setdefault(name, {"embeddings": [], "learned": ""})
    entry["embeddings"] = (entry["embeddings"] + [target["embedding"].tolist()])[-5:]
    entry["learned"] = entry["learned"] or datetime.date.today().isoformat()
    _save_db(db)

    x, y, w, h = target["box"]
    pad = int(w * 0.25)
    crop = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    FACES_DIR.mkdir(exist_ok=True)
    cv2.imwrite(str(FACES_DIR / f"{name}.jpg"), crop)

    people = BASE / "vault" / "People"
    people.mkdir(parents=True, exist_ok=True)
    note = people / f"{name}.md"
    today = datetime.date.today().isoformat()
    if not note.exists():
        note.write_text(f"---\ncreated: {today}\ntags:\n  - person\n---\n\n"
                        f"- TARS learned {name}'s face on {today} *(photo in faces\\{name}.jpg)*\n",
                        encoding="utf-8")
    return f"Got it — I'll recognise {name} now.{extra}"


def known_names() -> list[str]:
    """Everyone currently enrolled, for 'who do you know' style replies."""
    return sorted(_db().keys())


def find_name(spoken: str) -> str | None:
    """Match a spoken name against the db loosely (speech-to-text spells names
    inconsistently), the same way correct_name matches vault entries."""
    db = _db()
    if not db:
        return None
    if spoken in db:
        return spoken
    lspoken = spoken.lower()
    for known in db:
        if known.lower() == lspoken:
            return known
    best, best_ratio = None, 0.0
    for known in db:
        ratio = difflib.SequenceMatcher(None, known.lower(), lspoken).ratio()
        if ratio > best_ratio:
            best, best_ratio = known, ratio
    return best if best_ratio >= 0.6 else None


def forget(name: str) -> str:
    """Remove a learned person from the face database — their embeddings and
    their reference photo. Their vault note in People/ is left alone, since
    that's Jacob's memory of them, not the recognition data."""
    db = _db()
    if name not in db:
        return f"I don't have {name} in my face database."
    del db[name]
    _save_db(db)

    photo = FACES_DIR / f"{name}.jpg"
    if photo.exists():
        try:
            from send2trash import send2trash
            send2trash(str(photo))
        except Exception:
            pass
    return f"Done — I've forgotten {name}'s face, I won't recognise them anymore."


def identify(frame=None, wait: bool = True) -> list[dict]:
    """[{name or None, box}] for everyone in view.

    wait=False (the live feed): skip instantly unless models are already warm.
    """
    global ready
    if not ready and not wait:
        return []
    if frame is None:
        frame = get_frame()
    if frame is None:
        return []
    db = _db()
    out = []
    for f in _faces_in(frame):
        out.append({"name": _match(f["embedding"], db), "box": f["box"]})
    ready = True
    return out
