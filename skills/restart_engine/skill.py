"""Full self-restart: close the dashboard window, kill TARS's own engine
process, then start it fresh (which reopens the dashboard automatically —
see boot.py). NOT a shutdown (that's 'goodbye tars', handled in main.py) —
this always comes back up on its own.

How it works: this code runs INSIDE the live engine process, so it can't
just kill itself and then start a new copy — it would die before the owner's
spoken confirmation ever got played, and nothing would be left alive to
launch the replacement. Instead it closes the dashboard window immediately,
then hands off to a small detached helper script (_do_restart.py) that:
  1. waits a few seconds so TARS finishes saying "restarting now"
  2. force-kills this engine by PID
  3. runs TARS.bat again, exactly like clicking the desktop icon
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]  # the tars folder, wherever it is
HELPER = Path(__file__).resolve().parent / "_do_restart.py"

DESCRIPTION = ("Fully restart TARS: close the dashboard window, restart the engine "
               "process itself, then reopen the dashboard once it's back up. "
               "E.g. 'restart yourself', 'restart your engine', 'reboot yourself'. "
               "NOT for shutting down for good (say 'goodbye TARS' for that) and "
               "NOT for just closing one window (that's close_window).")
ARGS = {}


def _close_dashboard_windows() -> int:
    """Close TARS's own chromeless app windows (dashboard/brain/camera feed) —
    they all have window titles starting with 'TARS' (see tars_window.py)."""
    closed = 0
    try:
        import pygetwindow
    except Exception:
        return 0
    for win in pygetwindow.getAllWindows():
        title = (win.title or "").strip()
        if title.lower().startswith("tars"):
            try:
                win.close()
                closed += 1
            except Exception:
                pass
    return closed


def run(args: dict) -> str:
    pid = os.getpid()
    _close_dashboard_windows()

    try:
        subprocess.Popen(
            [sys.executable, str(HELPER), str(pid), str(BASE)],
            cwd=str(BASE),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception as e:
        return f"I couldn't kick off the restart: {e}"

    return "Restarting my engine now. I'll be back in a few seconds."
