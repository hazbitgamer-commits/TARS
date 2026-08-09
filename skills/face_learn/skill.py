"""'The person in the white shirt is Jacob' — TARS learns the face in view."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("LEARN a face through the camera and attach a name: 'the person in the "
               "white shirt is Jacob', 'this is my mate Luke', 'the girl in the "
               "background is Emma'. Say which person if several are in shot "
               "(background/left/right/closest). TARS recognises them from then on.")
ARGS = {"name": "the person's name",
        "which": "which face if several are visible: 'background', 'left', "
                 "'right', 'closest' — or a description like 'the one behind me'"}

# never learn TARS's own name, or a vocative, as a person
NOT_NAMES = {"Tars", "Hey", "Hey Tars", "You", "Me", "That", "This", "Him",
             "Her", "Someone", "Person", "Girl", "Boy", "Man", "Woman"}


def run(args: dict) -> str:
    name = (args.get("name") or "").strip().strip(".,!?").title()
    for junk in ("Hey Tars", "Tars,", "Tars"):  # "That's me, TARS. I'm Jacob."
        if name.startswith(junk + " "):
            name = name[len(junk) + 1:].strip()
    if name in NOT_NAMES or len(name) < 2:
        return ("That didn't sound like a name — say it as, for example, "
                "'the person in the background is Emma'.")
    import faces

    return faces.enroll(name, which=str(args.get("which") or ""))
