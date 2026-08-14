"""Open the setup page — the one holding his name, school login, phone
number and saved website logins.

It exists because that page had no way in. It opened itself once, on the
very first install, and after that the only way to reach it was to know the
address by heart. Asking TARS out loud got "did you mean to set up a new
device?", which is a fair guess and completely useless.

Now it's where every other page is: ask for it.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("OPEN THE SETUP PAGE — his own details: name, city, email, "
               "school portal login, phone number, Twilio keys, and the "
               "saved website logins TARS fills in for him. E.g. 'open "
               "setup', 'open my settings', 'I want to change my details', "
               "'add a login', 'save a password', 'where do I put my "
               "password'. NOT the dashboard home page (that's "
               "open_dashboard) and NOT setting up a new device or gadget.")
ARGS = {"confirmed": "leave empty — the brain sets 'true' only after the owner says yes"}

REOPEN_WINDOW = 20  # a second ask this soon is usually an accidental repeat
_last_opened = 0.0


def run(args: dict) -> str:
    global _last_opened

    now = time.time()
    if (str(args.get("confirmed", "")).lower() != "true"
            and now - _last_opened < REOPEN_WINDOW):
        return ("__CONFIRM__open_setup__I just opened that — want it "
                "again?")

    import tars_window

    tars_window.open_page("setup", 760, 950)
    _last_opened = now
    return ("Setup's open — your details, and the website logins I fill in "
            "for you.")
