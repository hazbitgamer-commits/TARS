"""Hand signals: control TARS without speaking.

Runs MediaPipe's gesture recogniser over the webcam at ~30fps locally —
nothing leaves the PC, and the heavy vision model isn't involved at all.

ON DEMAND ONLY, by the owner's explicit choice: it starts when he says "watch
for signals" and stops on command, on timeout, or when the process ends.
The camera is never opened by this module for any other reason.

What the signals do (his picks):
  Open palm  -> stop talking, immediately
  Thumbs up  -> "yes"   (answers whatever TARS just asked)
  Thumbs down-> "no"
"""
import ctypes.wintypes  # noqa: F401 — needed for monitor enumeration
import os
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
MODEL = BASE / "models" / "gesture_recognizer.task"

# a signal must hold for this many of the last frames before it counts —
# a hand passing through shot must not pause his music
HOLD_FRAMES = 6
WINDOW = 10
CONFIDENCE = 0.6
COOLDOWN = 3.0        # seconds before the same signal can fire again
DEFAULT_MINUTES = 10  # watching stops on its own; the camera never lingers

_thread: threading.Thread | None = None
_running = threading.Event()
_state = {"last": "", "at": 0.0, "seen": 0, "since": 0.0}
_speaker = None   # set by main.py — for "stop talking"
_brain = None     # set by main.py — for yes/no


_recogniser = None
_warm_lock = threading.Lock()


def wire(speaker=None, brain=None) -> None:
    global _speaker, _brain
    _speaker, _brain = speaker, brain


def warm() -> None:
    """Import mediapipe and build the recogniser NOW, in the background.

    Measured: importing mediapipe costs 4.3s, building the recogniser
    0.05s. Paid when the owner says "watch for signals" it feels broken; paid
    at boot he never sees it, leaving only the camera's 1.4s.
    """
    global _recogniser
    with _warm_lock:
        if _recogniser is not None or not MODEL.exists():
            return
        try:
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision

            _recogniser = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=mpt.BaseOptions(model_asset_path=str(MODEL)),
                    running_mode=vision.RunningMode.IMAGE, num_hands=1))
        except Exception:
            _recogniser = None


def live() -> dict:
    """What the HUD needs to draw itself."""
    return {"watching": _running.is_set(),
            "hand": _state.get("hand", ""),
            "last": _state.get("last", ""),
            "last_at": _state.get("at", 0),
            "seen": _state.get("seen", 0),
            "since": _state.get("since", 0)}


def open_hud() -> bool:
    """The camera HUD, fullscreen on the SECOND monitor — he games on the
    main one, so it must never land there. His second screen is portrait
    at negative x, which is a perfectly valid position."""
    import subprocess

    monitors: list[tuple[int, int, int, int]] = []
    try:
        user32 = ctypes.windll.user32  # Windows only; Mac skips to the else

        def collect(handle, hdc, rect, data):
            r = rect.contents
            monitors.append((r.left, r.top, r.right, r.bottom))
            return 1

        proto = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double)
        user32.EnumDisplayMonitors(None, None, proto(collect), 0)
    except Exception:
        monitors = []

    spot = None
    others = [m for m in monitors if not (m[0] == 0 and m[1] == 0)]
    if len(monitors) > 1 and others:
        spot = others[0]
    args = ["--app=http://127.0.0.1:8765/hud", "--start-fullscreen",
            "--new-window"]
    if spot:
        args.append(f"--window-position={spot[0]},{spot[1]}")
    try:  # one place knows where the browser lives on each OS
        from platform_caps import browser_exe

        exe = browser_exe()
    except Exception:
        exe = ""
    if exe:
        try:
            subprocess.Popen([exe] + args)
            return True
        except Exception:
            pass
    try:
        import webbrowser

        webbrowser.open("http://127.0.0.1:8765/hud")
        return True
    except Exception:
        return False


def _backend(cv2):
    """DirectShow on Windows (MSMF can't grab on the owner's webcam),
    AVFoundation on a Mac, default elsewhere."""
    try:
        from platform_caps import camera_backend

        return camera_backend() or cv2.CAP_ANY
    except Exception:
        return cv2.CAP_ANY


def available() -> tuple[bool, str]:
    """Can this run at all? Returns (ok, why not)."""
    if not MODEL.exists():
        return False, "the gesture model file is missing"
    try:
        import mediapipe  # noqa: F401
    except Exception:
        return False, "mediapipe isn't installed"
    return True, ""


def active() -> bool:
    return _running.is_set()


