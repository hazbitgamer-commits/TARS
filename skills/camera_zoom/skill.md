# camera_zoom
Digitally zooms the desk webcam in or out so TARS can make out a face that's too
far away or too dim ("I can't make out a face — more light, or come closer").
Crops the center of every frame and scales it back up before face detection
(faces.py) uses it — no physical PTZ, the webcam doesn't have one. Level is
saved in camera_zoom.json (1.0-3.0, default 1.0) and stays until zoomed back
out or reset.
**Say:** "zoom in" / "zoom in on my face" / "zoom out" / "reset the zoom"
**Args:** `direction` — 'in', 'out', or 'reset'.
