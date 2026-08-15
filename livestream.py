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


def _cloudflared() -> Path:
    """The tunnel binary, whichever machine this is.

    TARS runs on his Windows PC and on his mate's Mac, so hard-coding the
    .exe meant the whole feature was Windows-only for no reason. A Mac or
    Linux copy just needs the matching binary dropped in tools/, or one
    already on PATH.
    """
    import shutil
    import sys

    names = (["cloudflared.exe"] if sys.platform == "win32"
             else ["cloudflared"])
    for name in names:
        local = BASE / "tools" / name
        if local.exists():
            return local
    found = shutil.which("cloudflared")
    return Path(found) if found else BASE / "tools" / names[0]


CLOUDFLARED = _cloudflared()

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
SCREEN_WIDTH = 960          # the safe default, before a viewer says otherwise
SCREEN_QUALITY = 45
SCREEN_FPS = 12
# A phone can't use more than about 960; a Mac with a big window can, and at
# 960 the picture is 37% of native and looks soft blown up. Measured on his
# 2560x1440 monitor at 12 fps:
#      960 -> 195 KB/s   37% of native
#     1280 -> 315 KB/s   50%
#     1600 -> 466 KB/s   62%
#     1920 -> 640 KB/s   75%   fine on wifi, too much on mobile data
# So the VIEWER asks for what its display can actually show, and this is the
# ceiling rather than the setting.
SCREEN_WIDTH_MAX = 1920
SCREEN_WIDTH_MIN = 640

_live = {"on": False, "code": "", "url": "", "port": 0, "until": 0.0,
         "server": None, "tunnel": None, "source": "camera", "fps": FPS,
         "control": False, "width": SCREEN_WIDTH, "gen": 0}
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

PAGE = """<!doctype html><html><head>
<meta name=viewport content="width=device-width,initial-scale=1,\
maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>TARS</title>
<style>
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
html,body{{margin:0;height:100%;background:#07090d;color:#9fb;
 font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;
 overflow:hidden;overscroll-behavior:none}}
/* 100dvh, not 100vh: on a phone the address bar and the on-screen keyboard
   both change the usable height, and vh doesn't notice either */
/* The bar sits BELOW the picture, not on top of it. Floating it over the
   bottom hid the Windows taskbar and the last inch of the desktop — the
   part you most often need, since that's where the taskbar lives. */
#wrap{{position:fixed;left:0;right:0;top:0;bottom:var(--bar,66px);
 display:flex;align-items:center;justify-content:center}}
/* width/height 100% + contain, NOT max-width. An img with only max-width
   never grows past its own pixel size, so on a big screen the picture sat
   small in the middle — and since the page then asked for a stream matching
   that small size, it shrank itself further every time. contain still
   letterboxes correctly; it just fills the space it's given. */
img{{width:100%;height:100%;object-fit:contain;
 touch-action:none;user-select:none;-webkit-user-drag:none;display:block}}
p{{opacity:.65;font-size:13px;margin:8px;text-align:center}}
input,button{{font-size:17px;padding:11px 14px;border-radius:10px;
 border:1px solid #2c3b33;background:#10161b;color:#9fb;font-family:inherit}}
button:active{{background:#1b2a22}}
#bar{{position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;
 padding:9px calc(9px + env(safe-area-inset-left))
 calc(9px + env(safe-area-inset-bottom)) 9px;
 background:#0b0e13;border-top:1px solid #182028}}
#bar button{{flex:1;min-height:48px}}   /* 48px: a thumb, not a cursor */
#kb{{position:fixed;left:8px;right:8px;bottom:8px;display:none}}
/* the hint floats — it's over the very top of the desktop, which is almost
   never where you're working, and it fades to nothing after a moment */
#tip{{position:fixed;top:0;left:0;right:0;padding:5px;font-size:12px;
 background:#07090dcc;text-align:center;transition:opacity .6s;
 pointer-events:none}}
/* monitor switchers: at the edges, where a thumb already is */
.arrow{{position:fixed;top:50%;transform:translateY(-50%);width:42px;
 height:62px;display:flex;align-items:center;justify-content:center;
 font-size:24px;line-height:1;border-radius:12px;z-index:5;
 background:#0b0e13cc;border:1px solid #2c3b33;color:#9fb;opacity:.55}}
.arrow:active{{opacity:1;background:#1b2a22}}
#aleft{{left:calc(4px + env(safe-area-inset-left))}}
#aright{{right:calc(4px + env(safe-area-inset-right))}}
.dot{{position:fixed;width:26px;height:26px;margin:-13px 0 0 -13px;
 border:2px solid #6fe3a4;border-radius:50%;pointer-events:none;
 animation:pop .45s ease-out forwards}}
@keyframes pop{{from{{transform:scale(.3);opacity:.9}}
 to{{transform:scale(1.5);opacity:0}}}}
</style></head><body>{body}</body></html>"""

