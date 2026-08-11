"""'Who is this?' — TARS names the faces it can see."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Say WHO is on camera by recognising known faces: 'who is this', "
               "'who can you see', 'who's in the room', 'is that the owner'.")
ARGS = {}


def run(args: dict) -> str:
    import faces

    seen = faces.identify()
    if not seen:
        return "I can't see any faces right now."
    # report EVERYONE, left to right — it used to say "I can see the owner"
    # with two people in frame
    seen = sorted(seen, key=lambda s: s.get("box", [0])[0])
    named = list(dict.fromkeys(s["name"] for s in seen if s["name"]))
    unknown = sum(1 for s in seen if not s["name"])
    if len(seen) > 1 and not unknown:
        return f"I can see {len(seen)} people: " + " and ".join(named) + "."
    parts = []
    if named:
        parts.append("I can see " + " and ".join(named))
    if unknown:
        who = f"{unknown} people" if unknown > 1 else "someone"
        parts.append(f"{who} I don't recognise — introduce us and I'll remember")
    return (". ".join(parts) + ".").replace("..", ".")
