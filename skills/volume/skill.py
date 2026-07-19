from pycaw.pycaw import AudioUtilities

DESCRIPTION = ("Read or change SPEAKER sound volume, or mute/unmute the speakers. "
               "E.g. 'set volume to 40', 'turn it down' (level '-15'), 'mute'. "
               "NOT for screen brightness and NOT for the microphone — those are "
               "different skills.")
ARGS = {"level": "0-100 to set, +N or -N to nudge, 'mute', 'unmute', or 'get' to just read it"}


def _endpoint():
    return AudioUtilities.GetSpeakers().EndpointVolume


def run(args: dict) -> str:
    vol = _endpoint()
    level = str(args.get("level", "get")).strip().lower().rstrip("%")
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
