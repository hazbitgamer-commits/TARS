"""Seeing people properly — skeletons, hands, faces — and drawing it like a HUD.

What was there before ran DeepFace on every refresh. DeepFace is a
RECOGNITION model: it answers "who is this", and it takes hundreds of
milliseconds to do it. Asking it to also do the tracking meant the box
round his face lagged two seconds behind his head.

So the work is split by what each part is actually for:

    every frame      MediaPipe detectors — where are the bodies, hands and
                     faces RIGHT NOW. Milliseconds, so the overlay moves
                     with him instead of trailing.
    every ~2 seconds DeepFace — WHO those faces belong to. Slow, and it
                     doesn't need to be fast: his name doesn't change
                     between frames.

The names are then attached to the fast boxes by position, so a name
follows a face around smoothly even though it was worked out seconds ago.

Everything is optional and degrades quietly: no models, no mediapipe, or a
model that won't load just means that layer isn't drawn, never a crash and
never a black screen.
"""
import math
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
MODELS = BASE / "models"

MAX_PEOPLE = 4          # "everyone in the room" — beyond four it crawls
IDENTIFY_EVERY = 2.0    # seconds between asking DeepFace who people are

# JARVIS HUD, in BGR because that's what OpenCV wants
CYAN = (255, 214, 92)
CYAN_DIM = (150, 130, 60)
WHITE = (235, 245, 245)
AMBER = (60, 190, 255)
GREEN = (120, 230, 140)

# the 33 pose landmarks, joined into limbs. Face points 1-10 are left out:
# the face mesh draws that far better than four dots ever could.
BONES = [
    (11, 12), (11, 23), (12, 24), (23, 24),          # torso
    (11, 13), (13, 15), (12, 14), (14, 16),          # arms
    (15, 17), (15, 19), (15, 21), (16, 18), (16, 20), (16, 22),
    (23, 25), (25, 27), (24, 26), (26, 28),          # legs
    (27, 29), (29, 31), (27, 31), (28, 30), (30, 32), (28, 32),
]
HAND_BONES = [
    (0, 1), (1, 2), (2, 3), (3, 4),            # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),            # index
    (5, 9), (9, 10), (10, 11), (11, 12),       # middle
    (9, 13), (13, 14), (14, 15), (15, 16),     # ring
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),   # little
]

_lock = threading.Lock()
_models = {"pose": None, "face": None, "hands": None, "loaded": False}
_names = {"at": 0.0, "people": [], "busy": False}
_stats = {"ms": 0.0, "people": 0}


def _load() -> bool:
    """Build the detectors once. Slow (a second or two), so it happens on
    first use rather than at import — TARS's startup is already long."""
    if _models["loaded"]:
        return _models["pose"] is not None
    with _lock:
        if _models["loaded"]:
            return _models["pose"] is not None
        _models["loaded"] = True
        try:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except Exception:
            return False

        def build(kind, filename, **extra):
            path = MODELS / filename
            if not path.exists():
                return None
            try:
                base = mp_python.BaseOptions(model_asset_path=str(path))
                options = kind(base_options=base,
                               running_mode=vision.RunningMode.IMAGE, **extra)
                return getattr(vision, kind.__name__[:-7]).create_from_options(options)
            except Exception:
                return None

        _models["pose"] = build(vision.PoseLandmarkerOptions,
                                "pose_landmarker_full.task",
                                num_poses=MAX_PEOPLE)
        _models["face"] = build(vision.FaceLandmarkerOptions,
                                "face_landmarker.task",
                                num_faces=MAX_PEOPLE)
        _models["hands"] = build(vision.HandLandmarkerOptions,
                                 "hand_landmarker.task",
                                 num_hands=MAX_PEOPLE * 2)
        return _models["pose"] is not None


def _identify_later(frame) -> None:
    """Ask DeepFace who's in shot, on a background thread.

    Never blocks a frame. If it's still thinking when the next request
    comes, that request is dropped — a name two seconds stale is fine, a
    stuttering picture is not.
    """
    if _names["busy"] or time.time() - _names["at"] < IDENTIFY_EVERY:
        return
    _names["busy"] = True

    def work():
        try:
            import faces

            found = faces.identify(frame.copy(), wait=False)
            _names["people"] = [{"name": f.get("name"), "box": f["box"]}
                                for f in found if f.get("box")]
        except Exception:
            pass
        finally:
            _names["at"] = time.time()
            _names["busy"] = False

    threading.Thread(target=work, daemon=True).start()


