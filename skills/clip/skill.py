"""Keeping the last thirty seconds of a game.

The footage already exists — highlights.py is always holding the last half
minute while he plays. This is just the bit that says "keep that one".
"""
DESCRIPTION = (
    "Save and send a clip of what just happened in a game. Use for 'clip "
    "that', 'save that', 'did you get that', 'clip the last 30 seconds', "
    "'send me that clip'. Also 'highlights off' / 'highlights on' and 'are "
    "you recording'. TARS always holds the last 30 seconds while a game is "
    "open, so this catches something that has ALREADY happened. NOT for "
    "starting a live stream (that's livestream) and NOT for a still "
    "screenshot (that's screenshot).")
ARGS = {
    "action": "'clip' (the default), 'on', 'off', or 'status'",
    "seconds": "how far back to keep, up to 30",
}


def run(args: dict) -> str:
    import highlights

    action = str(args.get("action") or "clip").lower().strip()
    if action in ("off", "stop", "disable"):
        return highlights.turn(False)
    if action in ("on", "start", "enable"):
        return highlights.turn(True)
    if action == "status":
        return highlights.status()

    try:
        seconds = int(float(args.get("seconds") or highlights.SECONDS))
    except (TypeError, ValueError):
        seconds = highlights.SECONDS
    return highlights.save("Clip", send=True,
                           seconds=max(5, min(highlights.SECONDS, seconds)))
