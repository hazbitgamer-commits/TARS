import datetime
from pathlib import Path

from mss import mss

DESCRIPTION = "Take a screenshot of the screen and save it to the Pictures folder."
ARGS = {}


def run(args: dict) -> str:
    out_dir = Path.home() / "Pictures" / "TARS"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"screenshot-{stamp}.png"
    with mss() as grabber:
        grabber.shot(mon=1, output=str(path))
    return "Screenshot saved to your Pictures folder, under TARS."
