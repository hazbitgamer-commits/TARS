"""Open TARS's OWN pages (dashboard, brain, camera) as chromeless app
windows — part of the TARS app, not tabs in Jacob's browser. External
websites still open in the normal browser; this is only for 127.0.0.1:8765."""
import os
import subprocess
from pathlib import Path


def open_page(path: str = "", width: int = 1100, height: int = 760) -> bool:
    url = f"http://127.0.0.1:8765/{path.lstrip('/')}"
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
