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

# ---- learning a face over time ----------------------------------------
# One enrolment photo is one lighting, one angle, one expression, and every
# face that isn't that gets compared against it and missed. So every time a
# face is recognised CONFIDENTLY, that look is kept — a grin, a side-on
# head, a dark room. The set of known looks grows with use, and recognition
# gets better at exactly the conditions it's actually used in.
#
# The danger is drift: learn from a shaky match and the wrong person's face
# quietly joins the set, after which everything matches everyone. So the bar
# to LEARN is much stricter than the bar to NAME.
LEARN_THRESHOLD = 0.30    # must be well inside MATCH_THRESHOLD to be learnt
LEARN_MIN_NEW = 0.10      # and different enough from what's already known
MAX_GALLERY = 40          # looks kept per person before the dullest is dropped

# Below this average brightness the picture is lifted before recognition.
# A dark room doesn't change the shape of a face, but it does flatten the
# contrast the model reads, which is why it can see a face there and still
# not know whose it is.
DARK_ENOUGH = 80

# "zoom in" — digital crop-and-enlarge on the webcam feed, for someone too
# far away or too dim to make out ("I can't make out a face — more light,
# or come closer"). Not owner data, so it lives at the root next to the
# other *_state.json files rather than inside faces/.
ZOOM_FILE = BASE / "camera_zoom.json"
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 1.0, 3.0, 0.5


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
    # This file now rewrites itself as faces are learnt, so the enrolments
    # he made by hand are kept once, untouched, before anything automatic
    # ever edits them. If learning were ever to go wrong there'd otherwise
    # be nothing to go back to.
    backup = DB_FILE.with_suffix(".json.original")
    if DB_FILE.exists() and not backup.exists():
        try:
            backup.write_text(DB_FILE.read_text(encoding="utf-8"),
                              encoding="utf-8")
        except OSError:
            pass
    DB_FILE.write_text(json.dumps(db, indent=1), encoding="utf-8")


def _load_zoom() -> float:
    try:
        level = float(json.loads(ZOOM_FILE.read_text(encoding="utf-8")).get("level", ZOOM_MIN))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
        return ZOOM_MIN
    return max(ZOOM_MIN, min(ZOOM_MAX, level))


def _save_zoom(level: float) -> None:
    ZOOM_FILE.write_text(json.dumps({"level": level}), encoding="utf-8")


def _apply_zoom(frame, level: float):
    """Crop to the center 1/level of the frame and scale back up — a digital
    zoom so a distant or dim face fills more of what the detector sees."""
    if frame is None or level <= ZOOM_MIN:
        return frame
    import cv2

    h, w = frame.shape[:2]
    cw, ch = max(1, int(w / level)), max(1, int(h / level))
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    cropped = frame[y0:y0 + ch, x0:x0 + cw]
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)


def zoom_in() -> str:
    level = round(min(ZOOM_MAX, _load_zoom() + ZOOM_STEP), 1)
    _save_zoom(level)
    if level >= ZOOM_MAX:
        return f"Zoomed in to {level:g}x — that's as close as I can get digitally."
    return f"Zoomed in to {level:g}x. Say zoom in again, or zoom out to back off."


def zoom_out() -> str:
    level = round(max(ZOOM_MIN, _load_zoom() - ZOOM_STEP), 1)
    _save_zoom(level)
    if level <= ZOOM_MIN:
        return "Back to normal — no digital zoom."
    return f"Zoomed out to {level:g}x."


def zoom_reset() -> str:
    _save_zoom(ZOOM_MIN)
    return "Zoom reset — back to normal."


def get_frame():
    """A fresh camera frame (BGR array), digitally zoomed per zoom_in()/out().

    STREAM FIRST: if the live feed is running, use its latest frame and never
    touch the hardware — opening the device while the feed holds it kills the
    feed. Only grab the device directly when no stream is active.
    """
    import cv2

    zoom = _load_zoom()

    try:
        import dashboard

        t, jpg = dashboard.LATEST_JPEG
        if jpg and time.time() - t < 2:  # feed is live right now
            frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            return _apply_zoom(frame, zoom)
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
                # mirrored to match the live feed exactly. If enrolment saw
                # an unmirrored face and the feed a mirrored one, every face
                # would be learnt the wrong way round from the one it's later
                # compared against.
                return _apply_zoom(cv2.flip(frame, 1), zoom)
        finally:
            cap.release()
    except Exception:
        pass
    return None


