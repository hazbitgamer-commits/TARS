"""TARS dashboard — a tiny localhost web server living inside the TARS process.

Serves dashboard/index.html plus a JSON state API, and accepts personality
slider changes (they apply to the very next reply, since the brain re-reads
settings.json every time).
"""
import datetime
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).parent
BRAIN = None  # set by main.py — used by the "Teach TARS" box
PORT = 8765

state = {"status": "starting"}
_cache: dict = {"skills": (0.0, []), "weather": (0.0, "")}
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
VOICE_IDS = {v["id"] for v in VOICES}


def set_status(s: str) -> None:
    state["status"] = s


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
            try:
                extras["lists"] = json.loads(
                    (BASE / "lists.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            try:
                lines = (BASE / "improvements.log").read_text(
                    encoding="utf-8").splitlines()
                extras["kipp"] = [l.split(" ", 1)[1] for l in lines
                                  if "DONE: " in l or "PROPOSED" in l][-4:]
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
        import cv2

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
                ok, frame = cap.read()
                if not ok:
                    break
                # share the CLEAN frame first — snapshot skills borrow this,
                # so they never have to touch the camera hardware
                ok, clean = cv2.imencode(".jpg", frame,
                                         [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    global LATEST_JPEG
                    LATEST_JPEG = (time.time(), clean.tobytes())
                # nametags: refresh every ~2s, never block the feed on loading
                frame_n += 1
                if faces is not None and frame_n % 30 == 1:
                    try:
                        tags = faces.identify(frame, wait=False)
                    except Exception:
                        tags = []
                for t in tags:
                    x, y, w, h = t["box"]
                    label = t["name"] or "unknown"
                    color = (80, 220, 120) if t["name"] else (120, 120, 200)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                    cv2.putText(frame, label, (x, max(20, y - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
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
                saved["voice"] = voice_id
                saved.setdefault("rate", "+8%")
                saved.setdefault("smooth", False)
                path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
                try:
                    import tts

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
