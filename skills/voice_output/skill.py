"""Switch which speakers TARS's own voice comes out of (the PC's outputs —
the Nest speakers are a different skill)."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Switch which PC speakers TARS's VOICE comes out of: the monitor "
               "(Lenovo screen speakers), headphones, or the Quest. Also lists "
               "outputs. E.g. 'speak through the monitor speakers', 'switch your "
               "voice back to my headphones'.")
ARGS = {"target": "'monitor', 'headphones', 'quest', or part of a device name — "
                  "or 'list' to hear the options"}


def run(args: dict) -> str:
    import audio_out

    target = (args.get("target") or "").strip().lower()
    if not target or target == "list":
        names = ", ".join(n for _, n in audio_out.outputs())
        return f"I can speak through: {names}."
    name = audio_out.set_output(target)
    if name is None:
        return f"I can't find an output matching {target}. Say 'list voice outputs' to hear them."
    return f"Voice moved to {name.strip()}. Testing, testing."
