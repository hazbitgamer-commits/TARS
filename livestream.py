"""A live view of his room, from anywhere — for ten minutes, behind a code,
and never quietly.

This is the one part of TARS that is reachable from the public internet, so
it is built to be the opposite of everything else here. The dashboard is
bound to the PC on purpose; the heartbeat can say exactly one word. This can
show his bedroom, so it gets the ceremony:

  1. OFF unless he asks. There is no schedule and nothing that starts it.
  2. A random link AND a separate six-digit code. A leaked link on its own
     shows nothing — the code arrives in a different message.
  3. It closes itself after ten minutes. Not "until he remembers": the
     tunnel dies, the port closes, the code is thrown away.
  4. It ANNOUNCES itself, out loud in the room, when it starts and stops.
     Nobody in the house can be watched without the room being told — that
     is the thing people rightly object to about cameras, and the whole
     reason it's built in rather than optional.

Nothing is recorded. Frames go straight out and are not kept.
"""
import random
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
CLOUDFLARED = BASE / "tools" / "cloudflared.exe"

MINUTES = 10
# the webcam tops out at 29.3 fps at 1280x720, so 30 is the real ceiling
# rather than a wish. At 640 wide / quality 55 that's about 250 KB/s, which
# is fine on wifi and heavy on mobile data — hence SLOW_FPS.
FPS = 30
SLOW_FPS = 12     # for "slow stream" when he's on mobile data
WIDTH = 640       # 1280 wide at quality 70 is 35KB a frame; this is ~8KB
QUALITY = 55
TAG_EVERY = 2.0   # seconds between re-identifying faces

# Screens need different numbers from a camera. His two monitors are
# 2560x1440 and 1080x1920 (portrait) — 3640x1920 side by side, which is
# mostly small text, so JPEG can't squeeze it the way it squeezes a face.
# Measured on his actual desktop, at 12 fps:
#     1280 wide, q45 -> 797 KB/s   too heavy for mobile data
#      960 wide, q45 -> 491 KB/s   readable, and survives a phone connection
#      800 wide, q45 -> 381 KB/s   cheap, but the text starts to go
# 960 it is. And 12 fps, because watching a screen isn't watching a room:
# nothing on a desktop needs thirty frames a second.
SCREEN_WIDTH = 960
SCREEN_QUALITY = 45
SCREEN_FPS = 12

_live = {"on": False, "code": "", "url": "", "port": 0, "until": 0.0,
         "server": None, "tunnel": None, "source": "camera", "fps": FPS}
