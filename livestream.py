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
FPS = 10
WIDTH = 640       # 1280 wide at quality 70 is 35KB a frame; this is 7KB
QUALITY = 60
TAG_EVERY = 2.0   # seconds between re-identifying faces

_live = {"on": False, "code": "", "url": "", "port": 0, "until": 0.0,
         "server": None, "tunnel": None}
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
        delay = 1.0 / FPS
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
    delay = 1.0 / FPS
    tags, tagged_at = [], 0.0
    try:
        if not cap.isOpened():
            return
        while live():
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.2)
                continue

            # a clean copy goes to the rest of TARS before the boxes are
            # drawn on — nobody else wants my annotations baked in
            try:
                import dashboard

                ok_clean, clean = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok_clean:
                    dashboard.LATEST_JPEG = (time.time(), clean.tobytes())
            except Exception:
                pass

            now = time.time()
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
            time.sleep(delay)
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


def _open_tunnel(port: int) -> str:
    """cloudflared prints the public URL on stderr as it starts."""
    import re
    import subprocess

    if not CLOUDFLARED.exists():
        return ""
    proc = subprocess.Popen(
        [str(CLOUDFLARED), "tunnel", "--url", f"http://127.0.0.1:{port}",
         "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _live["tunnel"] = proc
    deadline = time.time() + 45
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return ""
            continue
        found = re.search(r"https://[-\w]+\.trycloudflare\.com", line)
        if found:
            return found.group(0)
    return ""


def start() -> tuple[str, str]:
    """Returns (message, code). The code is sent separately, on purpose."""
    with _lock:
        if live():
            return status(), ""
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
    threading.Thread(target=_capture, daemon=True).start()

    url = _open_tunnel(port)
    if not url:
        stop(quiet=True)
        return "I couldn't open the tunnel — the stream didn't start.", ""
    _live["url"] = url

    threading.Timer(MINUTES * 60, lambda: stop()).start()
    _say("Live camera on. Streaming this room for ten minutes.")
    return url, code


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
    if was and not quiet:
        _say("Live camera off.")
    return "Live stream stopped." if was else "It wasn't running."