def _name_for(x: int, y: int, w: int, h: int) -> str:
    """Which known face is this fast-detected one? Matched by overlap, so a
    name stays stuck to the right head as it moves."""
    best, score = "", 0.0
    cx, cy = x + w / 2, y + h / 2
    for person in _names["people"]:
        px, py, pw, ph = person["box"]
        if px <= cx <= px + pw and py <= cy <= py + ph:
            overlap = min(w, pw) * min(h, ph)
            if overlap > score:
                best, score = person.get("name") or "", overlap
    return best


def _px(landmark, width: int, height: int) -> tuple:
    return int(landmark.x * width), int(landmark.y * height)


def _brackets(img, x, y, w, h, colour, arm: int = 18, thick: int = 2) -> None:
    """Corner brackets rather than a closed box — the HUD look, and it
    leaves the person's face actually visible."""
    import cv2

    for dx, dy in ((0, 0), (w, 0), (0, h), (w, h)):
        sx = 1 if dx == 0 else -1
        sy = 1 if dy == 0 else -1
        cv2.line(img, (x + dx, y + dy), (x + dx + sx * arm, y + dy), colour, thick)
        cv2.line(img, (x + dx, y + dy), (x + dx, y + dy + sy * arm), colour, thick)


def annotate(frame):
    """Draw everything onto the frame, in place. Returns how many people."""
    import cv2
    import numpy as np

    if not _load():
        return 0

    started = time.time()
    height, width = frame.shape[:2]
    try:
        import mediapipe as mp

        image = mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except Exception:
        return 0

    # ---- skeletons ------------------------------------------------------
    people = 0
    try:
        result = _models["pose"].detect(image)
        for person in (result.pose_landmarks or []):
            people += 1
            pts = [_px(p, width, height) for p in person]
            for a, b in BONES:
                if a < len(pts) and b < len(pts):
                    cv2.line(frame, pts[a], pts[b], CYAN, 2, cv2.LINE_AA)
            for i, (px, py) in enumerate(pts):
                if i < 11:                 # face points — the mesh does those
                    continue
                cv2.circle(frame, (px, py), 4, WHITE, -1, cv2.LINE_AA)
                cv2.circle(frame, (px, py), 7, CYAN_DIM, 1, cv2.LINE_AA)
    except Exception:
        pass

    # ---- face mesh, boxes and names -------------------------------------
    try:
        result = _models["face"].detect(image)
        for face in (result.face_landmarks or []):
            pts = [_px(p, width, height) for p in face]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x, y = max(0, min(xs)), max(0, min(ys))
            w, h = max(1, max(xs) - x), max(1, max(ys) - y)

            # the mesh: every 4th point, or 468 dots is a solid blob
            for px, py in pts[::4]:
                cv2.circle(frame, (px, py), 1, CYAN_DIM, -1)

            name = _name_for(x, y, w, h)
            colour = GREEN if name else AMBER
            _brackets(frame, x, y, w, h, colour)
            label = name.upper() if name else "UNKNOWN"
            cv2.putText(frame, label, (x, max(16, y - 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2, cv2.LINE_AA)
    except Exception:
        pass

    # ---- hands ----------------------------------------------------------
    try:
        result = _models["hands"].detect(image)
        for hand in (result.hand_landmarks or []):
            pts = [_px(p, width, height) for p in hand]
            for a, b in HAND_BONES:
                if a < len(pts) and b < len(pts):
                    cv2.line(frame, pts[a], pts[b], AMBER, 1, cv2.LINE_AA)
            for px, py in pts:
                cv2.circle(frame, (px, py), 2, WHITE, -1)
    except Exception:
        pass

    _identify_later(frame)

    # ---- the readout ----------------------------------------------------
    _stats["ms"] = (time.time() - started) * 1000
    _stats["people"] = people
    cv2.putText(frame, f"TRACKING {people}  {_stats['ms']:.0f}ms",
                (10, height - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                CYAN, 1, cv2.LINE_AA)
    return people


def stats() -> dict:
    return dict(_stats)
