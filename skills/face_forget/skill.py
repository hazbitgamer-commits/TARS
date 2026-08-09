"""'Clear the name Emma from this database' — TARS forgets a learned face.

Removes that person's face signatures + reference photo from faces/faces.json
and faces/<name>.jpg. Their vault note under People/ (any facts Jacob told
TARS about them) is left untouched — this only clears face RECOGNITION data.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("DELETE / forget a name from the camera face recognition database, so "
               "TARS stops recognising that person on camera. E.g. 'clear the name "
               "Emma from this database', 'forget Luke's face', 'delete Jacob from "
               "the face database', 'remove that person you learned'. NOT for "
               "learning a new face (face_learn) or asking who's on camera (face_who).")
ARGS = {"name": "the person's name to remove from the face database"}


def run(args: dict) -> str:
    name = (args.get("name") or "").strip().strip(".,!?")
    if not name:
        return "Whose face should I forget?"

    import faces

    if name.lower() in ("all", "everyone", "all names", "everybody"):
        known = faces.known_names()
        if not known:
            return "There's nobody in my face database to clear."
        for person in known:
            faces.forget(person)
        return (f"Cleared all {len(known)} face"
                f"{'s' if len(known) != 1 else ''} — "
                f"{', '.join(known)} forgotten. Their vault notes are safe.")

    match = faces.find_name(name)
    if not match:
        known = faces.known_names()
        if known:
            return f"I don't have anyone called {name} — I only know {', '.join(known)}."
        return "I don't have anyone learned in my face database yet."

    return faces.forget(match)
