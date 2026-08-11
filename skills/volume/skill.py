"""Speaker volume — the same commands on every OS.

The whole skill used to be `from pycaw...` at import time, which meant on
a Mac it didn't degrade, it vanished (and the owner's mates would have found
"turn it down" simply missing). macOS gets the same behaviour through
osascript, which is built in.
"""
import subprocess
import sys

DESCRIPTION = ("Read or change SPEAKER sound volume, or mute/unmute the speakers. "
               "E.g. 'set volume to 40', 'turn it down' (level '-15'), 'mute'. "
               "NOT for screen brightness and NOT for the microphone — those are "
               "different skills.")
ARGS = {"level": "0-100 to set, +N or -N to nudge, 'mute', 'unmute', or 'get' to just read it"}

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


# ---------- Windows ----------
def _win_endpoint():
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


# ---------- macOS ----------
def _osa(script: str) -> str:
    out = subprocess.run(["osascript", "-e", script],
                         capture_output=True, text=True, timeout=10)
    return (out.stdout or "").strip()


def _mac_get() -> int:
    try:
        return int(_osa("output volume of (get volume settings)") or 0)
    except ValueError:
        return 0


def run(args: dict) -> str:
    level = str(args.get("level", "get")).strip().lower().rstrip("%")

    if IS_MAC:
        current = _mac_get()
        if level == "mute":
            _osa("set volume with output muted")
            return "Muted."
        if level == "unmute":
            _osa("set volume without output muted")
            return "Unmuted."
        if level.startswith(("+", "-")) and level[1:].isdigit():
            new = max(0, min(100, current + int(level)))
        elif level.isdigit():
            new = max(0, min(100, int(level)))
        else:
            return f"Volume is at {current} percent."
        _osa(f"set volume output volume {new}")
        _osa("set volume without output muted")
        return f"Volume {new} percent."

    if not IS_WIN:  # Linux
        try:
            if level.isdigit():
                subprocess.run(["amixer", "-q", "sset", "Master", f"{level}%"],
                               timeout=10)
                return f"Volume {level} percent."
            if level in ("mute", "unmute"):
                subprocess.run(["amixer", "-q", "sset", "Master",
                                "mute" if level == "mute" else "unmute"],
                               timeout=10)
                return "Muted." if level == "mute" else "Unmuted."
        except Exception:
            pass
        return "I can't reach the volume control on this machine."

    vol = _win_endpoint()
    current = round(vol.GetMasterVolumeLevelScalar() * 100)
    if level == "mute":
        vol.SetMute(True, None)
        return "Muted."
    if level == "unmute":
        vol.SetMute(False, None)
        return "Unmuted."
    if level.startswith(("+", "-")) and level[1:].isdigit():
        new = max(0, min(100, current + int(level)))
    elif level.isdigit():
        new = max(0, min(100, int(level)))
    else:
        return f"Volume is at {current} percent."

    vol.SetMasterVolumeLevelScalar(new / 100, None)
    vol.SetMute(False, None)
    return f"Volume {new} percent."
