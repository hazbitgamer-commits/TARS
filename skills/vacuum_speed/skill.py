"""Voice control of the eufy robot vacuum's suction/clean intensity."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Change how HARD the eufy robot vacuum cleans — its suction/fan "
               "speed — between quiet, medium, and hard/loud. E.g. 'make the "
               "vacuum quiet', 'set clean mode to medium', 'battle clean mode "
               "hard clean'. NOT for starting/pausing/docking the vacuum or "
               "single-room cleans — those are different skills.")
ARGS = {"speed": "'quiet', 'medium' (also 'standard'), 'hard' (also 'loud' or "
                 "'turbo'), or 'max'"}

SPEED_MAP = {
    "quiet": "Quiet", "silent": "Quiet", "low": "Quiet",
    "medium": "Standard", "standard": "Standard", "normal": "Standard",
    "hard": "Turbo", "loud": "Turbo", "turbo": "Turbo", "high": "Turbo",
    "max": "Max", "maximum": "Max", "boost": "Max",
}

SPOKEN_NAME = {"Quiet": "quiet", "Standard": "medium", "Turbo": "hard", "Max": "max"}


def run(args: dict) -> str:
    import eufy_vac

    raw = str(args.get("speed", "")).strip().lower()
    speed = SPEED_MAP.get(raw)
    if speed is None:
        return "For clean mode I can go quiet, medium, hard, or max — which one?"

    try:
        name = eufy_vac.run_sync(eufy_vac.set_fan_speed(speed))
        return f"{name} is now set to {SPOKEN_NAME[speed]} clean."
    except Exception as e:
        return str(e) if isinstance(e, RuntimeError) else f"The vacuum didn't answer: {e}"
