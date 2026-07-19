"""'Who is this?' — TARS names the faces it can see."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Say WHO is on camera by recognising known faces: 'who is this', "
               "'who can you see', 'who's in the room', 'is that Jacob'.")
ARGS = {}


def run(args: dict) -> str:
    import faces

    seen = faces.identify()
    if not seen:
        return "I can't see any faces right now."
    named = [s["name"] for s in seen if s["name"]]
    unknown = sum(1 for s in seen if not s["name"])
    parts = []
    if named:
        parts.append("I can see " + " and ".join(named))
    if unknown:
        who = f"{unknown} people" if unknown > 1 else "someone"
        parts.append(f"{who} I don't recognise — introduce us and I'll remember")
    return (". ".join(parts) + ".").replace("..", ".")
