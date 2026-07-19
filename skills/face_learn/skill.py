"""'The person in the white shirt is Jacob' — TARS learns the face in view."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("LEARN a face through the camera and attach a name: 'the person in the "
               "white shirt is Jacob', 'this is my mate Luke', 'remember this face as "
               "Amy'. TARS will recognise them from then on.")
ARGS = {"name": "the person's name"}


def run(args: dict) -> str:
    name = (args.get("name") or "").strip().title()
    if not name:
        return "Whose name should I attach to this face?"
    import faces

    return faces.enroll(name)
