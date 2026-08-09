"""Open the Mini CAD apps the big brain built in the workshop — first-class
citizens now, because "Open CAD" fell through to 'nothing installed by
that name' while mini_cad_3d.py sat right there."""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
APPS = {"3d": BASE / "workshop" / "mini_cad_3d.py",
        "2d": BASE / "workshop" / "mini_cad.py"}

DESCRIPTION = ("Open TARS's own Mini CAD design app — 'open CAD', 'open the "
               "CAD app', 'open mini CAD 3D', 'let me draw some shapes'. "
               "The 3D version (default) has the Convert-to-3D button; say "
               "'the 2D one' for the original. NOT for opening other "
               "people's CAD software.")
ARGS = {"which": "'3d' (default) or '2d'"}


def run(args: dict) -> str:
    which = "2d" if "2" in str(args.get("which", "3d")) else "3d"
    app = APPS[which]
    if not app.exists():
        other = APPS["2d" if which == "3d" else "3d"]
        if other.exists():
            app, which = other, ("2d" if which == "3d" else "3d")
        else:
            return "I can't find the Mini CAD files in my workshop anymore."
    python = str(app.parent.parent / "runtime" /
                 ("pythonw.exe" if sys.platform == "win32" else "python3"))
    if sys.platform != "win32":
        python = sys.executable or "python3"
    try:
        subprocess.Popen([python, "-s", str(app)], cwd=str(app.parent))
    except OSError:
        return "The CAD app wouldn't start — its file may be damaged."
    return (f"Mini CAD {which.upper()} is opening — draw on the grid"
            + (" and hit Convert to 3D when you're ready."
               if which == "3d" else "."))