def _act(gesture: str) -> str:
    """Do the thing. Returns what to say, or '' for silence."""
    if gesture == "Open_Palm":
        if _speaker is not None:
            try:
                _speaker.shut_up()
            except Exception:
                pass
        return ""  # cutting him off then talking would be daft
    if gesture in ("Thumb_Up", "Thumb_Down"):
        word = "yes" if gesture == "Thumb_Up" else "no"
        if _brain is None:
            return ""
        try:
            return _brain.handle(word) or ""
        except Exception:
            return ""
    return ""


def _loop(minutes: float) -> None:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    import announce

    warm()  # normally already done at boot; free if so
    recogniser = _recogniser
    if recogniser is None:
        recogniser = vision.GestureRecognizer.create_from_options(
            vision.GestureRecognizerOptions(
                base_options=mpt.BaseOptions(model_asset_path=str(MODEL)),
                running_mode=vision.RunningMode.IMAGE, num_hands=1))
    # the HUD may already be streaming from the webcam; it drops the stream
    # as soon as it sees watching=true, but that takes a poll cycle — so
    # keep trying for a few seconds rather than failing the first attempt
    camera = None
    for attempt in range(12):
        camera = cv2.VideoCapture(0, _backend(cv2))
        if camera.isOpened():
            ok_test, _ = camera.read()
            if ok_test:
                break
        camera.release()
        camera = None
        time.sleep(0.35)
    if camera is None:
        announce.post("I couldn't open the camera to watch for signals — "
                      "something else has hold of it.")
        _running.clear()
        return

    recent: list[str] = []
    deadline = time.time() + minutes * 60
    try:
        while _running.is_set() and time.time() < deadline:
            ok, frame = camera.read()
            if not ok:
                time.sleep(0.2)
                continue
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = recogniser.recognize(image)
            top = ""
            if result.gestures and result.gestures[0]:
                best = result.gestures[0][0]
                if best.score >= CONFIDENCE:
                    top = best.category_name
            recent.append(top)
            recent[:] = recent[-WINDOW:]
            # hand the frame to the HUD from THIS capture — two processes
            # fighting over one webcam ends with neither getting it
            _state["hand"] = top
            stamp = time.time()
            if stamp - _state.get("published", 0) > 0.08:
                _state["published"] = stamp
                try:
                    import dashboard

                    ok_jpg, buf = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                    if ok_jpg:
                        dashboard.LATEST_JPEG = (stamp, buf.tobytes())
                except Exception:
                    pass

            for name in ("Open_Palm", "Thumb_Up", "Thumb_Down"):
                if recent.count(name) < HOLD_FRAMES:
                    continue
                now = time.time()
                if _state["last"] == name and now - _state["at"] < COOLDOWN:
                    continue
                _state.update(last=name, at=now, seen=_state["seen"] + 1)
                recent.clear()
                spoken = _act(name)
                try:
                    import main

                    main.log("heard", f"[signal] {name}")
                    if spoken:
                        main.log("said", spoken)
                except Exception:
                    pass
                if spoken and _speaker is not None:
                    try:
                        _speaker.say(spoken)
                    except Exception:
                        pass
                break
            time.sleep(0.03)
    except Exception:
        pass
    finally:
        try:
            camera.release()
        except Exception:
            pass
        _running.clear()


def start(minutes: float = DEFAULT_MINUTES, hud: bool = True) -> str:
    global _thread
    ok, why = available()
    if not ok:
        return f"I can't watch for hand signals — {why}."
    if _running.is_set():
        # He says "watch for hand signals" again to mean "turn it off" as
        # often as he says "stop watching" — treat the start phrase as a
        # toggle instead of making him rephrase.
        return stop()
    # stamped HERE, not in the loop: status() could be asked before the
    # thread got going and reported "29772851 minutes so far"
    _state.update(last="", at=0.0, seen=0, since=time.time())
    _running.set()
    _thread = threading.Thread(target=_loop, args=(minutes,), daemon=True)
    _thread.start()
    if hud:
        threading.Thread(target=open_hud, daemon=True).start()
    return (f"Watching for hand signals for {int(minutes)} minutes. Palm up "
            f"stops me talking, thumbs up or down answers me. Say stop "
            f"watching when you're done.")


def stop() -> str:
    if not _running.is_set():
        return "I wasn't watching for signals."
    _running.clear()
    seen = _state.get("seen", 0)
    return ("Camera's off." if not seen else
            f"Camera's off — I picked up {seen} signal"
            f"{'s' if seen != 1 else ''}.")


def status() -> str:
    if not _running.is_set():
        ok, why = available()
        return ("Not watching. Say watch for signals to start."
                if ok else f"Hand signals aren't available — {why}.")
    mins = (time.time() - _state["since"]) / 60
    return (f"Watching for signals — {mins:.0f} minutes so far, "
            f"{_state['seen']} picked up.")
