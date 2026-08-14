"""Looking at the room, or the screen, from wherever he happens to be.

This is the answer to "can I watch a live stream from anywhere" that doesn't
involve putting his bedroom on the public internet: he asks, TARS takes a
photo or a few seconds of video, and Telegram delivers it. It works from
school, from a mate's house, from anywhere with signal, and it exposes
nothing — the PC only ever makes outbound connections, exactly as it does
for every other message.

A stream is only better than this when he wants to WATCH something unfold.
For "is the dog on my bed", "did I leave the light on", "what's on my
screen" — which is nearly always what it's actually for — a photo arriving
in two seconds is better, not worse.

The camera rule still applies: nothing here runs unless he asks for it in
words, and every capture is a single deliberate act with a definite end.
Nothing records continuously and nothing is kept beyond the send.
"""
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "workshop" / "remote"
CLIP_SECONDS = 6
CLIP_FPS = 10


def _fresh(name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT / f"{name}-{int(time.time())}"


def photo() -> tuple[Path | None, str]:
    """One frame from the desk camera."""
    try:
        import cv2

        import faces

        frame = faces.get_frame()
        if frame is None:
            return None, ("The camera didn't answer — something else may be "
                          "using it.")
        path = _fresh("room").with_suffix(".jpg")
        cv2.imwrite(str(path), frame)
        return path, f"Your room, {time.strftime('%H:%M')}."
    except Exception as e:
        return None, f"I couldn't get a photo ({type(e).__name__})."


def clip(seconds: int = CLIP_SECONDS) -> tuple[Path | None, str]:
    """A few seconds of video — the honest middle ground between a photo and
    a live stream. Long enough to see whether something is moving."""
    try:
        import cv2

        import faces

        first = faces.get_frame()
        if first is None:
            return None, "The camera didn't answer."
        height, width = first.shape[:2]
        path = _fresh("clip").with_suffix(".mp4")
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                                 CLIP_FPS, (width, height))
        if not writer.isOpened():
            return None, "I couldn't start recording on this PC."
        frames = max(1, int(seconds * CLIP_FPS))
        delay = 1.0 / CLIP_FPS
        for _ in range(frames):
            frame = faces.get_frame()
            if frame is not None:
                writer.write(frame)
            time.sleep(delay)
        writer.release()
        if not path.exists() or path.stat().st_size < 1000:
            return None, "The recording came out empty."
        return path, f"{seconds} seconds from your room, {time.strftime('%H:%M')}."
    except Exception as e:
        return None, f"I couldn't record a clip ({type(e).__name__})."


def screen(which: str = "") -> tuple[Path | None, str]:
    """What's on the PC screen right now."""
    try:
        import mss

        with mss.mss() as sct:
            # left-to-right by actual position. Windows lists the primary
            # display first wherever it physically sits, so going by index
            # handed him the wrong monitor.
            screens = sorted(sct.monitors[1:] or sct.monitors[:1],
                             key=lambda m: m["left"])
            want = (which or "").strip().lower()
            if want in ("left", "1") and screens:
                target = screens[0]
            elif want in ("right", "2") and len(screens) > 1:
                target = screens[-1]
            else:
                target = sct.monitors[0]        # everything, side by side
            shot = sct.grab(target)
            path = _fresh("screen").with_suffix(".png")
            mss.tools.to_png(shot.rgb, shot.size, output=str(path))
        return path, f"Your screen, {time.strftime('%H:%M')}."
    except Exception as e:
        return None, f"I couldn't grab the screen ({type(e).__name__})."


def tidy(keep: int = 12) -> None:
    """These are throwaway. Keep the last few for a re-send, bin the rest —
    a folder of silent recordings of his bedroom is not something to
    accumulate."""
    try:
        files = sorted(OUT.glob("*"), key=lambda p: -p.stat().st_mtime)
        for old in files[keep:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