ASK = """<div id=wrap><form style="display:grid;gap:12px;padding:20px">
<p>Enter the code TARS sent you.</p>
<input name=c inputmode=numeric autocomplete=off autofocus
       style="text-align:center;letter-spacing:6px;font-size:26px">
<button>Watch</button></form></div>"""

WATCH_ONLY = """<div id=wrap><img src="/mjpeg?c=CODE"></div>
<div id=tip>Watching only — closes in MINS minutes</div>"""

# The viewer. Rebuilt for a phone held in one hand, not a desktop shrunk down.
#
#   tap                  left click            pinch          zoom in/out
#   press and hold       right click           drag (zoomed)  pan
#   two fingers, drag    scroll                buttons        keyboard, zoom, stop
#
# The whole screen always fits: a portrait monitor streams as a 960x1706
# picture, and on a phone that ran off both ends with no way to reach the
# top or bottom of the desktop. Now it's fitted to the viewport and you
# pinch in for detail.
VIEWER = """<div id=wrap><img id=v src="/mjpeg?c=CODE"></div>
<button class=arrow id=aleft>&#9664;</button>
<button class=arrow id=aright>&#9654;</button>
<div id=tip>Tap = click · hold = right click · 2 fingers = scroll · pinch = zoom</div>
<input id=kb autocomplete=off autocapitalize=off autocorrect=off
       spellcheck=false placeholder="type here — enter sends">
<div id=bar>
  <button id=bkb>Keyboard</button>
  <button id=bzoom>Fit</button>
  <button id=bstop>Stop</button>
</div>
<script>
const img=document.getElementById('v'), kb=document.getElementById('kb'),
      tip=document.getElementById('tip'), bar=document.getElementById('bar');
const say=t=>{tip.textContent=t; tip.style.opacity=1; clearTimeout(say.t);
              say.t=setTimeout(()=>{tip.style.opacity=0},2600)};
setTimeout(()=>{tip.style.opacity=0},5000);   // the hint gets out of the way

/* Tell the layout exactly how tall the bar is, so the picture ends where
   the bar begins — guessing a height left a sliver of desktop hidden. */
const fit=()=>document.documentElement.style.setProperty(
  '--bar', (bar.style.display==='none' ? 0 : bar.offsetHeight) + 'px');

/* Ask for a stream that matches what this display can actually show.
   A phone is ~960 even at 3x; a Mac window wants 1600 and looks soft below
   it. Sent on load, on resize and on rotate — debounced, because dragging a
   window edge fires this constantly. */
let sized=0, sizeTimer=null;
function askForSize(){
  clearTimeout(sizeTimer);
  sizeTimer=setTimeout(async ()=>{
    const b=shown();                 // the PICTURE's size, not the element's
    if(!b.w) return;
    const dpr=Math.min(devicePixelRatio||1, 2);   // 3x on a phone is wasted
    let want=Math.round(b.w*dpr);
    /* mobile data: stay modest whatever the screen can do */
    const net=navigator.connection;
    if(net && (net.saveData || /2g|3g/.test(net.effectiveType||''))) want=Math.min(want,960);
    want=Math.max(640, Math.min(1920, want));
    if(Math.abs(want-sized) < 120) return;        // ignore small wobbles
    const res=await post({type:'fit', w:want});
    if(res&&res.ok && res.width!==sized){sized=res.width; reconnect();
                                        say('Sharpness '+res.width+'px');}
  }, 400);
}
addEventListener('resize', ()=>{fit(); askForSize();});
addEventListener('orientationchange', ()=>{fit(); askForSize();});
img.addEventListener('load', askForSize);
const HINT='Tap = click · hold = right click · 2 fingers = scroll · pinch = zoom';
const SOURCE='SRC', SCREENS=NSCREENS;
if(SCREENS<2){document.getElementById('aleft').style.display='none';
              document.getElementById('aright').style.display='none';}
const post=a=>fetch('/input?c=CODE',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(a)})
    .then(r=>r.json()).catch(()=>({}));

/* A browser will drop an MJPEG connection when the frames change size, and
   the picture goes blank — which is what happened switching monitors or
   changing sharpness. So whenever the dimensions are about to change, take
   a fresh connection rather than hoping the old one copes. */
function reconnect(){
  img.src='/mjpeg?c=CODE&t='+Date.now();
}

/* ---- zoom & pan -------------------------------------------------------- */
let zoom=1, panX=0, panY=0;
const apply=()=>{img.style.transform=
  `translate(${panX}px,${panY}px) scale(${zoom})`;
  document.getElementById('bzoom').textContent = zoom>1.02?'Fit':'Zoom';};
const clampPan=()=>{const r=img.getBoundingClientRect();
  const mx=Math.max(0,(r.width*1-innerWidth)/2+40);
  panX=Math.min(mx,Math.max(-mx,panX));
  const my=Math.max(0,(r.height*1-innerHeight)/2+40);
  panY=Math.min(my,Math.max(-my,panY));};

/* Where the PICTURE actually is on screen. The <img> fills its box, but
   object-fit:contain letterboxes the picture inside it — so the element's
   rectangle is NOT the picture's rectangle, and using it would put every
   click out by the size of the black bars. */
function shown(){
  const r=img.getBoundingClientRect();
  const nw=img.naturalWidth||1, nh=img.naturalHeight||1;
  const s=Math.min(r.width/nw, r.height/nh);
  const w=nw*s, h=nh*s;
  return {left:r.left+(r.width-w)/2, top:r.top+(r.height-h)/2, w:w, h:h, s:s};
}
function at(cx,cy){
  const b=shown();
  return {x:(cx-b.left)/b.s, y:(cy-b.top)/b.s};
}
function mark(cx,cy){const d=document.createElement('div');
  d.className='dot'; d.style.left=cx+'px'; d.style.top=cy+'px';
  document.body.appendChild(d); setTimeout(()=>d.remove(),460);}

/* ---- scrolling --------------------------------------------------------- */
/* Every action is a round trip through Cloudflare, so sending a click per
   6 pixels made scrolling crawl. Movement is accumulated and flushed on a
   timer, as one bigger scroll — far fewer requests, far more travel. */
let pending=0, flushing=null;
function scrollBy(px,cx,cy){
  pending += px;
  if(flushing) return;
  flushing=setTimeout(()=>{
    const notches=Math.round(pending/2.2);   // was /6 — this is the speed
    pending=0; flushing=null;
    if(notches) post({type:'scroll',dy:notches,...at(cx,cy)});
  },55);
}

/* ---- touch ------------------------------------------------------------- */
let hold=null, held=false, moved=0, startX=0, startY=0,
    lastY=0, pinchFrom=0, zoomFrom=1, fingers=0, panning=false;

img.addEventListener('touchstart',e=>{
  e.preventDefault(); fingers=e.touches.length; held=false; moved=0;
  const t=e.touches[0]; startX=t.clientX; startY=lastY=t.clientY;
  if(fingers===2){
    clearTimeout(hold);
    const [a,b]=e.touches;
    pinchFrom=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
    zoomFrom=zoom; return;
  }
  panning = zoom>1.02;
  hold=setTimeout(()=>{held=true; mark(startX,startY);
    post({type:'rclick',...at(startX,startY)}); say('Right click');},480);
},{passive:false});

img.addEventListener('touchmove',e=>{
  e.preventDefault();
  const t=e.touches[0];
  moved=Math.max(moved,Math.hypot(t.clientX-startX,t.clientY-startY));
  if(moved>12) clearTimeout(hold);

  if(e.touches.length===2){
    const [a,b]=e.touches;
    const now=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
    /* pinch if the gap is changing, otherwise it's a two-finger scroll */
    if(pinchFrom && Math.abs(now-pinchFrom)>28){
      zoom=Math.min(4,Math.max(1,zoomFrom*(now/pinchFrom)));
      if(zoom<=1.02){zoom=1;panX=panY=0;}
      clampPan(); apply(); return;
    }
    const dy=t.clientY-lastY; lastY=t.clientY;
    if(Math.abs(dy)>1) scrollBy(dy,t.clientX,t.clientY);
    return;
  }
  if(panning && zoom>1.02){
    panX+=t.clientX-startX; panY+=t.clientY-startY;
    startX=t.clientX; startY=t.clientY; clampPan(); apply();
  }
},{passive:false});

img.addEventListener('touchend',async e=>{
  e.preventDefault(); clearTimeout(hold);
  const was=fingers; fingers=e.touches.length;
  if(held||was>1||moved>12||panning) return;
  const t=e.changedTouches[0];
  mark(t.clientX,t.clientY);
  const r=await post({type:'click',...at(t.clientX,t.clientY)});
  if(r&&r.why) say(r.why);
  if(r&&r.keyboard) showKb(true);
},{passive:false});

/* ---- mouse & trackpad (Mac, Windows, any laptop) ----------------------- */
img.addEventListener('click',async e=>{
  if(e.detail===0) return;
  mark(e.clientX,e.clientY);
  const r=await post({type:'click',...at(e.clientX,e.clientY)});
  if(r&&r.why) say(r.why);
  if(r&&r.keyboard) showKb(true);
});
img.addEventListener('dblclick',e=>{e.preventDefault();
  post({type:'dclick',...at(e.clientX,e.clientY)});});
img.addEventListener('contextmenu',e=>{e.preventDefault();
  mark(e.clientX,e.clientY); post({type:'rclick',...at(e.clientX,e.clientY)});});
/* a Mac trackpad sends many small deltas — accumulate them like touch */
img.addEventListener('wheel',e=>{e.preventDefault();
  scrollBy(-e.deltaY,e.clientX,e.clientY);},{passive:false});

/* ---- keyboard ---------------------------------------------------------- */
function showKb(on){
  kb.style.display = on ? 'block' : 'none';
  bar.style.display = on ? 'none' : 'flex';
  fit();                       /* the picture grows back into the space */
  if(on) kb.focus(); else kb.blur();
}
document.getElementById('bkb').onclick=()=>showKb(true);
kb.addEventListener('blur',()=>showKb(false));
/* Typed characters are BUFFERED and sent in batches.
   One request per keystroke floods the browser's connection pool — it only
   allows about six at once, and the video is permanently holding one of
   them — so typing a command starved the stream and the picture froze while
   clicks carried on working. A batch every 90ms feels identical to type
   and uses a fraction of the connections. */
let typed='', typeTimer=null;
function flushTyping(){
  clearTimeout(typeTimer); typeTimer=null;
  if(!typed) return Promise.resolve({});
  const batch=typed; typed='';
  return post({type:'text',text:batch}).then(r=>{if(r&&r.why) say(r.why); return r;});
}
function queueType(ch){
  typed+=ch;
  if(!typeTimer) typeTimer=setTimeout(flushTyping,90);
}
kb.addEventListener('keydown',async e=>{
  if(e.key==='Enter'){e.preventDefault();
    await flushTyping();               /* the text must land BEFORE enter */
    const r=await post({type:'key',key:'enter'});
    if(r&&r.why) say(r.why); kb.value=''; return;}
  if(e.key==='Backspace'){e.preventDefault();
    if(typed){typed=typed.slice(0,-1); return;}   /* not yet sent — just drop it */
    post({type:'key',key:'backspace'}); return;}
  if(e.key.length===1){e.preventDefault(); queueType(e.key);}
});
/* phone autocorrect and predictive text fire input events, not keydown */
kb.addEventListener('input',()=>{const v=kb.value; if(!v) return;
  kb.value=''; queueType(v);});
kb.addEventListener('blur',flushTyping);

/* ---- which monitor ----------------------------------------------------- */
/* left -> both -> right -> both -> left ... so "both" is always one tap
   away from either single screen, and you can never get stuck */
const ORDER=['screen:left','screen','screen:right'];
const LABEL={'screen:left':'Left screen','screen':'Both screens',
             'screen:right':'Right screen'};
let current=SOURCE;
async function switchTo(step){
  const i=ORDER.indexOf(current);
  const next=ORDER[Math.min(ORDER.length-1,Math.max(0,(i<0?1:i)+step))];
  if(next===current){say('No further that way'); return;}
  const r=await post({type:'monitor',which:
    next==='screen'?'both':next.split(':')[1]});
  if(r&&r.ok){current=next; zoom=1; panX=panY=0; apply(); reconnect();
              sized=0; say(LABEL[next]);}
  else say((r&&r.why)||'Could not switch');
}
document.getElementById('aleft').onclick=()=>switchTo(-1);
document.getElementById('aright').onclick=()=>switchTo(1);

document.getElementById('bzoom').onclick=()=>{
  if(zoom>1.02){zoom=1;panX=panY=0;} else {zoom=2;}
  clampPan(); apply();};
document.getElementById('bstop').onclick=()=>{
  post({type:'quit'}); say('Stopping…');
  setTimeout(()=>{document.body.innerHTML='<div id=wrap><p>Stopped.</p></div>';},600);};
apply(); fit(); askForSize();
</script>"""


