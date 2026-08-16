"""Open TARS's OWN pages (dashboard, brain, camera) as chromeless app
windows — part of the TARS app, not tabs in the owner's browser. External
websites still open in the normal browser; this is only for 127.0.0.1:8765."""
import os
import subprocess
from pathlib import Path


def open_page(path: str = "", width: int = 1100, height: int = 760) -> bool:
    """Show a page — in the dashboard that's already open, if there is one.

    This used to launch a browser window every single time. Ask for the
    camera, then the brain map, then setup, and you had three windows and
    three things to close, none of which knew about the others. His words:
    "i want everything to open on the main dashboard seamlessly... EVERYTHING
    is on 1 tab when i ask for it."

    So: if a dashboard tab is open, it's simply told what to show and the
    panel changes under him. Only when nothing is open does a window get
    launched — which is what that behaviour was always actually for.
    """
    try:
        import dashboard

        if dashboard.show(path):
            return True          # a tab was open and has been switched
    except Exception:
        pass                     # dashboard not up — fall through and launch

    # Nothing open, so launch — but launch the DASHBOARD, not the bare page.
    # dashboard.show() has already recorded which panel was wanted, so the
    # new tab lands on it a moment after it appears. Opening /hud directly
    # would give him the camera in a window with no way back to anything
    # else, which is the thing being fixed.
    url = "http://127.0.0.1:8765/"
    brave = (Path(os.environ.get("LOCALAPPDATA", ""))
             / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    exe = brave if brave.exists() else edge
    try:
        subprocess.Popen([str(exe), f"--app={url}",
                          f"--window-size={width},{height}"])
        return True
    except OSError:
        import webbrowser  # last resort: a normal tab beats nothing

        webbrowser.open(url)
        return False
