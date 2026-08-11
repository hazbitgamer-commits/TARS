import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("Open the TARS dashboard home page in its own TARS window — status, "
               "timers, personality sliders, activity, skills, brain stats.")
ARGS = {"confirmed": "leave empty — the brain sets 'true' only after the owner says yes"}

REOPEN_WINDOW = 20  # seconds — a second "open the dashboard" this soon is
# probably an accidental repeat (double command, misheard echo), not a real ask
_last_opened = 0.0


def run(args: dict) -> str:
    global _last_opened

    now = time.time()
    if (str(args.get("confirmed", "")).lower() != "true"
            and now - _last_opened < REOPEN_WINDOW):
        return ("__CONFIRM__open_dashboard__I just opened that — want me to "
                 "bring it up again?")

    import tars_window

    tars_window.open_page("")
    _last_opened = now
    return "Dashboard's up."