def live() -> bool:
    return bool(_live["on"]) and time.time() < _live["until"]


def status() -> str:
    if not live():
        return "The live stream is off."
    left = int((_live["until"] - time.time()) / 60) + 1
    return f"Live now — about {left} minute{'s' if left != 1 else ''} left."


def _monitor_count() -> int:
    """How many screens there are — so the switch arrows only appear on a
    machine that has something to switch to."""
    try:
        import mss

        with mss.mss() as sct:
            return max(1, len(sct.monitors) - 1)
    except Exception:
        return 1


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
        body = ((VIEWER if _live.get("control") else WATCH_ONLY)
                .replace("CODE", _live["code"])
                .replace("MINS", str(MINUTES))
                .replace("NSCREENS", str(_monitor_count()))
                .replace("SRC", _live["source"]))
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
    mine = _live["gen"]
    while live() and _live["gen"] == mine:
        try:
            _capture_screens_once(mine)
        except Exception:
            time.sleep(1.0)      # transient — go round and rebuild


def _capture_screens_once(mine: int = None) -> None:
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
            # he switched monitors with the on-screen arrows: drop out and
            # let the outer loop rebuild against the new one. mss caches the
            # layout, so this can't be changed in place.
            if _live["source"] != want or (mine is not None
                                           and _live["gen"] != mine):
                return
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
            wide = int(_live.get("width") or SCREEN_WIDTH)
            scale = wide / float(frame.shape[1])
            frame = cv2.resize(frame, (wide,
                                       max(1, int(frame.shape[0] * scale))),
                               interpolation=cv2.INTER_AREA)
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

    mine = _live["gen"]
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
        while live() and _live["gen"] == mine:
            started = time.time()
            try:
                ok, frame = cap.read()
            except Exception:
                ok, frame = False, None
            if ok and frame is not None:
                # Mirror, so his left hand is on the left of the picture the
                # way it is in a mirror. Flipped HERE, at the source, so the
                # overlay, the recognition and any snapshot all work off the
                # same picture — flipping only at display would leave every
                # skeleton and face box on the wrong side of the screen.
                frame = cv2.flip(frame, 1)
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

            # Track on the SCALED-DOWN frame, not the full-size one: at 640
            # wide it's a quarter of the pixels, the overlay looks identical,
            # and the phone gets skeletons for almost nothing.
            scale = WIDTH / float(frame.shape[1])
            small = cv2.resize(frame, (WIDTH, int(frame.shape[0] * scale)))
            try:
                import vision_track

                vision_track.annotate(small)
            except Exception:
                pass

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


