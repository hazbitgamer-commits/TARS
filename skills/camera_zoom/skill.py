"""'Zoom in' — digitally crop and enlarge the desk webcam view so TARS can
make out a face that's too small, too far away, or too dim to recognise
("I can't make out a face — more light, or come closer"). Persists in
camera_zoom.json and applies to every frame faces.py grabs from then on,
until zoomed back out or reset.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("ZOOM the desk webcam in or out to see a FACE more clearly — for low "
               "light or someone too far from the camera: 'zoom in', 'zoom in on my "
               "face', 'zoom in so you can see me better', 'zoom out', 'reset the "
               "zoom'. Digital crop-and-enlarge that helps face_learn/face_who see. "
               "NOT the dashboard map (map_view) and NOT 'what am I holding' (camera).")
ARGS = {"direction": "'in', 'out', or 'reset' — default 'in'"}


def run(args: dict) -> str:
    direction = (args.get("direction") or "in").strip().lower()
    import faces

    if direction.startswith("out"):
        return faces.zoom_out()
    if direction.startswith("reset") or direction in ("normal", "none"):
        return faces.zoom_reset()
    return faces.zoom_in()
