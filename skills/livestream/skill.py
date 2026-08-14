"""Start and — crucially — STOP the live stream by voice.

This skill exists because the stream could only be controlled from Telegram.
Saying "stop the live stream" in the room did nothing, which is a bad
property for a camera: the way to turn it off must be at least as easy as
the way to turn it on.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("LIVE STREAM the camera or the screens to his phone, and STOP "
               "it again. E.g. 'start a live stream', 'stream my screens', "
               "'share my screen to my phone', 'stop the live stream', 'turn "
               "the stream off', 'is the stream on'. Sends a link and a code "
               "to Telegram and closes itself after ten minutes. NOT a single "
               "photo (that's camera) and NOT the room watch (that's guard).")
ARGS = {"action": "'start' (default), 'stop', or 'status'",
        "source": "'camera' (default), 'screen' for both monitors, "
                  "'screen:left' or 'screen:right' for one"}


def run(args: dict) -> str:
    import livestream

    action = str(args.get("action") or "start").strip().lower()
    source = str(args.get("source") or "camera").strip().lower()

    if any(w in action for w in ("stop", "off", "end", "close", "cancel",
                                 "stand down", "kill")):
        return livestream.stop()
    if "status" in action or "is the" in action:
        return livestream.status()

    fps = str(args.get("fps") or "").strip()
    if fps.isdigit():
        return livestream.set_fps(int(fps))

    try:
        import tars_phone

        if not tars_phone.paired():
            return ("I can start a stream, but your phone isn't paired, so I "
                    "couldn't send you the link or the code.")
    except Exception:
        pass

    try:
        url, code = livestream.start(source)
    except Exception as e:
        # "an error occurred" told him nothing. Say what broke.
        livestream.stop(quiet=True)
        return f"The stream didn't start ({type(e).__name__}: {e})."
    if not code:
        return url          # already running, or it failed — url holds why
    try:
        import tars_phone

        tars_phone.send(url, force=True)
        tars_phone.send(f"Code: {code}\nCloses itself in "
                        f"{livestream.MINUTES} minutes.", force=True)
    except Exception:
        return f"Stream's up but I couldn't text you the link. Code is {code}."
    what = {"screen": "both your screens",
            "screen:left": "your left screen",
            "screen:right": "your right screen"}.get(source, "the room")
    return (f"Streaming {what}. Link and code are on your phone — it shuts "
            f"itself off in {livestream.MINUTES} minutes.")