def brightness(frame) -> float:
    """Average brightness, 0 (black) to 255.

    Every 8th pixel in each direction, which is a 64th of the work and
    lands within a fraction of a point of the true average — this is called
    on every single frame of the live feed, where reading all two million
    pixels cost more than some of the detectors do.
    """
    try:
        return float(np.asarray(frame)[::8, ::8].mean())
    except Exception:
        return 255.0


def _lift(frame):
    """Pull a dark frame up so recognition has something to read.

    His words: "if my room is dark he cant figure out who i am, but he sees
    a face". That split is the clue — finding a face needs only edges, which
    survive the dark, but knowing WHOSE face needs the fine contrast across
    it, and that's what's been crushed into near-black.

    CLAHE on the lightness channel only, so colour is untouched: it lifts
    the dim parts of the face without blowing out a lamp behind him, which
    is what a plain brightness/gamma boost does. Applied only when it's
    actually dark, so a well-lit face is compared exactly as it always was
    and nothing that already works starts behaving differently.
    """
    import cv2

    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)


def _faces_in(frame, lift: bool = False) -> list[dict]:
    """[{embedding, box(x,y,w,h)}] for every real face in the frame."""
    from deepface import DeepFace

    if lift:
        try:
            frame = _lift(frame)
        except Exception:
            pass
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


def _match(vec: np.ndarray, db: dict) -> tuple:
    """(name, how sure, raw distance) — the closest known look to this face.

    Returns the name only when it's inside MATCH_THRESHOLD, but hands back
    the distance either way so the caller can decide whether it's worth
    learning from.
    """
    best_name, best_dist = None, 1.0
    for name, info in db.items():
        for known in info.get("embeddings", []):
            k = np.array(known, dtype=np.float32)
            dist = 1.0 - float(vec @ k)
            if dist < best_dist:
                best_name, best_dist = name, dist
    if best_dist >= MATCH_THRESHOLD:
        return None, 0, best_dist
    # cosine similarity as a percentage: 100% is the identical picture,
    # ~45% is the loosest thing still called a match. Shown next to the
    # name so a shaky identification looks shaky instead of certain.
    return best_name, max(1, min(100, round((1.0 - best_dist) * 100))), best_dist


def _learn(name: str, vec: np.ndarray, db: dict, dist: float) -> bool:
    """Keep this look, if it's both trustworthy and new. True if it was kept.

    Two gates, and both matter:
      - trustworthy: a marginal match must never be learnt from. If it were,
        one wrong guess would be remembered as fact, the next wrong guess
        would match against it more easily, and the set would slide onto
        someone else's face. Learning only from near-certain matches keeps
        that from ever starting.
      - new: a hundred copies of the same straight-on look teaches nothing
        and just slows every future comparison down. Only a look that's
        meaningfully different from everything already known is worth space.
    """
    if dist > LEARN_THRESHOLD:
        return False
    entry = db.get(name)
    if entry is None:
        return False
    known = [np.array(e, dtype=np.float32) for e in entry.get("embeddings", [])]
    if known and min(1.0 - float(vec @ k) for k in known) < LEARN_MIN_NEW:
        return False                       # already knows this look

    entry.setdefault("embeddings", []).append(vec.tolist())
    entry["seen"] = entry.get("seen", 0) + 1
    entry["last_seen"] = datetime.date.today().isoformat()

    if len(entry["embeddings"]) > MAX_GALLERY:
        _drop_dullest(entry)
    return True


def _drop_dullest(entry: dict) -> None:
    """Full up — drop whichever look teaches the least.

    That's the one most similar to another look already kept, since between
    two near-identical pictures one of them is redundant. Index 0 is never
    dropped: that's the enrolment photo, the only look confirmed by a person
    rather than by the system agreeing with itself.
    """
    vecs = [np.array(e, dtype=np.float32) for e in entry["embeddings"]]
    twin, closest = None, 2.0
    for i in range(1, len(vecs)):
        for j in range(i + 1, len(vecs)):
            gap = 1.0 - float(vecs[i] @ vecs[j])
            if gap < closest:
                twin, closest = j, gap
    entry["embeddings"].pop(twin if twin is not None else 1)


def _pick(found: list, which: str):
    """Choose WHICH face the owner means. Enrolling always took the biggest
    face, so 'add Emma, the girl in the background' tagged the owner himself."""
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
    # newest enrolment goes FIRST and stays: it's the only look a person
    # actually confirmed, so it's the one _drop_dullest must never bin, and
    # the anchor everything learnt afterwards is measured against
    entry["embeddings"] = ([target["embedding"].tolist()]
                           + entry.get("embeddings", []))[:MAX_GALLERY]
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
    try:  # remember who was last learned, so "no, wrong name" can undo it
        LAST_LEARNED.write_text(name, encoding="utf-8")
    except OSError:
        pass
    return (f"Got it — I'll recognise {name} now.{extra} "
            f"If I misheard the name, say: no, wrong name.")


