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

# How long a name sticks to a face after the last confident match.
# DeepFace compares a face to one enrolled photo, so a smile or a turned
# head moves the embedding enough to miss — and dropping the name the
# instant that happens made it flicker between his name and "UNKNOWN".
# A face doesn't stop being his because he grinned, so the name holds.
NAME_STICKS_FOR = 8.0

# Smoothing. Landmarks wobble a few pixels every frame even when nothing
# moves; drawn raw, a skeleton looks like it's having a fit. Each point is
# blended with where it was last frame — higher follows faster, lower is
# calmer.
SMOOTH = 0.55
# and points the model isn't sure about aren't drawn at all, rather than
# being flung across the room. This is most of "the body tracking goes crazy":
# an occluded leg gets a wild guess, and a wild guess drawn confidently
# looks far worse than nothing.
MIN_VISIBLE = 0.55
MIN_CONFIDENCE = 0.6

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
_clock = 0          # rising milliseconds, for VIDEO mode


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
                # VIDEO, not IMAGE. IMAGE treats every frame as an unrelated
                # photograph, so the model re-finds everything from scratch
                # and the result jumps about. VIDEO keeps track between
                # frames and is dramatically steadier — this single line is
                # most of the fix for the skeleton going haywire.
                options = kind(base_options=base,
                               running_mode=vision.RunningMode.VIDEO, **extra)
                return getattr(vision, kind.__name__[:-7]).create_from_options(options)
            except Exception:
                return None

        _models["pose"] = build(
            vision.PoseLandmarkerOptions, "pose_landmarker_full.task",
            num_poses=MAX_PEOPLE,
            min_pose_detection_confidence=MIN_CONFIDENCE,
            min_pose_presence_confidence=MIN_CONFIDENCE,
            min_tracking_confidence=MIN_CONFIDENCE)
        _models["face"] = build(
            vision.FaceLandmarkerOptions, "face_landmarker.task",
            num_faces=MAX_PEOPLE,
            min_face_detection_confidence=MIN_CONFIDENCE,
            min_face_presence_confidence=MIN_CONFIDENCE,
            min_tracking_confidence=MIN_CONFIDENCE)
        _models["hands"] = build(
            vision.HandLandmarkerOptions, "hand_landmarker.task",
            num_hands=MAX_PEOPLE * 2,
            min_hand_detection_confidence=MIN_CONFIDENCE,
            min_hand_presence_confidence=MIN_CONFIDENCE,
            min_tracking_confidence=MIN_CONFIDENCE)
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


_sticky = []      # [{"name", "cx", "cy", "at"}] — names that have stuck


def _name_for(x: int, y: int, w: int, h: int) -> str:
    """Who is this face?

    Two layers. First, any fresh answer from DeepFace whose box contains
    this face. Failing that, a name we were confident about recently, near
    this spot — because DeepFace misses constantly on a smile or a turned
    head, and losing his name every time he grins is worse than holding a
    name a few seconds too long.
    """
    cx, cy = x + w / 2, y + h / 2
    now = time.time()

    best, score = "", 0.0
    for person in _names["people"]:
        px, py, pw, ph = person["box"]
        if px <= cx <= px + pw and py <= cy <= py + ph:
            overlap = min(w, pw) * min(h, ph)
            if overlap > score and person.get("name"):
                best, score = person["name"], overlap

    if best:                                   # confident — remember it here
        for seen in _sticky:
            if math.hypot(seen["cx"] - cx, seen["cy"] - cy) < max(w, h):
                seen.update(name=best, cx=cx, cy=cy, at=now)
                break
        else:
            _sticky.append({"name": best, "cx": cx, "cy": cy, "at": now})
        return best

    # nothing fresh — has this face been named recently, roughly here?
    near = max(w, h) * 1.5
    for seen in list(_sticky):
        if now - seen["at"] > NAME_STICKS_FOR:
            _sticky.remove(seen)
            continue
        if math.hypot(seen["cx"] - cx, seen["cy"] - cy) < near:
            seen.update(cx=cx, cy=cy)          # follow the face as it moves
            return seen["name"]
    return ""


