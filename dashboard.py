"""TARS dashboard — a tiny localhost web server living inside the TARS process.

Serves dashboard/index.html plus a JSON state API, and accepts personality
slider changes (they apply to the very next reply, since the brain re-reads
settings.json every time).
"""
import datetime
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
BRAIN = None    # set by main.py — used by the Teach and Talk boxes
SPEAKER = None  # set by main.py — so typed messages can be answered aloud
_TYPING = threading.Lock()  # one typed message at a time — the brain isn't reentrant
_LAST_TYPED_NORM = None  # exact-repeat guard for /api/say — mirrors the
# voice loop's last_command_norm in main.py (typed side never had it, which
# is how "whats the weather" typed twice back-to-back ran the skill twice)
PORT = 8765

state = {"status": "starting"}
_cache: dict = {"skills": (0.0, []), "weather": (0.0, "")}
EARS: tuple[float, float] = (0.0, 0.0)  # (when the listening loop
# last ran, how loud it was) — set by main. Lets the dashboard say
# whether he is ACTUALLY listening, not just running.
LATEST_JPEG: tuple[float, bytes] = (0.0, b"")  # newest live-feed frame, shared
# with the camera skill so "what do you see" works while the feed is open

# every TTS voice TARS can speak with — mirrors skills/list_voices + voice_settings
VOICES = [
    {"id": "bm_george", "name": "George", "desc": "British male — default"},
    {"id": "bm_fable", "name": "Fable", "desc": "British male"},
    {"id": "bm_lewis", "name": "Lewis", "desc": "British male"},
    {"id": "bm_daniel", "name": "Daniel", "desc": "British male"},
    {"id": "bf_emma", "name": "Emma", "desc": "British female"},
    {"id": "bf_isabella", "name": "Isabella", "desc": "British female"},
    {"id": "en-GB-RyanNeural", "name": "Ryan", "desc": "British male"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia", "desc": "British female"},
    {"id": "en-US-GuyNeural", "name": "Guy", "desc": "US male"},
    {"id": "en-US-JennyNeural", "name": "Jenny", "desc": "US female"},
    {"id": "en-US-AriaNeural", "name": "Aria", "desc": "US female"},
    {"id": "en-US-DavisNeural", "name": "Davis", "desc": "US male"},
    {"id": "en-AU-WilliamNeural", "name": "William", "desc": "Australian male"},
    {"id": "en-AU-NatashaNeural", "name": "Natasha", "desc": "Australian female"},
]

# The paid ElevenLabs voices, if a key is set. These are library voices with
# fixed IDs that work on any account, which matters because a key scoped to
# text-to-speech can't list them — asking would 401. Every ID below was
# verified by actually generating a word with it; one more that came from
# memory turned out to be a 404, which is why none of these are guesses.
ELEVEN_VOICES = [
    {"id": "el:JBFqnCBsd6RMkjVDRZzb", "name": "George",
     "desc": "ElevenLabs — British male"},
    {"id": "el:IKne3meq5aSn9XLyUdCD", "name": "Charlie",
     "desc": "ElevenLabs — Australian male"},
    {"id": "el:onwK4e9ZLuTAKqWW03F9", "name": "Daniel",
     "desc": "ElevenLabs — British male, deeper"},
    {"id": "el:nPczCjzI2devNBz1zQrb", "name": "Brian",
     "desc": "ElevenLabs — American male"},
    {"id": "el:pFZP5JQG7iQjIQuC4Bku", "name": "Lily",
     "desc": "ElevenLabs — British female"},
]
VOICES = VOICES + ELEVEN_VOICES
VOICE_IDS = {v["id"] for v in VOICES}


def set_status(s: str) -> None:
    state["status"] = s


def _test_portal(data: dict) -> dict:
    """Try the school portal with what they've typed, and — for schools
    that aren't SEQTA — work out what system it actually is so it can be
    supported later. the owner's ask: 'try to detect it and tell me what it is'.
    """
    import urllib.request

    url = str(data.get("seqta_url", "")).strip().rstrip("/")
    if not url:
        return {"ok": False, "message": "Put the address in first."}
    if not url.startswith("http"):
        url = "https://" + url

    # 1. does it answer at all?
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 TARS"})
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(120_000).decode("utf-8", "replace").lower()
            landed = response.geturl().lower()
    except Exception as e:
        return {"ok": False,
                "message": f"Couldn't reach that address ({type(e).__name__}). "
                           f"Check it's the same one you type into a browser."}

    # 2. what is it?
    systems = [("SEQTA", ("seqta", "/seqta/")),
               ("Compass", ("compass.education", "compass school manager")),
               ("Sentral", ("sentral", "portal.sentral")),
               ("Daymap", ("daymap",)),
               ("Schoolbox", ("schoolbox",)),
               ("Canvas", ("instructure", "canvas lms")),
               ("Google Classroom", ("classroom.google",)),
               ("Microsoft/SharePoint", ("sharepoint", "office365", "microsoftonline"))]
    found = next((name for name, marks in systems
                  if any(m in body or m in landed for m in marks)), "")

    if found == "SEQTA":
        try:  # actually log in
            import seqta

            os.environ["SEQTA_URL"] = url
            os.environ["SEQTA_USER"] = str(data.get("seqta_user", ""))
            os.environ["SEQTA_PASS"] = str(data.get("seqta_pass", ""))
            message = seqta.test()
            return {"ok": message.lower().startswith("connected"),
                    "message": message}
        except Exception as e:
            return {"ok": False, "message": f"SEQTA test failed: {e}"}
    if found:
        return {"ok": False,
                "message": f"That's {found}, not SEQTA — I can't log into "
                           f"{found} yet. Tell me your timetable in your own "
                           f"words instead and everything else still works."}
    return {"ok": False,
            "message": "That address answered, but I don't recognise the "
                       "system it runs. Tell me your timetable yourself and "
                       "study mode will still work."}


def _gestures_took_over() -> bool:
    """True once the hand-signal watcher wants the webcam."""
    try:
        import gestures

        return gestures.active()
    except Exception:
        return False


def _skills() -> list[dict]:
    ts, cached = _cache["skills"]
    if time.time() - ts < 60:
        return cached
    from skills_engine import SkillBox

    out = []
    for item in SkillBox(BASE).catalog():
        py = BASE / "skills" / item["skill"] / "skill.py"
        added = datetime.date.fromtimestamp(py.stat().st_mtime).strftime("%d %b")
        out.append({"name": item["skill"], "desc": item["description"], "added": added})
    _cache["skills"] = (time.time(), out)
    return out


def _learning() -> list[dict]:
    """The 'Learning' dashboard card: skills TARS has most recently taught
    himself, newest first — NOT Kipp's proposed-upgrades queue (that's the
    separate 'kipp' card/log), just the actual finished output of the
    self-teaching pipeline (skills/<name>/skill.py), sorted by file age."""
    ts, cached = _cache.get("learning", (0.0, []))
    if time.time() - ts < 60:
        return cached
    from skills_engine import SkillBox

    rows = []
    for item in SkillBox(BASE).catalog():
        py = BASE / "skills" / item["skill"] / "skill.py"
        try:
            mtime = py.stat().st_mtime
        except OSError:
            continue
        rows.append({"name": item["skill"], "desc": item["description"], "mtime": mtime})
    rows.sort(key=lambda r: -r["mtime"])
    out = [{"name": r["name"], "desc": r["desc"],
            "added": datetime.date.fromtimestamp(r["mtime"]).strftime("%d %b")}
           for r in rows[:3]]
    _cache["learning"] = (time.time(), out)
    return out


def _weather() -> str:
    ts, cached = _cache["weather"]
    if time.time() - ts < 900:
        return cached
    _cache["weather"] = (time.time(), cached)  # block re-entry while fetching

    def fetch():
        try:
            from skills_engine import SkillBox

            text = SkillBox(BASE).run("weather", {"when": "now"})
        except Exception:
            text = ""
        _cache["weather"] = (time.time(), text or "")

    threading.Thread(target=fetch, daemon=True).start()
    return cached


def _payload() -> dict:
    try:
        settings = json.loads((BASE / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        settings = {}
    try:
        timers = json.loads((BASE / "timers.json").read_text(encoding="utf-8"))
    except Exception:
        timers = []

    log_entries = []
    log_file = BASE / "logs" / f"{datetime.date.today().isoformat()}.jsonl"
    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines()[-14:]:
            try:
                log_entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    notes = [p for p in (BASE / "vault").rglob("*.md") if ".obsidian" not in p.parts]
    notes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    recent = [{"name": p.stem,
               "uri": "obsidian://open?path=" + urllib.parse.quote(str(p))}
              for p in notes[:5]]

    return {
        "status": state["status"],
        "weather": _weather(),
        "settings": {n: s["value"] for n, s in settings.items()},
        "timers": timers,
        "log": log_entries,
        "skills": _skills(),
        "brain": {"count": len(notes), "recent": recent},
        "ears": {"ago": round(time.time() - EARS[0], 1) if EARS[0] else None,
                 "level": round(EARS[1], 5)},
    }


def _voice_payload() -> dict:
    current = "bm_george"
    try:
        import tts

        current = tts.VOICE
    except Exception:
        try:
            data = json.loads((BASE / "voice_settings.json").read_text(encoding="utf-8"))
            current = data.get("voice", current)
        except Exception:
            pass
    return {"voices": VOICES, "current": current}


def _brain_payload() -> dict:
    import neuro

    nb = neuro.get()
    nb.reindex()
    nodes = [{"id": name, "folder": info["folder"]}
             for name, info in nb.neurons.items()]
    edges = []
    seen = set()
    for name in nb.neurons:
        for other in nb._links_of(name):
            key = tuple(sorted([name, other]))
            if key not in seen:
                seen.add(key)
                edges.append({"a": key[0], "b": key[1], "type": "link", "w": 0.3})
    for key, syn in nb.synapses.items():
        a, b = key.split("|")
        if syn["w"] >= 0.12 and a in nb.neurons and b in nb.neurons:
            edges.append({"a": a, "b": b, "type": "learned",
                          "w": round(syn["w"], 3)})
    return {"nodes": nodes, "edges": edges}


def _brain_note(name: str) -> dict:
    """Everything about one neuron: content, connections, firing history."""
    import neuro

    nb = neuro.get()
    if name not in nb.neurons:
        return {"error": "unknown neuron"}
    info = nb.neurons[name]
    path = Path(info["path"])
    text = path.read_text(encoding="utf-8")
    body = text.split("---")[-1].strip()[:1500] if text.startswith("---") else text[:1500]

    synapses = []
    for key, syn in nb.synapses.items():
        a, b = key.split("|")
        if name in (a, b) and syn["w"] > 0.02:
            synapses.append({"other": b if name == a else a, "w": round(syn["w"], 3)})
    synapses.sort(key=lambda s: -s["w"])

    fired_count, last_fired = 0, None
    act = BASE / "brain_activity.jsonl"
    if act.exists():
        for line in act.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if any(f["name"] == name for f in e.get("fired", [])):
                fired_count += 1
                last_fired = e["t"]
    last_str = ""
    if last_fired:
        last_str = datetime.datetime.fromtimestamp(last_fired).strftime("%d %b, %I:%M %p").lstrip("0")

    return {"name": name, "folder": info["folder"], "body": body,
            "links": sorted(nb._links_of(name)), "synapses": synapses[:8],
            "fired_count": fired_count, "last_fired": last_str,
            "obsidian": "obsidian://open?path=" + urllib.parse.quote(str(path))}


def _brain_activity() -> list[dict]:
    path = BASE / "brain_activity.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-25:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep TARS's console clean
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # browsers cached the old dashboard and kept showing it after
        # redesigns ("the old version isn't closed") — never cache
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/":
            html = (BASE / "dashboard" / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif route == "/brain":
            html = (BASE / "dashboard" / "brain.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif route == "/setup":
            html = (BASE / "dashboard" / "setup.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif route == "/api/setup":
            import profile

            self._send(200, json.dumps({"values": profile.public_view(),
                                        "first_run": profile.needs_setup()}
                                       ).encode(), "application/json")
        elif route == "/api/logins":
            # site names and usernames only. The passwords are never sent to
            # a web page, not even his own — there is no route that returns
            # one, so there's no bug that can leak one.
            import secrets_store

            try:
                users = json.loads((BASE / "logins.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                users = {}
            sites = sorted(n[len("site:"):] for n in secrets_store.names()
                           if n.startswith("site:"))
            self._send(200, json.dumps(
                [{"site": s, "username": users.get(s, "")} for s in sites]
            ).encode(), "application/json")
        elif route == "/hud":
            html = (BASE / "dashboard" / "hud.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif route == "/api/camera/live":
            live = {"watching": False, "hand": "", "last": "", "last_at": 0,
                    "seen": 0}
            try:
                import gestures

                live = gestures.live()
            except Exception:
                pass
            live["status"] = state.get("status", "standby")
            self._send(200, json.dumps(live).encode(), "application/json")
        elif route == "/api/camera/frame":
            stamp, blob = LATEST_JPEG
            if blob and time.time() - stamp < 5:
                self._send(200, blob, "image/jpeg")
            else:
                self._send(404, b"no frame", "text/plain")
        elif route == "/three.min.js":
            js = (BASE / "dashboard" / "three.min.js").read_bytes()
            self._send(200, js, "application/javascript")
        elif route == "/api/state":
            self._send(200, json.dumps(_payload()).encode(), "application/json")
        elif route == "/api/map":
            try:
                data = (BASE / "map_state.json").read_text(encoding="utf-8")
            except OSError:
                data = ('{"center": [-31.95, 115.86], "zoom": 11, '
                        '"label": "PERTH — HOME", "markers": [], "t": 0}')
            self._send(200, data.encode(), "application/json")
        elif route == "/api/streetview":
            try:
                data = (BASE / "street_view_state.json").read_text(encoding="utf-8")
            except OSError:
                data = ('{"active": false, "lat": -31.95, "lon": 115.86, '
                        '"label": "", "t": 0}')
            self._send(200, data.encode(), "application/json")
        elif route == "/api/proposals":
            try:
                import improve

                data = json.dumps({"proposals": improve.get_proposals()})
            except Exception:
                data = '{"proposals": []}'
            self._send(200, data.encode(), "application/json")
        elif route == "/api/routines":
            try:
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "routines_skill", BASE / "skills" / "routines" / "skill.py")
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                data = [{"name": n,
                         "when": (e.get("when") or {}).get("at")
                         or ((e.get("when") or {}).get("type") == "game"
                             and "on game start") or "",
                         "steps": len(e.get("steps", []))}
                        for n, e in mod._load().items()]
            except Exception:
                data = []
            self._send(200, json.dumps({"routines": data}).encode(),
                       "application/json")
        elif route == "/api/designs":
            out = []
            ddir = BASE / "workshop" / "designs"
            if ddir.exists():
                for scad in sorted(ddir.glob("*.scad"),
                                   key=lambda p: -p.stat().st_mtime):
                    out.append({
                        "name": scad.stem,
                        "pretty": scad.stem.replace("_", " "),
                        "png": scad.with_suffix(".png").name
                        if scad.with_suffix(".png").exists() else "",
                        "stl": scad.with_suffix(".stl").exists(),
                        "when": datetime.date.fromtimestamp(
                            scad.stat().st_mtime).strftime("%d %b")})
            self._send(200, json.dumps({"designs": out}).encode(),
                       "application/json")
        elif route.startswith("/designs/"):
            img = BASE / "workshop" / "designs" / route.split("/")[-1]
            if img.exists() and img.suffix.lower() == ".png":
                self._send(200, img.read_bytes(), "image/png")
            else:
                self._send(404, b"no", "text/plain")
        elif route == "/api/extras":
            extras = {"lists": {}, "kipp": [], "learning": []}
            # BEGIN dashboard_panel:games
            try:
                import re as _re_dp, winreg as _winreg_dp
                with _winreg_dp.OpenKey(_winreg_dp.HKEY_CURRENT_USER,
                                        r"Software\Valve\Steam") as _key_dp:
                    _sroot_dp = Path(_winreg_dp.QueryValueEx(_key_dp, "SteamPath")[0])
            except Exception:
                _sroot_dp = None
            _sgames_dp = []
            try:
                if _sroot_dp:
                    _slibs_dp = [_sroot_dp / "steamapps"]
                    _svdf_dp = _sroot_dp / "steamapps" / "libraryfolders.vdf"
                    if _svdf_dp.exists():
                        for _sm_dp in _re_dp.finditer(r'"path"\s+"([^"]+)"',
                                                      _svdf_dp.read_text(encoding="utf-8", errors="ignore")):
                            _sp_dp = Path(_sm_dp.group(1).replace("\\\\", "\\")) / "steamapps"
                            if _sp_dp.exists() and _sp_dp not in _slibs_dp:
                                _slibs_dp.append(_sp_dp)
                    for _slib_dp in _slibs_dp:
                        for _acf_dp in _slib_dp.glob("appmanifest_*.acf"):
                            _stext_dp = _acf_dp.read_text(encoding="utf-8", errors="ignore")
                            _sname_dp = _re_dp.search(r'"name"\s+"([^"]+)"', _stext_dp)
                            if not _sname_dp:
                                continue
                            _snm_dp = _sname_dp.group(1)
                            if any(w in _snm_dp.lower() for w in
                                   ("redistributable", "steamworks", "runtime", "proton")):
                                continue
                            _sgames_dp.append({"name": _snm_dp, "touched": _acf_dp.stat().st_mtime})
                    _sgames_dp.sort(key=lambda g: -g["touched"])
            except Exception:
                _sgames_dp = []
            extras["games"] = [{"name": g["name"]} for g in _sgames_dp[:10]]
            extras["games_count"] = len(_sgames_dp)
            # END dashboard_panel:games
            # BEGIN dashboard_panel:assessments
            try:
                import datetime as _dt_dp, sys as _sys_dp
                sdata = json.loads((BASE / "school.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                sdata = {"work": []}
            except Exception:
                sdata = {"work": []}
            work = [w for w in sdata.get("work", []) if not w.get("done")]
            try:
                if str(BASE) not in _sys_dp.path:
                    _sys_dp.path.insert(0, str(BASE))
                import seqta as _seqta_dp
                # cached() not data(): data() re-fetches when the cache ages
                # out, and the dashboard polls every few seconds — a login
                # round-trip inside the HTTP handler would stall the page
                # (and several polls could fire off logins at once)
                if _seqta_dp.configured():
                    done_titles = {w["what"].lower() for w in sdata.get("work", []) if w.get("done")}
                    for item in _seqta_dp.cached().get("due", []):
                        if item["what"].lower() in done_titles:
                            continue
                        label = (f"{item['what']} for {item['subject']}"
                                 if item.get("subject") else item["what"])
                        work.append({"what": label, "due": item["due"]})
            except Exception:
                pass
            try:
                _stamp_dp = _dt_dp.date.today().isoformat()
                _upcoming_dp = sorted((w for w in work if w.get("due") and w["due"] >= _stamp_dp),
                                       key=lambda w: w["due"])
                extras["assessments"] = [{"what": w["what"], "due": w["due"]}
                                          for w in _upcoming_dp[:6]]
            except Exception:
                extras["assessments"] = []
            # END dashboard_panel:assessments
            try:
                extras["lists"] = json.loads(
                    (BASE / "lists.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            try:
                lines = (BASE / "improvements.log").read_text(
                    encoding="utf-8").splitlines()
                # what happened, not just what was attempted: since the
                # proof gate, a change can be shipped OR reverted, and
                # the owner should be able to see which at a glance
                rows = []
                for line in reversed(lines[-60:]):
                    body = line.partition(" ")[2]
                    state_word = ("shipped" if body.startswith("DONE")
                                  else "reverted" if body.startswith("UNVERIFIED")
                                  else "asking" if body.startswith("PROPOSAL OFFERED")
                                  else "proposed" if body.startswith("PROPOSED")
                                  else "failed" if body.startswith("FAILED")
                                  else "")
                    if not state_word:
                        continue
                    what = body.split(":", 1)[-1].split("—")[0].strip()[:52]
                    if what and not any(r["what"] == what for r in rows):
                        rows.append({"what": what, "state": state_word})
                    if len(rows) >= 5:
                        break
                extras["kipp"] = rows
            except OSError:
                pass
            try:
                extras["learning"] = _learning()
            except Exception:
                pass
            self._send(200, json.dumps(extras).encode(), "application/json")
        elif route == "/api/voices":
            self._send(200, json.dumps(_voice_payload()).encode(), "application/json")
        elif route == "/api/brain":
            self._send(200, json.dumps(_brain_payload()).encode(), "application/json")
        elif route == "/api/brain/note":
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            name = (qs.get("name") or [""])[0]
            self._send(200, json.dumps(_brain_note(name)).encode(), "application/json")
        elif route == "/api/brain/activity":
            self._send(200, json.dumps(_brain_activity()).encode(), "application/json")
        elif route == "/camera":
            html = (BASE / "dashboard" / "camera.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif route == "/camera/stream":
            self._stream_camera()
        else:
            self._send(404, b"not found", "text/plain")

    def _stream_camera(self):
        """Live MJPEG feed from the desk webcam — localhost only, released
        the moment the page closes."""
        global LATEST_JPEG
        import cv2

        # ONE owner of the webcam at a time. When the gesture watcher is
        # running it holds the camera and publishes frames, so relay those
        # instead of opening a second capture — both grabbing device 0 ends
        # with read() failing and a black HUD.
        try:
            import gestures

            if gestures.active():
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                last = 0.0
                while gestures.active():
                    stamp, blob = LATEST_JPEG
                    if blob and stamp != last:
                        last = stamp
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg"
                                         b"\r\n\r\n" + blob + b"\r\n")
                    time.sleep(0.05)
                return
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            pass

        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not cap.isOpened():
            self._send(503, b"camera busy", "text/plain")
            return
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        tags, frame_n = [], 0
        try:
            import faces

            threading.Thread(target=faces.warmup, daemon=True).start()
        except Exception:
            faces = None
        try:
            while True:
                if _gestures_took_over():
                    break  # hand the webcam over rather than fight for it
                ok, frame = cap.read()
                if not ok:
                    break
                frame = cv2.flip(frame, 1)   # mirror: his left on the left
                # share the CLEAN frame first — snapshot skills borrow this,
                # so they never have to touch the camera hardware
                ok, clean = cv2.imencode(".jpg", frame,
                                         [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    LATEST_JPEG = (time.time(), clean.tobytes())
                # Skeletons, hands, face mesh and names — about 22ms, so it
                # keeps up with the feed instead of trailing it. The old code
                # here ran DeepFace every 30 frames and drew a plain box; the
                # box lagged two seconds behind his head, because DeepFace
                # answers "who is this", not "where is this".
                frame_n += 1
                try:
                    import vision_track

                    vision_track.annotate(frame)
                except Exception:
                    pass
                ok, jpg = cv2.imencode(".jpg", frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: " + str(len(jpg)).encode()
                                 + b"\r\n\r\n" + jpg.tobytes() + b"\r\n")
                time.sleep(1 / 15)  # ~15 fps is plenty for a desk cam
        except (ConnectionError, OSError):
            pass  # viewer closed the page
        finally:
            cap.release()

    def do_POST(self):
        if self.path == "/api/brain/feed":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            text = str(data.get("text", "")).strip()[:300]
            fired = []
            if text:
                try:
                    import neuro

                    fired = neuro.get().stimulate(text, source="feed")
                except Exception:
                    pass
            self._send(200, json.dumps({"fired": fired}).encode(), "application/json")
        elif self.path == "/api/proposals":
            # Build / Ignore click on one of Kipp's proposal cards
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            try:
                import improve

                ok = improve.decide(str(data.get("title", "")),
                                    data.get("decision") == "build")
                self._send(200 if ok else 404,
                           json.dumps({"ok": ok}).encode(), "application/json")
            except Exception:
                self._send(500, b'{"ok": false}', "application/json")
        elif self.path == "/api/say":
            # type to TARS instead of talking — same brain, same skills
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            text = str(data.get("text", "")).strip()[:800]
            if not text or BRAIN is None:
                self._send(503, b'{"error": "not ready"}', "application/json")
            elif not _TYPING.acquire(blocking=False):
                self._send(200, json.dumps(
                    {"reply": "Hang on — still finishing the last one."}
                ).encode(), "application/json")
            else:
                try:
                    import main

                    main.log("heard", f"[typed] {text}")
                    global _LAST_TYPED_NORM
                    norm = text.lower().rstrip(".!? ")
                    # only a DOUBLE-SUBMIT is suspicious. With no time limit
                    # it refused the same question asked hours apart — you
                    # can't ask the time twice in one day.
                    repeat = (norm and norm == (_LAST_TYPED_NORM or [None, 0])[0]
                              and time.time() - _LAST_TYPED_NORM[1] < 30)
                    if repeat:
                        # same exact message twice in a row — almost always
                        # means the first one didn't land, not a deliberate
                        # repeat. Same call main.py's voice loop makes.
                        reply = ("That's the same thing again — did I miss "
                                 "it, or did you mean something else?")
                        _LAST_TYPED_NORM = None
                    else:
                        _LAST_TYPED_NORM = (norm, time.time())
                        # typed on his own PC's localhost dashboard — that's
                        # him, and it must not inherit whoever spoke last
                        BRAIN.speaker_name = __import__("profile").owner()
                        reply = BRAIN.handle(text) or "..."
                    main.log("said", reply)
                    try:  # and don't print it on the page either
                        import secrets_store

                        reply = secrets_store.redact(reply)
                    except Exception:
                        pass
                    if data.get("speak") and SPEAKER is not None:
                        # flag the status while it talks — the camera HUD's
                        # speaking cue reads this, and only the VOICE loop
                        # was setting it, so typed replies lit nothing up
                        def _talk(words: str) -> None:
                            was = state.get("status", "standby")
                            set_status("speaking")
                            try:
                                SPEAKER.say(words)
                            finally:
                                set_status(was)

                        threading.Thread(target=_talk, args=(reply,),
                                         daemon=True).start()
                    self._send(200, json.dumps({"reply": reply}).encode(),
                               "application/json")
                except Exception as e:
                    self._send(500, json.dumps({"reply": f"That went wrong: {e}"}
                                               ).encode(), "application/json")
                finally:
                    _TYPING.release()
        elif self.path == "/api/routines/run":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            try:
                from skills_engine import SkillBox

                said = SkillBox(BASE).run("routines", {
                    "name": str(data.get("name", "")), "action": "run"})
                self._send(200, json.dumps({"ok": True, "said": said}).encode(),
                           "application/json")
            except Exception:
                self._send(500, b'{"ok": false}', "application/json")
        elif self.path == "/api/designs/open":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            try:
                from skills_engine import SkillBox

                msg = SkillBox(BASE).run("design", {
                    "action": "load", "name": str(data.get("name", "latest"))})
                self._send(200, json.dumps({"ok": True, "msg": msg}).encode(),
                           "application/json")
            except Exception:
                self._send(500, b'{"ok": false}', "application/json")
        elif self.path == "/api/learn":
            # the dashboard's "Teach TARS" box — typed learning requests,
            # precise where speech gets misheard. BRAIN is set by main.py.
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            request = str(data.get("request", "")).strip()[:600]
            if not request:
                self._send(400, b'{"error": "empty"}', "application/json")
            elif BRAIN is None:
                self._send(503, b'{"error": "brain not ready"}', "application/json")
            else:
                try:
                    BRAIN.skills.run(
                        "deep_task", {"task": BRAIN._learning_task(request)})
                    self._send(200, b'{"ok": true}', "application/json")
                except Exception:
                    self._send(500, b'{"error": "failed"}', "application/json")
        elif self.path.startswith("/api/logins"):
            # Saved website logins. The password goes to Windows Credential
            # Manager; the username goes to a plain file. They're separated
            # on purpose: everything in the vault gets blanked out of TARS's
            # speech, and having his own email replaced with
            # [password hidden] mid-sentence would be daft.
            import secrets_store

            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            import re

            store = BASE / "logins.json"
            try:
                users = json.loads(store.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                users = {}
            site = str(data.get("site", "")).strip().lower()
            site = re.sub(r"^https?://", "", site).split("/")[0].replace("www.", "")

            if self.path == "/api/logins/delete":
                secrets_store.forget(f"site:{site}")
                users.pop(site, None)
                store.write_text(json.dumps(users, indent=1), encoding="utf-8")
                self._send(200, b'{"ok": true}', "application/json")
            elif not site or not data.get("password"):
                self._send(200, json.dumps(
                    {"error": "I need the site and the password."}
                ).encode(), "application/json")
            else:
                secrets_store.put(f"site:{site}", str(data["password"]))
                if data.get("username"):
                    users[site] = str(data["username"])
                    store.write_text(json.dumps(users, indent=1), encoding="utf-8")
                self._send(200, json.dumps({"ok": True, "site": site}).encode(),
                           "application/json")

        elif self.path.startswith("/api/setup"):
            import profile

            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/api/setup/reveal":
                # his own details, on his own machine — people forget school
                # passwords, and he asked to be able to read them back
                self._send(200, json.dumps(profile.reveal()).encode(),
                           "application/json")
            elif self.path == "/api/setup/caller":
                import profile as _pf

                _pf.save(data)  # so the check uses what he just typed
                try:
                    import phone_call

                    ok, message = phone_call.caller_id_verified()
                except Exception as e:
                    ok, message = False, f"Couldn't check: {e}"
                self._send(200, json.dumps({"ok": ok, "message": message}
                                           ).encode(), "application/json")
            elif self.path == "/api/setup/test":
                self._send(200, json.dumps(_test_portal(data)).encode(),
                           "application/json")
            else:
                try:
                    profile.save(data)
                    name = profile.owner_or("")
                    self._send(200, json.dumps({"ok": True, "name": name}
                                               ).encode(), "application/json")
                except Exception:
                    self._send(500, b'{"ok": false}', "application/json")
        elif self.path == "/api/shutdown":
            # the window's power button: reply first, then die cleanly
            self._send(200, b'{"bye": true}', "application/json")

            def _die():
                import os
                import time as _t

                set_status("offline")
                _t.sleep(0.6)
                os._exit(0)

            threading.Thread(target=_die, daemon=True).start()
        elif self.path == "/api/voice":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            voice_id = str(data.get("id", ""))
            if voice_id in VOICE_IDS:
                path = BASE / "voice_settings.json"
                try:
                    saved = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    saved = {}
                saved.setdefault("rate", "+8%")
                saved.setdefault("smooth", False)
                if voice_id.startswith("el:"):
                    # an ElevenLabs voice is a separate setting: it's WHICH
                    # paid voice to use when a line is worth paying for, not
                    # a replacement for the local voice. The local one still
                    # handles "okay" and anything over budget, so both have
                    # to be remembered.
                    saved["eleven_voice"] = voice_id[3:]
                else:
                    saved["voice"] = voice_id
                path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                try:
                    import tts

                    if voice_id.startswith("el:"):
                        tts.ELEVEN_VOICE = voice_id[3:]
                    else:
                        tts.VOICE = voice_id
                except Exception:
                    pass
                self._send(200, json.dumps({"ok": True, "current": voice_id}).encode(),
                           "application/json")
            else:
                self._send(400, b'{"ok": false}', "application/json")
        elif self.path == "/api/settings":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            path = BASE / "settings.json"
            settings = json.loads(path.read_text(encoding="utf-8"))
            name = str(data.get("name", ""))
            if name in settings:
                if data.get("remove"):
                    del settings[name]
                else:
                    settings[name]["value"] = max(0, min(100, int(data.get("value", 50))))
                path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            self._send(200, b"{}", "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def start() -> None:
    def serve():
        # the old instance can hold the port while dying — retry FOREVER
        # rather than give up (a 15s retry window once expired and left the
        # engine with no dashboard at all; daemon thread, so looping is free)
        while True:
            try:
                ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
                return
            except OSError:
                time.sleep(2)

    threading.Thread(target=serve, daemon=True).start()