# ONE capture for the whole stream, however many people are watching.
# faces.get_frame() opens the camera, throws away six frames to let the
# exposure settle and closes it again — 2.5 seconds a go. That is exactly
# right for a single photo and hopeless for video: the first version of
# this ran at well under one frame a second.
_latest = {"jpeg": b"", "at": 0.0}
_lock = threading.Lock()

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>TARS</title>
<style>body{{margin:0;background:#0b0e13;color:#9fb;font-family:system-ui;
text-align:center}}img{{max-width:100%;height:auto}}p{{opacity:.6;font-size:14px}}
input,button{{font-size:18px;padding:10px;border-radius:8px;border:1px solid #2a3;
background:#111;color:#9fb}}</style>
<h3>TARS — live</h3>{body}"""

ASK = """<form><p>Enter the code TARS sent you.</p>
<input name=c inputmode=numeric autocomplete=off autofocus>
<button>Watch</button></form>"""


def live() -> bool:
    return bool(_live["on"]) and time.time() < _live["until"]


def status() -> str:
    if not live():
        return "The live stream is off."
    left = int((_live["until"] - time.time()) / 60) + 1
    return f"Live now — about {left} minute{'s' if left != 1 else ''} left."


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _ok(self) -> bool:
        code = ""
        if "?" in self.path:
            import urllib.parse

            code = (urllib.parse.parse_qs(self.path.split("?", 1)[1])
                    .get("c", [""])[0])
        # constant-time compare: this is the only thing between the public
        # internet and a camera in his bedroom
        return bool(_live["code"]) and secrets.compare_digest(
            str(code), str(_live["code"]))

    def do_GET(self):  # noqa: N802
        if not live():
            self._html("<p>Not live.</p>", 410)
            return
        if not self._ok():
            self._html(ASK, 401)
            return
        if self.path.startswith("/mjpeg"):
            self._stream()
            return
        self._html(f'<img src="/mjpeg?c={_live["code"]}">'
                   f'<p>Closes itself in {MINUTES} minutes.</p>')

    def _html(self, body: str, code: int = 200):
        page = PAGE.format(body=body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        try:
            self.wfile.write(page)
        except OSError:
            pass

    def _stream(self):
        """Serve whatever the capture thread last produced. This never
        touches the camera, so ten viewers cost the same as one."""
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=f")
        self.end_headers()
        delay = 1.0 / _live["fps"]
        sent_at = 0.0
        while live():
            frame_jpeg, at = _latest["jpeg"], _latest["at"]
            if not frame_jpeg or at == sent_at:
                time.sleep(delay / 2)
                continue
            sent_at = at
            try:
                self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: " +
                                 str(len(frame_jpeg)).encode() + b"\r\n\r\n" +
                                 frame_jpeg + b"\r\n")
            except OSError:
                return          # he closed the tab
            time.sleep(delay)


def _capture_screens() -> None:
    """Stream the monitors instead of the camera — both side by side when
    there are two, so he can watch the whole desk from his phone."""
    import cv2
    import numpy as np

    try:
        import mss
    except ImportError:
        return

    delay = 1.0 / _live["fps"]
    want = _live["source"]                    # "screen", "screen:left", ...
    with mss.mss() as sct:
        monitors = sct.monitors[1:] or sct.monitors[:1]
        if want.endswith("left") and monitors:
            monitors = monitors[:1]
        elif want.endswith("right") and len(monitors) > 1:
            monitors = monitors[1:2]
        while live():
            started = time.time()
            shots = []
            for mon in monitors:
                raw = sct.grab(mon)
                shots.append(np.array(raw)[:, :, :3])   # BGRA -> BGR
            if not shots:
                return
            if len(shots) > 1:
                # one monitor is portrait and the other landscape — pad the
                # shorter to match, never stretch, or everything on it is
                # the wrong shape
                tall = max(s.shape[0] for s in shots)
                padded = []
                for s in shots:
                    if s.shape[0] < tall:
                        s = cv2.copyMakeBorder(s, 0, tall - s.shape[0], 0, 0,
                                               cv2.BORDER_CONSTANT, value=(0, 0, 0))
                    padded.append(s)
                frame = np.hstack(padded)
            else:
                frame = shots[0]
            # scale the WHOLE thing once, at the end. Scaling each monitor to
            # full width first made two screens twice as wide as one, and
            # doubled the bandwidth for no extra detail.
            scale = SCREEN_WIDTH / float(frame.shape[1])
            frame = cv2.resize(frame, (SCREEN_WIDTH,
                                       max(1, int(frame.shape[0] * scale))))
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, SCREEN_QUALITY])
            if ok:
                _latest["jpeg"] = buf.tobytes()
                _latest["at"] = time.time()
            rest = delay - (time.time() - started)
            if rest > 0:
                time.sleep(rest)


def _capture() -> None:
    """Hold the camera open for the life of the stream, draw nametags on,
    and keep one encoded frame ready for everyone watching.

    It also publishes to dashboard.LATEST_JPEG, which is the existing
    contract for "the feed is live, don't touch the hardware" — so /photo,
    the guard and the camera skills all keep working while this runs, and
    get their frames instantly instead of fighting for the device.
    """
    import cv2

    try:
        import faces
    except Exception:
        faces = None

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    delay = 1.0 / _live["fps"]
    tags, tagged_at = [], 0.0
    published = [0.0]        # when the last full-size frame went to dashboard
    try:
        if not cap.isOpened():
            return
        while live():
            started = time.time()
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.2)
                continue

            now = time.time()
            # A clean full-size copy goes to the rest of TARS, before the
            # boxes are drawn on — nobody else wants my annotations baked in.
            # Throttled to a few a second: encoding 1280x720 at quality 75 is
            # the most expensive thing in this loop, and doing it on every
            # frame held the stream to 15 fps. /photo and the guard only need
            # a frame that's under two seconds old.
            if now - published[0] > 0.2:
                published[0] = now
                try:
                    import dashboard

                    ok_clean, clean = cv2.imencode(
                        ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok_clean:
                        dashboard.LATEST_JPEG = (now, clean.tobytes())
                except Exception:
                    pass

            if faces is not None and now - tagged_at > TAG_EVERY:
                tagged_at = now
                try:
                    tags = faces.identify(frame, wait=False)
                except Exception:
                    tags = []

            scale = WIDTH / float(frame.shape[1])
            small = cv2.resize(frame, (WIDTH, int(frame.shape[0] * scale)))
            for tag in tags:
                x, y, w, h = (int(v * scale) for v in tag["box"])
                label = tag["name"] or "unknown"
                colour = (80, 220, 120) if tag["name"] else (120, 120, 200)
                cv2.rectangle(small, (x, y), (x + w, y + h), colour, 2)
                cv2.putText(small, label, (x, max(16, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2)

            ok_enc, buf = cv2.imencode(".jpg", small,
                                       [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
            if ok_enc:
                _latest["jpeg"] = buf.tobytes()
                _latest["at"] = now
            # cap.read() already waits for the camera's next frame, so a flat
            # sleep on top halves the rate — 30 fps of camera became 15. Only
            # sleep for whatever's LEFT of the frame budget.
            rest = delay - (time.time() - started)
            if rest > 0:
                time.sleep(rest)
    finally:
        try:
            cap.release()
        except Exception:
            pass
        _latest["jpeg"], _latest["at"] = b"", 0.0


def _say(words: str) -> None:
    """Out loud in the room, and on the dashboard. Not optional."""
    try:
        import announce

        announce.post(words)
    except Exception:
        pass


PIDFILE = BASE / "livestream_tunnel.pid"


def _kill_strays() -> None:
    """Kill a tunnel left over from last time.

    stop() terminates the process it started — but if TARS restarts while a
    stream is up, that reference dies with the old process and cloudflared
    keeps running, forever, holding a tunnel to a port nothing is serving.
    One was found still alive hours later. The PID is written to a file so
    a fresh TARS can still find and kill it.
    """
    import subprocess

    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, timeout=10,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    PIDFILE.unlink(missing_ok=True)


def _open_tunnel(port: int) -> str:
    """cloudflared prints the public URL on stderr as it starts.

    The reading happens on its own thread with a hard deadline: readline()
    blocks, so a cloudflared that starts but says nothing used to hang the
    whole call forever — the 45-second limit was only checked BETWEEN lines,
    which never arrived.
    """
    import re
    import subprocess

    if not CLOUDFLARED.exists():
        return ""
    _kill_strays()
    proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--url", f"http://127.0.0.1:{port}",
         "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _live["tunnel"] = proc
    try:
        PIDFILE.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass

    found = []

    def read_until_url() -> None:
        pattern = re.compile(r"https://[-\w]+\.trycloudflare\.com")
        for line in proc.stdout:
            hit = pattern.search(line)
            if hit:
                found.append(hit.group(0))
                return

    reader = threading.Thread(target=read_until_url, daemon=True)
    reader.start()
    reader.join(timeout=45)
    return found[0] if found else ""


def start(source: str = "camera", fps: int = 0) -> tuple[str, str]:
    """Returns (message, code). The code is sent separately, on purpose.

    source: "camera", "screen", "screen:left", "screen:right"
    """
    with _lock:
        if live():
            return status(), ""
        _live["source"] = (source or "camera").strip().lower()
        default_fps = (SCREEN_FPS if _live["source"].startswith("screen")
                       else FPS)
        _live["fps"] = max(2, min(30, fps or default_fps))
        if not CLOUDFLARED.exists():
            return ("I can't put a stream online — cloudflared isn't "
                    "installed in my tools folder."), ""
        port = _free_port()
        code = f"{random.SystemRandom().randrange(0, 10**6):06d}"
        _live.update({"on": True, "code": code, "port": port,
                      "until": time.time() + MINUTES * 60, "url": ""})

    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _live["server"] = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    grab = _capture_screens if _live["source"].startswith("screen") else _capture
    threading.Thread(target=grab, daemon=True).start()

    url = _open_tunnel(port)
    if not url:
        stop(quiet=True)
        return "I couldn't open the tunnel — the stream didn't start.", ""
    _live["url"] = url

    threading.Timer(MINUTES * 60, lambda: stop()).start()
    what = ("this room" if _live["source"] == "camera"
            else "my screens" if _live["source"] == "screen"
            else "a screen")
    _say(f"Live stream on. Sharing {what} for ten minutes.")
    return url, code


def set_fps(target: int) -> str:
    """He asked for 30fps mid-stream and was told it had been adjusted, when
    nothing had. Now it can actually be done — and when the camera won't
    give it, that's said plainly rather than agreed to."""
    want = max(2, min(30, int(target)))
    _live["fps"] = want
    if not live():
        return f"Noted — the next stream will run at {want} frames a second."
    if _live["source"] == "camera" and want > 20:
        return (f"Set to {want}. Fair warning: in a dark room the camera "
                f"halves its own rate to gather light, so you may still see "
                f"about 15 until you put a lamp on.")
    return f"Stream's now running at {want} frames a second."


def stop(quiet: bool = False) -> str:
    with _lock:
        was = _live["on"]
        _live.update({"on": False, "code": "", "url": "", "until": 0})
        server, tunnel = _live.get("server"), _live.get("tunnel")
        _live["server"] = _live["tunnel"] = None
    for thing, how in ((server, "shutdown"), (tunnel, "terminate")):
        try:
            if thing:
                getattr(thing, how)()
        except Exception:
            pass
    _kill_strays()      # belt and braces: terminate() can miss a child
    if was and not quiet:
        _say("Live camera off.")
    return "Live stream stopped." if was else "It wasn't running."