LAST_INPUT = BASE / "livestream_last_input.json"


def _note_input(action: dict, outcome: str, **extra) -> None:
    """Write down what the phone asked for and what happened to it.

    Remote control failing looks identical from a phone whatever the cause —
    the tap just does nothing. Guessing at that cost a whole afternoon on the
    face recogniser earlier today, so this time the answer gets written down
    the first time it goes wrong.
    """
    try:
        import json as _json

        LAST_INPUT.write_text(_json.dumps({
            "at": time.strftime("%H:%M:%S"),
            "asked": {k: v for k, v in (action or {}).items() if k != "code"},
            "outcome": outcome, **extra}, indent=1), encoding="utf-8")
    except Exception:
        pass


def _do_input(action: dict) -> dict:
    """Carry out one remote action. Everything here is guarded twice: the
    code was already checked by the caller, and control has to have been
    switched on deliberately."""
    # stopping is allowed even without control — the way out must never be
    # harder to reach than the way in
    if str(action.get("type", "")) == "quit":
        threading.Thread(target=stop, daemon=True).start()
        return {"ok": True}

    # Switching which monitor he's looking at. Allowed without control,
    # because looking at a different screen of his own isn't a new power —
    # and having to stop the stream and say "share my right screen" to see
    # the other monitor was the whole complaint.
    # The viewer telling us how big a picture its display can actually use.
    # A phone asking for 1920 would just spend data on detail it can't show;
    # a Mac at 960 gets a soft, blown-up picture. Only the viewer knows.
    if str(action.get("type", "")) == "fit":
        try:
            want = int(float(action.get("w", 0)))
        except (TypeError, ValueError):
            return {"ok": False, "why": "bad width"}
        want = max(SCREEN_WIDTH_MIN, min(SCREEN_WIDTH_MAX, want))
        want -= want % 2          # even widths encode more cleanly
        _live["width"] = want
        return {"ok": True, "width": want}

    if str(action.get("type", "")) == "monitor":
        if not _live["source"].startswith("screen"):
            return {"ok": False, "why": "not sharing a screen"}
        which = str(action.get("which", "")).lower()
        wanted = {"left": "screen:left", "right": "screen:right",
                  "both": "screen"}.get(which)
        if not wanted:
            return {"ok": False, "why": "which monitor?"}
        _live["source"] = wanted
        return {"ok": True, "source": wanted}

    if not _live.get("control"):
        _note_input(action, "control is off",
                    source=_live.get("source"), live=live())
        return {"ok": False, "why": "control is off"}

    import pyautogui

    pyautogui.FAILSAFE = False       # a corner tap must not abort everything
    kind = str(action.get("type", ""))

    if kind in ("click", "rclick", "dclick", "move", "down", "up"):
        point = _to_screen(float(action.get("x", -1)),
                           float(action.get("y", -1)))
        if point is None:
            _note_input(action, "the tap landed outside the shared screen")
            return {"ok": False, "why": "off screen"}
        _note_input(action, "done", at=list(point))
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
    """Keep frames flowing — and if they truly can't, shut down cleanly.

    Two stages, because dying was too blunt a response to a stumble:

      after 3s of no frames  -> restart the capture. A UAC prompt on the
        secure desktop, a game going exclusive fullscreen, or a display
        change all stop the grab; none of them are reasons to end a stream
        he's using. He hit this as a frozen picture that still took clicks.

      after 25s              -> give up, say so, and close the tunnel. A
        public URL pointing at a camera that isn't working is worse than
        no stream at all.
    """
    restarts = 0
    while live():
        time.sleep(2)
        if not live():
            return
        age = time.time() - (_latest["at"] or 0)
        if not _latest["at"] or age < 3:
            restarts = 0
            continue

        if age > 25:
            _say("The stream stopped sending pictures, so I've shut it off.")
            stop(quiet=True)
            return

        # nudge it: the capture loops exit when the source changes, so
        # flipping it to itself makes them rebuild
        restarts += 1
        if restarts <= 4:
            _live["gen"] += 1          # the stuck loop exits when it notices
            grab = (_capture_screens if _live["source"].startswith("screen")
                    else _capture)
            threading.Thread(target=grab, daemon=True).start()
            time.sleep(2)


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

    import os
    import signal
    import sys

    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=10,
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
        else:
            os.kill(pid, signal.SIGTERM)
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
