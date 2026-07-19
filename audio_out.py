"""Where TARS's voice comes out. Persisted in audio_out.json; applied at
startup and switchable by voice ("speak through the monitor speakers")."""
import json
from pathlib import Path

import sounddevice as sd

FILE = Path(__file__).parent / "audio_out.json"

# generic words → device-name fragments (virtual junk excluded for these)
ALIASES = {
    "monitor": ("g27",), "screen": ("g27",), "lenovo": ("g27",), "display": ("g27",),
    "headphones": ("headphones",), "headset": ("headphones",),
    "quest": ("oculus",), "oculus": ("oculus",),
}
VIRTUAL_JUNK = ("steam", "dualsense", "virtual", "sound mapper")


def outputs() -> list[tuple[int, str]]:
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["max_output_channels"] > 0 and d["hostapi"] == 0
            and "sound mapper" not in d["name"].lower()]


def resolve(target: str) -> tuple[int | None, str | None]:
    t = target.strip().lower()
    fragments = ALIASES.get(t, (t,))
    allow_virtual = t in ("quest", "oculus") or not ALIASES.get(t)
    for i, name in outputs():
        low = name.lower()
        if not allow_virtual and any(j in low for j in VIRTUAL_JUNK):
            continue
        if any(f in low for f in fragments):
            return i, name
    return None, None


def set_output(target: str) -> str | None:
    idx, name = resolve(target)
    if idx is None:
        return None
    current = sd.default.device
    sd.default.device = (current[0] if isinstance(current, (list, tuple)) else None, idx)
    FILE.write_text(json.dumps({"target": target, "name": name}), encoding="utf-8")
    return name


MIC_PREFER = ("hd-3000", "desktop microphone")  # the LifeCam — never a gamepad


def pick_input() -> int | None:
    """The index of the mic TARS should use — pinned to the LifeCam, so a
    freshly connected DualSense/headset can't hijack the default input."""
    candidates = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0 or d["hostapi"] != 0:
            continue
        low = d["name"].lower()
        if any(j in low for j in VIRTUAL_JUNK) or "sound mapper" in low:
            continue
        if any(f in low for f in MIC_PREFER):
            return i
        if "dualsense" not in low and "oculus" not in low:
            candidates.append(i)
    return candidates[0] if candidates else None


def apply_saved() -> None:
    try:
        saved = json.loads(FILE.read_text(encoding="utf-8"))
        set_output(saved.get("target", ""))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