LAST_LEARNED = BASE / "faces" / "last_learned.txt"


def undo_last() -> str:
    """'No, wrong name' — undo the most recent enrolment. Speech mishears
    names ("Dad" for something else), and a phantom person is worse than
    no person."""
    try:
        name = LAST_LEARNED.read_text(encoding="utf-8").strip()
    except OSError:
        return "I haven't learned a face recently enough to undo."
    if not name:
        return "I haven't learned a face recently enough to undo."
    LAST_LEARNED.write_text("", encoding="utf-8")
    return forget(name).replace("Forgotten", "Undone — forgotten")


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
    that's the owner's memory of them, not the recognition data."""
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


def identify(frame=None, wait: bool = True, learn: bool = True) -> list[dict]:
    """[{name or None, score, box}] for everyone in view.

    score is how sure, 1-100, and 0 when nobody is named.

    wait=False (the live feed): skip instantly unless models are already warm.
    learn=False turns off remembering this look — for anywhere a wrong
    answer shouldn't be allowed to teach anything.
    """
    global ready
    if not ready and not wait:
        return []
    if frame is None:
        frame = get_frame()
    if frame is None:
        return []
    db = _db()
    _mirror_migrate(db)

    # The ordinary picture first.
    people = [[f, _match(f["embedding"], db)] for f in _faces_in(frame)]

    # Anyone it couldn't put a name to gets a second attempt on a lifted
    # picture. Measured, not assumed: lifting a face that was already lit
    # well enough makes the match WORSE (0.24 to 0.38 on his own enrolment
    # photo), because CLAHE rewrites contrast the recogniser was reading.
    # But where it's dark enough that no face is found at all, the lift is
    # the difference between a name and nothing. So it's a fallback, never
    # a filter: a working identification can't be spoiled by it, and only
    # the cases already failing get the second look.
    if not people or any(match[0] is None for _, match in people):
        for f in _faces_in(frame, lift=True):
            _merge_face(people, f, _match(f["embedding"], db))

    out = []
    learned = False
    for f, (name, score, dist) in people:
        if name and learn and _learn(name, f["embedding"], db, dist):
            learned = True
        out.append({"name": name, "score": score, "box": f["box"]})
    if learned:
        _save_db(db)
    ready = True
    return out


def _merge_face(people: list, face: dict, match: tuple) -> None:
    """Fold a second-attempt face into the results, best answer wins.

    Same face or a new one is decided by where it is: two boxes whose
    centres sit within half a face-width of each other are the same person
    seen twice, not two people.
    """
    x, y, w, h = face["box"]
    cx, cy = x + w / 2, y + h / 2
    for slot in people:
        px, py, pw, ph = slot[0]["box"]
        if (abs(px + pw / 2 - cx) < max(w, pw) * 0.5
                and abs(py + ph / 2 - cy) < max(h, ph) * 0.5):
            if match[2] < slot[1][2]:          # closer match than we had
                slot[0], slot[1] = face, match
            return
    people.append([face, match])


MIRRORED_FLAG = FACES_DIR / "mirrored.flag"


def _mirror_migrate(db: dict) -> None:
    """Teach every known face its own mirror image, once.

    The camera view is now flipped so his left hand is on the left of the
    picture, the way a mirror shows it. A flipped face is not the same
    picture to the recogniser — faces are close to symmetrical but not
    actually symmetrical — so every face enrolled before the flip was at
    risk of no longer matching itself.

    That would have been a nasty failure: recognition stops, and because
    learning only ever happens after a successful match, it could never
    teach its way back out. So each saved enrolment photo is re-read
    mirrored and added as another known look. Runs once, then leaves a flag.
    """
    if MIRRORED_FLAG.exists() or not db:
        return
    try:
        import cv2

        changed = False
        for name in list(db):
            photo = FACES_DIR / f"{name}.jpg"
            if not photo.exists():
                continue
            image = cv2.imread(str(photo))
            if image is None:
                continue
            found = _faces_in(cv2.flip(image, 1))
            if not found:
                continue
            biggest = max(found, key=lambda f: f["box"][2] * f["box"][3])
            db[name].setdefault("embeddings", []).append(
                biggest["embedding"].tolist())
            changed = True
        if changed:
            _save_db(db)
        FACES_DIR.mkdir(exist_ok=True)
        MIRRORED_FLAG.write_text("done", encoding="utf-8")
    except Exception:
        pass          # a failed migration must never stop recognition
