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
import json
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
         "server": None, "tunnel": None, "source": "camera", "fps": FPS,
         "control": False}
# ONE capture for the whole stream, however many people are watching.
# faces.get_frame() opens the camera, throws away six frames to let the
# exposure settle and closes it again — 2.5 seconds a go. That is exactly
# right for a single photo and hopeless for video: the first version of
# this ran at well under one frame a second.
_latest = {"jpeg": b"", "at": 0.0}
# Where each monitor ended up INSIDE the streamed picture, so a tap at
# (x, y) on his phone can be turned back into a point on the right screen.
# Recorded as the frame is built rather than recalculated later — the
# picture is padded and scaled, and guessing that mapping afterwards is how
# remote clicks land an inch from where you meant.
#   [{"ix","iy","iw","ih", "sx","sy","sw","sh"}]  image rect -> screen rect
_geometry = []
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

WATCH_ONLY = """<img src="/mjpeg?c=CODE">
<p>Watching only. Closes itself in MINS minutes.</p>"""

# Touch handling, written for a phone rather than adapted from a mouse:
#   tap                -> left click
#   press and hold     -> right click
#   two-finger tap     -> right click
#   two-finger drag    -> scroll wheel
#   tap a text box     -> the phone's keyboard opens by itself
VIEWER = """<img id=v src="/mjpeg?c=CODE">
<input id=kb autocomplete=off autocapitalize=off autocorrect=off
       style="position:fixed;bottom:0;left:0;width:100%;box-sizing:border-box"
       placeholder="tap here to type — enter sends">
<p id=s>Control is ON. Hold = right click. Two fingers = scroll.
Closes in MINS minutes.</p>
<script>
const img = document.getElementById('v'), kb = document.getElementById('kb');
const say = t => document.getElementById('s').textContent = t;
const send = a => fetch('/input?c=CODE', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(a)}).then(r => r.json()).catch(() => ({}));

// where on the PICTURE was that, in the picture's own pixels
function at(e){
  const r = img.getBoundingClientRect();
  const p = e.touches && e.touches[0] ? e.touches[0] : e;
  return {x: (p.clientX - r.left) / r.width  * img.naturalWidth,
          y: (p.clientY - r.top)  / r.height * img.naturalHeight};
}

let holdTimer = null, held = false, startY = 0, twoFinger = false, lastY = 0;

img.addEventListener('touchstart', e => {
  e.preventDefault();
  held = false;
  twoFinger = e.touches.length > 1;
  const p = at(e); startY = lastY = (e.touches[0] || e).clientY;
  if (!twoFinger) {
    // press and hold is a right click — the standard phone idiom
    holdTimer = setTimeout(() => { held = true; send({type:'rclick', ...p}); }, 500);
  }
}, {passive:false});

img.addEventListener('touchmove', e => {
  e.preventDefault();
  clearTimeout(holdTimer);
  if (e.touches.length > 1) {           // two fingers = scroll wheel
    const y = e.touches[0].clientY, dy = y - lastY;
    if (Math.abs(dy) > 6) { lastY = y; send({type:'scroll', dy: Math.round(dy/6), ...at(e)}); }
  }
}, {passive:false});

img.addEventListener('touchend', async e => {
  e.preventDefault();
  clearTimeout(holdTimer);
  if (held || twoFinger) { twoFinger = false; return; }
  const p = at({clientX: e.changedTouches[0].clientX,
                clientY: e.changedTouches[0].clientY});
  const r = await send({type:'click', ...p});
  // tapped something you type into? raise the keyboard without being asked
  if (r && r.keyboard) { kb.focus(); }
}, {passive:false});

// mouse, for when he's on a laptop rather than a phone
img.addEventListener('click', async e => {
  if (e.detail === 0) return;
  const r = await send({type:'click', ...at(e)});
  if (r && r.keyboard) kb.focus();
});
img.addEventListener('contextmenu', e => { e.preventDefault(); send({type:'rclick', ...at(e)}); });
img.addEventListener('wheel', e => { e.preventDefault();
  send({type:'scroll', dy: e.deltaY > 0 ? -3 : 3, ...at(e)}); }, {passive:false});

// typing: send each character as it's typed so it feels live
kb.addEventListener('keydown', async e => {
  if (e.key === 'Enter') { e.preventDefault();
    const r = await send({type:'key', key:'enter'});
    if (r && r.why) say(r.why);
    kb.value = ''; return; }
  if (e.key === 'Backspace') { e.preventDefault(); send({type:'key', key:'backspace'}); return; }
  if (e.key.length === 1) { e.preventDefault();
    const r = await send({type:'text', text: e.key});
    if (r && r.why) say(r.why); }
});
</script>"""


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

    def do_POST(self):  # noqa: N802
        """Remote input. Code-checked exactly like everything else."""
        if not live() or not self._ok():
            self._json({"ok": False, "why": "no"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            action = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json({"ok": False, "why": "bad request"}, 400)
            return
        self._json(_do_input(action))

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

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
        body = (VIEWER if _live.get("control") else WATCH_ONLY).replace(
            "CODE", _live["code"]).replace("MINS", str(MINUTES))
        self._html(body)

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
    """Stream the monitors instead of the camera.

    Wrapped in a recovery loop. A single failed grab — a monitor going to
    sleep, a resolution change, a game taking exclusive fullscreen — used to
    kill this thread outright while the tunnel stayed up, so the picture
    froze half-drawn and never came back. mss caches the monitor layout when
    it's created, so recovering means building a fresh one, not retrying the
    old.
    """
    while live():
        try:
            _capture_screens_once()
        except Exception:
            time.sleep(1.0)      # transient — go round and rebuild


def _capture_screens_once() -> None:
    import cv2
    import numpy as np

    try:
        import mss
    except ImportError:
        return

    delay = 1.0 / _live["fps"]
    want = _live["source"]                    # "screen", "screen:left", ...
    with mss.mss() as sct:
        # Sort by where the monitors ACTUALLY are, not the order Windows
        # lists them in. Windows enumerates the primary display first
        # wherever it sits: his portrait screen is at x=-1080 — genuinely
        # the left one — but came second, so "left" gave him the right
        # screen and the side-by-side view was mirrored.
        monitors = sorted(sct.monitors[1:] or sct.monitors[:1],
                          key=lambda m: m["left"])
        if want.endswith("left") and monitors:
            monitors = monitors[:1]
        elif want.endswith("right") and len(monitors) > 1:
            monitors = monitors[-1:]
        while live():
            started = time.time()
            shots = []
            for mon in monitors:
                raw = sct.grab(mon)
                shots.append(np.array(raw)[:, :, :3])   # BGRA -> BGR
            if not shots:
                return
            # remember where each monitor sits in the picture, at NATIVE size
            # — the scale to SCREEN_WIDTH is applied to everything at the end
            offset, native = 0, []
            for mon, shot in zip(monitors, shots):
                native.append({"ix": offset, "iy": 0,
                               "iw": shot.shape[1], "ih": shot.shape[0],
                               "sx": mon["left"], "sy": mon["top"],
                               "sw": mon["width"], "sh": mon["height"]})
                offset += shot.shape[1]
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
            global _geometry
            _geometry = [{**box,
                          "ix": box["ix"] * scale, "iy": box["iy"] * scale,
                          "iw": box["iw"] * scale, "ih": box["ih"] * scale}
                         for box in native]
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

    failures = 0
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
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if not ok or frame is None:
                # a webcam that's been unplugged, or grabbed by another app,
                # must not silently end the stream — try to get it back
                failures += 1
                if failures > 30:
                    failures = 0
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                time.sleep(0.2)
                continue
            failures = 0

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


def _to_screen(ix: float, iy: float) -> tuple[int, int] | None:
    """A point on the streamed picture -> a point on the actual desktop.

    Returns None for a tap on the black padding beside a shorter monitor:
    that's not anywhere, and moving the mouse there would be a guess.
    """
    for box in _geometry:
        if (box["ix"] <= ix < box["ix"] + box["iw"]
                and box["iy"] <= iy < box["iy"] + box["ih"]):
            fx = (ix - box["ix"]) / max(1e-6, box["iw"])
            fy = (iy - box["iy"]) / max(1e-6, box["ih"])
            return (int(box["sx"] + fx * box["sw"]),
                    int(box["sy"] + fy * box["sh"]))
    return None


def _do_input(action: dict) -> dict:
    """Carry out one remote action. Everything here is guarded twice: the
    code was already checked by the caller, and control has to have been
    switched on deliberately."""
    if not _live.get("control"):
        return {"ok": False, "why": "control is off"}

    import pyautogui

    pyautogui.FAILSAFE = False       # a corner tap must not abort everything
    kind = str(action.get("type", ""))

    if kind in ("click", "rclick", "dclick", "move", "down", "up"):
        point = _to_screen(float(action.get("x", -1)),
                           float(action.get("y", -1)))
        if point is None:
            return {"ok": False, "why": "off screen"}
        pyautogui.moveTo(point[0], point[1])
        if kind == "click":
            pyautogui.click()
        elif kind == "rclick":
            pyautogui.click(button="right")
        elif kind == "dclick":
            pyautogui.doubleClick()
        elif kind == "down":
            pyautogui.mouseDown()
        elif kind == "up":
            pyautogui.mouseUp()
        # tell the phone whether to raise its keyboard: he tapped a box you
        # type into, so he almost certainly wants to type
        return {"ok": True,
                "keyboard": kind in ("click", "dclick")
                and _caret_in_textbox()}

    if kind == "scroll":
        point = _to_screen(float(action.get("x", -1)),
                           float(action.get("y", -1)))
        if point:
            pyautogui.moveTo(point[0], point[1])
        pyautogui.scroll(int(float(action.get("dy", 0))))
        return {"ok": True}

    if kind == "text":
        text = str(action.get("text", ""))[:500]
        if not text:
            return {"ok": False, "why": "nothing to type"}
        if _messaging_focused():
            return {"ok": False, "why": "I don't type into messaging apps"}
        pyautogui.write(text, interval=0.01)
        return {"ok": True}

    if kind == "key":
        key = str(action.get("key", "")).lower()
        allowed = {"enter", "backspace", "tab", "escape", "space", "up",
                   "down", "left", "right", "home", "end", "pageup",
                   "pagedown", "delete"}
        if key not in allowed:
            return {"ok": False, "why": "key not allowed"}
        if key == "enter" and _messaging_focused():
            return {"ok": False, "why": "I don't send messages to people"}
        pyautogui.press(key)
        return {"ok": True}

    return {"ok": False, "why": "unknown action"}


def _messaging_focused() -> bool:
    try:
        import input_guard

        return input_guard.is_messaging()
    except Exception:
        return False        # can't tell -> don't block ordinary typing


def _caret_in_textbox() -> bool:
    try:
        import input_guard

        return input_guard.caret_in_textbox()
    except Exception:
        return False


def _watchdog() -> None:
    """If frames stop arriving, shut the whole thing down.

    The failure he hit: the capture thread died, the tunnel stayed up, and
    the picture sat there half-drawn forever. A stream that has stopped
    producing frames is not a stream, and leaving the tunnel open is worse
    than useless — it's a public URL pointing at a camera with nobody
    minding it.
    """
    while live():
        time.sleep(5)
        if not live():
            return
        age = time.time() - (_latest["at"] or 0)
        if _latest["at"] and age > 20:
            _say("The stream stopped sending pictures, so I've shut it off.")
            stop(quiet=True)
            return


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


def start(source: str = "camera", fps: int = 0,
          control: bool = False) -> tuple[str, str]:
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
        # control only makes sense over a screen — you cannot
        # click on a webcam picture of a room
        _live["control"] = bool(control) and _live["source"].startswith("screen")
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
    threading.Thread(target=_watchdog, daemon=True).start()
    what = ("this room" if _live["source"] == "camera"
            else "my screens" if _live["source"] == "screen"
            else "a screen")
    if _live["control"]:
        # louder, because this is somebody able to drive the machine, not
        # just look at it
        _say(f"Remote control on. Sharing {what}, and whoever has the link "
             f"can click and type on this computer for ten minutes.")
    else:
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
