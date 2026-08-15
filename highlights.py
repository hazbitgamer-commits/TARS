"""Catching the good bits of a game without anyone remembering to record.

The problem with every clip button ever made is that you press it AFTER the
thing happened, and by then it's gone. So this keeps the last half-minute of
the screen in memory at all times while he's in a game — a loop that's
constantly overwriting itself — and when something good happens the footage
is already there. Saying "clip that" just tells it which thirty seconds to
keep.

It also has a go at spotting the moment by itself, by listening to what the
PC is playing. A goal, a win, a kill — they're all sudden and loud against
whatever the game normally sounds like. That's a rough heuristic and it's
honest about being one: it compares the current loudness against a rolling
baseline of the last minute, so a quiet game and a noisy one both work, but
it will occasionally clip somebody shouting. "Clip that" is the reliable
path; the automatic one is a bonus that costs nothing to ignore.

Nothing here runs unless a game is actually in the foreground — game_watch
already works that out for the session nudges, and the same answer is reused
rather than guessed at again.
"""
import threading
import time
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parent
CLIPS = BASE / "clips"

# 8, not 12. Grabbing a 2560x1440 screen costs about 29ms no matter what
# size it's scaled to afterwards — the grab dominates, so frame rate is the
# only lever. At 12fps that was ~40% of a core burning the whole time he
# played, for footage nobody watches frame-by-frame.
FPS = 8
SECONDS = 25             # how much is always in memory
WIDTH = 854
QUALITY = 50
COOLDOWN = 90            # seconds between automatic clips, so it can't spam
LOUD_FACTOR = 2.6        # this much above the recent normal counts as a moment
LOUD_FLOOR = 0.06        # ...and it has to be genuinely loud, not 2.6x silence
BASELINE_SECONDS = 60
KEEP_CLIPS = 40
# Telegram takes 50MB from a bot, but a 29MB clip over a home connection
# WHILE he's gaming takes minutes. Anything bigger than this is left on the
# PC and he's told where it is, rather than pretending to send it.
MAX_SEND_MB = 20

_frames = deque(maxlen=FPS * SECONDS)
_loudness = deque(maxlen=int(BASELINE_SECONDS * 2))    # one every half second
_state = {"on": True, "last_clip": 0.0, "made": 0, "listening": False}
_lock = threading.Lock()


def _gaming() -> bool:
    try:
        import game_watch

        return bool(game_watch.in_session())
    except Exception:
        return False


