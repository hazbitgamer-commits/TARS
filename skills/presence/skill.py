"""Arming and disarming the watch for whether he's at the desk.

Armed only. The camera does nothing until he says so, and one sentence turns
it off again — the same shape as the room guard, for the same reason.
"""
DESCRIPTION = (
    "Turn on or off TARS noticing whether the owner is at his desk, using "
    "the camera. Use for 'watch for me', 'keep an eye out for me', 'lock my "
    "pc when i leave', 'pause my music when i walk away', 'stop watching', "
    "'are you watching for me'. When on, it pauses what's playing when he "
    "leaves, locks the screen after five minutes, welcomes him back by name "
    "and says who came in. It NEVER unlocks the PC. NOT the room guard for "
    "intruders (that's guard) and NOT a live video feed (that's livestream).")
ARGS = {
    "action": "'on', 'off', or 'status'",
    "lock": "optional true/false — lock the screen when he's away",
    "pause": "optional true/false — pause what's playing when he's away",
    "greet": "optional true/false — say hello when he comes back",
}


def _flag(args, key):
    if key not in args or args[key] in (None, ""):
        return None
    value = args[key]
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "on", "1")


def run(args: dict) -> str:
    import presence

    action = str(args.get("action") or "").lower().strip()
    lock, pause, greet = (_flag(args, "lock"), _flag(args, "pause"),
                          _flag(args, "greet"))

    if action in ("on", "start", "enable", "arm"):
        answer = presence.turn(True)
        if any(f is not None for f in (lock, pause, greet)):
            presence.settings(lock, pause, greet)
        return answer
    if action in ("off", "stop", "disable", "disarm"):
        return presence.turn(False)
    if any(f is not None for f in (lock, pause, greet)):
        return presence.settings(lock, pause, greet)
    return presence.status()