_smoothed = []      # [{"kind", "points", "at"}] — one entry per tracked thing
TRACK_FORGET = 1.0  # seconds before a vanished body is a new body, not a jump


def _smooth(kind: str, points: list) -> list:
    """Blend each point with where that same thing was last frame.

    Landmarks jitter several pixels even on a motionless subject. Raw, the
    skeleton shivers; smoothed, it moves like a body.

    Matched by POSITION, not by list order. MediaPipe makes no promise about
    the order it returns people or hands in, so slot 0 can be him this frame
    and his brother the next. Blending by slot then drags one skeleton
    halfway across the room toward the other — which is most of what "the
    body tracking goes crazy" looks like. Nearest-centroid matching means a
    reordered list is still recognised as the same body in the same place.
    """
    if not points:
        return points
    now = time.time()
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)

    # how far apart these points are, so the match distance scales with a
    # near thing (large on screen) vs a far one
    spread = max(max(p[0] for p in points) - min(p[0] for p in points),
                 max(p[1] for p in points) - min(p[1] for p in points))
    reach = max(spread * 0.6, 60)

    best, closest = None, reach
    for entry in list(_smoothed):
        if now - entry["at"] > TRACK_FORGET:
            _smoothed.remove(entry)             # long gone; don't lurch to it
            continue
        if entry["kind"] != kind or len(entry["points"]) != len(points):
            continue
        gap = math.hypot(entry["cx"] - cx, entry["cy"] - cy)
        if gap < closest:
            best, closest = entry, gap

    if best is None:
        _smoothed.append({"kind": kind, "points": list(points),
                          "cx": cx, "cy": cy, "at": now})
        return points

    blended = [(int(SMOOTH * nx + (1 - SMOOTH) * ox),
                int(SMOOTH * ny + (1 - SMOOTH) * oy))
               for (nx, ny), (ox, oy) in zip(points, best["points"])]
    best.update(points=blended, cx=cx, cy=cy, at=now)
    return blended


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


_draw_lock = threading.Lock()


def annotate(frame):
    """Draw everything onto the frame, in place. Returns how many people.

    One at a time, always. The dashboard camera page and the remote
    livestream both call this, and a MediaPipe landmarker in VIDEO mode is
    neither thread-safe nor willing to accept a timestamp older than the
    last one it saw. Two threads interleaving would make every frame throw —
    and because the drawing swallows its own errors, that failure would show
    up as the overlay silently disappearing rather than as an error anyone
    could chase. The wait costs a few milliseconds; the alternative costs
    the whole feature.
    """
    with _draw_lock:
        return _annotate(frame)


def _annotate(frame):
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

    # VIDEO mode wants a timestamp that only ever goes up
    global _clock
    _clock += 33

    # ---- skeletons ------------------------------------------------------
    people = 0
    try:
        result = _models["pose"].detect_for_video(image, _clock)
        for person in (result.pose_landmarks or []):
            people += 1
            raw = [_px(p, width, height) for p in person]
            pts = _smooth("pose", raw)
            seen = [getattr(p, "visibility", 1.0) for p in person]
            for a, b in BONES:
                if a >= len(pts) or b >= len(pts):
                    continue
                if seen[a] < MIN_VISIBLE or seen[b] < MIN_VISIBLE:
                    continue     # a guessed limb drawn confidently looks mad
                cv2.line(frame, pts[a], pts[b], CYAN, 2, cv2.LINE_AA)
            for i, (px, py) in enumerate(pts):
                if i < 11 or seen[i] < MIN_VISIBLE:
                    continue     # face points — the mesh does those better
                cv2.circle(frame, (px, py), 4, WHITE, -1, cv2.LINE_AA)
                cv2.circle(frame, (px, py), 7, CYAN_DIM, 1, cv2.LINE_AA)
    except Exception:
        pass

    # ---- face mesh, boxes and names -------------------------------------
    try:
        result = _models["face"].detect_for_video(image, _clock)
        for face in (result.face_landmarks or []):
            pts = _smooth("face", [_px(p, width, height) for p in face])
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
        result = _models["hands"].detect_for_video(image, _clock)
        for hand in (result.hand_landmarks or []):
            pts = _smooth("hand", [_px(p, width, height) for p in hand])
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
