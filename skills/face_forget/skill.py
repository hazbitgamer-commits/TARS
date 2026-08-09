"""'Clear the name Emma from this database' — TARS forgets a learned face.

Removes that person's face signatures + reference photo from faces/faces.json
and faces/<name>.jpg. Their vault note under People/ (any facts Jacob told
TARS about them) is left untouched — this only clears face RECOGNITION data.

Deleting is irreversible (short of relearning the face from scratch), so a
repeat of the same forget within REPEAT_WINDOW — a misheard echo, a double
wake, a second stray command that lands on the same name — needs a spoken
yes rather than silently firing again. A fresh name, or the same name after
the window passes, still runs straight away.
"""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("DELETE / forget a name from the camera face recognition database, so "
               "TARS stops recognising that person on camera. E.g. 'clear the name "
               "Emma from this database', 'forget Luke's face', 'delete Jacob from "
               "the face database', 'remove that person you learned'. NOT for "
               "learning a new face (face_learn) or asking who's on camera (face_who).")
ARGS = {"name": "the person's name to remove from the face database",
        "confirmed": "leave empty — the brain sets 'true' only after Jacob says yes"}

REPEAT_WINDOW = 30  # seconds — a second forget of the SAME name this soon is
# probably an accidental repeat, not a fresh intentional ask
_last_forgotten = (None, 0.0)  # (name.lower(), timestamp)


def run(args: dict) -> str:
    global _last_forgotten

    name = (args.get("name") or "").strip().strip(".,!?")
    if not name:
        return "Whose face should I forget?"

    import faces

    confirmed = str(args.get("confirmed", "")).lower() == "true"
    key = name.lower()
    now = time.time()
    if not confirmed and _last_forgotten[0] == key and now - _last_forgotten[1] < REPEAT_WINDOW:
        return (f"__CONFIRM__face_forget:{name}__I just cleared {name} from the "
                f"face database — say yes if you really mean to do that again.")

    if key in ("all", "everyone", "all names", "everybody"):
        known = faces.known_names()
        if not known:
            return "There's nobody in my face database to clear."
        for person in known:
            faces.forget(person)
        _last_forgotten = (key, now)
        return (f"Cleared all {len(known)} face"
                f"{'s' if len(known) != 1 else ''} — "
                f"{', '.join(known)} forgotten. Their vault notes are safe.")

    match = faces.find_name(name)
    if not match:
        known = faces.known_names()
        if known:
            return f"I don't have anyone called {name} — I only know {', '.join(known)}."
        return "I don't have anyone learned in my face database yet."

    result = faces.forget(match)
    _last_forgotten = (key, now)
    return result