def _record() -> None:
    """Keep the last SECONDS of screen in memory, and nothing else."""
    import cv2
    import mss
    import numpy as np

    gap = 1.0 / FPS
    with mss.mss() as sct:
        while True:
            started = time.time()
            try:
                if not _state["on"] or not _gaming():
                    _frames.clear()          # not playing — hold nothing
                    time.sleep(2.0)
                    continue
                shot = np.array(sct.grab(sct.monitors[1]))[:, :, :3]
                height = int(shot.shape[0] * WIDTH / shot.shape[1])
                small = cv2.resize(np.ascontiguousarray(shot), (WIDTH, height))
                ok, buf = cv2.imencode(".jpg", small,
                                       [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
                if ok:
                    _frames.append((time.time(), buf.tobytes()))
            except Exception:
                time.sleep(1.0)
            # sleep only what's left, or the frame rate quietly halves
            time.sleep(max(0.0, gap - (time.time() - started)))


def _listen() -> None:
    """Watch how loud the game is, and notice when it jumps."""
    try:
        import numpy as np
        import pyaudiowpatch as pa
    except Exception:
        return                                # no loopback here; manual only

    while True:
        try:
            audio = pa.PyAudio()
            speaker = audio.get_default_wasapi_loopback()
            rate = int(speaker["defaultSampleRate"])
            stream = audio.open(format=pa.paInt16, channels=1, rate=rate,
                                input=True, input_device_index=speaker["index"],
                                frames_per_buffer=1024)
            _state["listening"] = True
            while True:
                chunk = stream.read(rate // 2, exception_on_overflow=False)
                if not _state["on"] or not _gaming():
                    _loudness.clear()
                    continue
                block = np.frombuffer(chunk, np.int16).astype(np.float32) / 32768
                level = float(np.sqrt((block ** 2).mean()))
                # compare against the recent normal BEFORE adding this one,
                # or a loud moment quietly raises its own bar
                if len(_loudness) >= 20:
                    normal = float(np.median(_loudness))
                    if level > LOUD_FLOOR and level > normal * LOUD_FACTOR:
                        _maybe_clip("that sounded like a moment")
                _loudness.append(level)
        except Exception:
            _state["listening"] = False
            time.sleep(30)                    # device changed, headphones out


def _maybe_clip(reason: str) -> None:
    if time.time() - _state["last_clip"] < COOLDOWN:
        return
    threading.Thread(target=lambda: save(reason, send=True), daemon=True).start()


def save(reason: str = "", send: bool = False, seconds: int = SECONDS) -> str:
    """Write what's in memory to a real file. Returns what to say."""
    import cv2
    import numpy as np

    with _lock:
        frames = [f for f in _frames]
    if not frames:
        if not _gaming():
            return ("I only keep the last half minute while you're in a game, "
                    "and you're not in one right now.")
        return "I haven't got anything buffered yet — give it a few seconds."

    cutoff = time.time() - seconds
    frames = [f for f in frames if f[0] >= cutoff]
    if len(frames) < FPS:
        return "There isn't enough footage yet to make a clip."

    _state["last_clip"] = time.time()
    CLIPS.mkdir(exist_ok=True)
    path = CLIPS / (time.strftime("%Y-%m-%d_%H%M%S") + ".mp4")
    first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
    height, width = first.shape[:2]
    # H.264 where it exists, which it does here: the same 30 seconds came
    # out 29MB as mp4v and about a fifth of that as avc1. mp4v is kept as a
    # fallback so a machine without the codec still gets a clip.
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"avc1"),
                             FPS, (width, height))
    if not writer.isOpened():
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                 FPS, (width, height))
    try:
        for _, jpeg in frames:
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                writer.write(frame)
    finally:
        writer.release()
    _state["made"] += 1
    _tidy()

    length = round(frames[-1][0] - frames[0][0])
    size = path.stat().st_size / 1e6

    # NEVER upload on the caller's thread. This is called from a skill, which
    # runs on the conversation loop, and that loop stops the microphone
    # before it speaks. A 29MB upload over a gaming connection took minutes,
    # and for every one of them TARS was alive, answering the dashboard, and
    # completely deaf — the mic was never restarted because the reply never
    # finished. One slow upload cost the whole assistant.
    if send and size <= MAX_SEND_MB:
        def deliver():
            try:
                import tars_phone

                tars_phone.send_video(
                    path, caption=(reason or "Clip") + f" — {length}s")
            except Exception:
                pass

        threading.Thread(target=deliver, daemon=True).start()
        return f"Clipped the last {length} seconds — sending it to your phone."
    if send:
        return (f"Clipped the last {length} seconds, but it's {size:.0f}MB — "
                f"too big to send without tying things up. It's in the clips "
                f"folder.")
    return f"Clipped the last {length} seconds — saved to clips."


def _tidy() -> None:
    clips = sorted(CLIPS.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    for old in clips[:-KEEP_CLIPS]:
        try:
            old.unlink()
        except OSError:
            pass


def turn(on: bool) -> str:
    _state["on"] = on
    if on:
        return ("Highlights on — I'll keep the last 30 seconds while you're "
                "in a game, so you can say 'clip that' whenever.")
    _frames.clear()
    return "Highlights off — I'll stop keeping the last 30 seconds."


def status() -> str:
    if not _state["on"]:
        return "Highlights are off."
    made = _state["made"]
    clips = len(list(CLIPS.glob("*.mp4"))) if CLIPS.exists() else 0
    where = ("and I'm listening for big moments" if _state["listening"]
             else "though I can't hear the game, so say 'clip that' yourself")
    if not _gaming():
        return (f"Highlights are on, but you're not in a game so I'm not "
                f"keeping anything. {clips} clips saved.")
    return (f"Highlights are on — I've got the last "
            f"{round(len(_frames) / FPS)} seconds in memory, {where}. "
            f"{made} clipped this session, {clips} saved.")


def start() -> None:
    threading.Thread(target=_record, daemon=True).start()
    threading.Thread(target=_listen, daemon=True).start()
