"""TARS-native text-to-CAD: "design me a 40 millimeter cable hook" →
Claude writes a parametric OpenSCAD model → preview PNG opens + print-ready
STL saved in workshop/designs/. v2 (the owner's asks): list/load saved designs,
open any design in OpenSCAD's rotatable 3D viewer, and after each design
TARS asks whether to change anything (the brain routes the answer back
here as an iteration)."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DESIGNS = BASE / "workshop" / "designs"
OPENSCAD_WIN = r"C:\Program Files\OpenSCAD\openscad.exe"

DESCRIPTION = ("DESIGN real 3D objects from a description and manage the "
               "collection — 'design me a phone stand' (creates, previews, "
               "saves STL), 'what designs do I have' (list, optionally "
               "filtered by a word e.g. 'what fast designs do I have'), "
               "'load my cable hook design' / 'open it so I can rotate it' "
               "(opens the design in the rotatable 3D viewer). NOT the Mini "
               "CAD drawing app (cad) and NOT the CADAM website (open_app).")
ARGS = {"request": "for designing: the object and any sizes",
        "action": "'design' (default), 'list', or 'load'",
        "name": "for load: which saved design, or 'latest'",
        "filter": "for list: optional word to only show designs whose name "
                  "contains it, e.g. 'fast'"}


def _openscad() -> str:
    return OPENSCAD_WIN if sys.platform == "win32" else "openscad"


def _saved() -> list[Path]:
    if not DESIGNS.exists():
        return []
    return sorted(DESIGNS.glob("*.scad"), key=lambda p: -p.stat().st_mtime)


def _find(name: str) -> Path | None:
    scads = _saved()
    if not scads:
        return None
    name = name.strip().lower().replace(" ", "_")
    if name in ("", "latest", "it", "the last one", "last"):
        return scads[0]
    loose = name.replace("_", "")
    for p in scads:
        if name in p.stem.lower() or loose in p.stem.lower().replace("_", ""):
            return p
    import difflib

    close = difflib.get_close_matches(name, [p.stem.lower() for p in scads],
                                      n=1, cutoff=0.5)
    return next((p for p in scads if p.stem.lower() == close[0]), None) \
        if close else None


def _from_photo(request: str, size_hint: str = "") -> str:
    """'Design a stand for this' — TARS looks through the camera, describes
    the object honestly, and designs around it. A photo alone can't give
    true millimetres, so he asks for ONE real measurement unless the owner
    already said one (that honesty beats a beautifully-wrong part)."""
    import base64
    import io
    import re

    import requests

    sys.path.insert(0, str(BASE))
    import faces  # its get_frame() is the stream-safe camera path

    frame = faces.get_frame()
    if frame is None:
        return "The camera didn't answer, so I can't see the object."
    if float(frame.mean()) < 12:
        return "It's too dark to see the object — more light and try again."
    try:
        import cv2
        from PIL import Image

        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if img.width > 1280:
            img = img.resize((1280, round(img.height * 1280 / img.width)))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        shot = buf.getvalue()
        r = requests.post("http://127.0.0.1:11434/api/chat", json={
            "model": "qwen2.5vl:7b", "stream": False, "keep_alive": "30m",
            "messages": [{"role": "user", "images": [base64.b64encode(shot).decode()],
                          "content": (
                "the owner is holding an object up to the camera and wants a 3D "
                "part designed for it. Describe ONLY the object: what it is, "
                "its shape, and its rough proportions (e.g. 'roughly twice as "
                "tall as it is wide'). Two sentences, no guessing at exact "
                "millimetres.")}],
            "options": {"num_ctx": 8192, "num_predict": 160}}, timeout=180)
        r.raise_for_status()
        seen = r.json()["message"]["content"].strip()
    except Exception:
        return "My eyes didn't answer — is the vision model still loading?"

    if not re.search(r"\d+\s*(mm|millimet|cm|centimet|inch)", size_hint.lower()
                     + " " + request.lower()):
        (BASE / "photo_design.json").write_text(json.dumps(
            {"seen": seen, "request": request}), encoding="utf-8")
        return (f"I can see {seen[:160]} To get the fit right I need one "
                f"real measurement — how wide is it, in millimetres?")
    return _design_task(f"{request}. The object, seen through the camera: "
                        f"{seen}. the owner's measurement: {size_hint or request}")


def _tweak(request: str, target: str = "latest") -> str:
    """INSTANT dimension changes — no big brain. The model is parametric, so
    'make it 20 millimetres taller' is one number in one line. OpenSCAD's
    viewer auto-reloads the file, so the change appears in about a second
    (big-brain edits take minutes; this is the live-tweaking path)."""
    import json as _json
    import re
    import threading

    import requests

    path = _find(target) or (_saved()[0] if _saved() else None)
    if path is None:
        return "There's no design to tweak."
    src = path.read_text(encoding="utf-8")
    variables = re.findall(r"^\s*(\w+)\s*=\s*([\d.]+)\s*;(.*)$", src, re.M)
    if not variables:
        return ("That design has no adjustable numbers — ask me to change "
                "it properly and the big brain will rework it.")
    menu = "\n".join(f"{n} = {v}{c[:40]}" for n, v, c in variables[:25])
    try:
        r = requests.post("http://127.0.0.1:11434/api/chat", json={
            "model": "qwen2.5:7b", "stream": False, "format": "json",
            "keep_alive": "2h",
            "messages": [{"role": "user", "content":
                f"OpenSCAD model variables (millimetres):\n{menu}\n\n"
                f"the owner says: {request!r}\n"
                "Which ONE variable changes, and to what new number? Reply "
                'JSON: {"var": "<exact name>", "value": <number>} — or '
                '{"var": ""} if no single variable covers it.'}],
            "options": {"temperature": 0}}, timeout=60)
        r.raise_for_status()
        pick = _json.loads(r.json()["message"]["content"])
    except Exception:
        return "My quick-change brain didn't answer — try saying it again."
    var, value = str(pick.get("var", "")), pick.get("value")
    if not var or value is None or var not in [n for n, _, _ in variables]:
        return ("That needs a proper rework — say 'change the design' and "
                "the big brain will take it on.")
    old = next(v for n, v, _ in variables if n == var)
    new_src = re.sub(rf"^(\s*{re.escape(var)}\s*=\s*)[\d.]+\s*;",
                     rf"\g<1>{value};", src, count=1, flags=re.M)
    path.write_text(new_src, encoding="utf-8")

    def rerender():  # STL/PNG in the background; the viewer reloads itself
        for out in (".stl", ".png"):
            cmd = [_openscad(), "-o", str(path.with_suffix(out))]
            if out == ".png":
                cmd += ["--imgsize=1000,750", "--viewall", "--autocenter"]
            try:
                subprocess.run(cmd + [str(path)], capture_output=True,
                               timeout=180)
            except Exception:
                pass

    threading.Thread(target=rerender, daemon=True).start()
    return (f"Done — {var.replace('_', ' ')} is now {value} instead of "
            f"{old}. The viewer will refresh itself.")


def run(args: dict) -> str:
    action = str(args.get("action") or "design").strip().lower()

    if action == "list":
        scads = _saved()
        if not scads:
            return "No saved designs yet — say design me something."
        keyword = str(args.get("filter") or "").strip().lower()
        if keyword:
            scads = [p for p in scads if keyword in p.stem.lower().replace("_", " ")]
            if not scads:
                return f"No designs matching '{keyword}'."
        import datetime

        items = [f"{p.stem.replace('_', ' ')} ({datetime.date.fromtimestamp(p.stat().st_mtime):%d %b})"
                 for p in scads[:8]]
        return (f"You've got {len(scads)} design{'s' if len(scads) != 1 else ''}"
                + (f" matching '{keyword}'" if keyword else "") + ": "
                + "; ".join(items)
                + ". Say load, then the name, to open one in the 3D viewer.")

    if action in ("load", "open", "rotate", "show"):
        p = _find(str(args.get("name") or "latest"))
        if p is None:
            return ("I can't find that design. Say 'what designs do I have' "
                    "to hear the list.")
        # the owner's pick (2026-08-08): the OpenSCAD viewer is THE viewer —
        # professional orbit/zoom + live tweakable dimensions
        try:
            subprocess.Popen([_openscad(), str(p)], cwd=str(DESIGNS))
            return (f"Opening {p.stem.replace('_', ' ')} in the 3D viewer — "
                    "drag to rotate, scroll to zoom, and the numbers in the "
                    "side panel are live dimensions.")
        except OSError:
            pass
        stl = p.with_suffix(".stl")
        mini_cad = BASE / "workshop" / "mini_cad_3d.py"
        if stl.exists() and mini_cad.exists():  # fallback viewer
            python = (str(BASE / "runtime" / "pythonw.exe")
                      if sys.platform == "win32"
                      else (sys.executable or "python3"))
            try:
                subprocess.Popen([python, "-s", str(mini_cad), str(stl)],
                                 cwd=str(mini_cad.parent))
                return (f"OpenSCAD wouldn't start, so {p.stem.replace('_', ' ')} "
                        "is opening in Mini CAD instead — drag to spin it.")
            except OSError:
                pass
        return "Neither viewer would open — tell Claude."

    if action == "photo":
        return _from_photo(str(args.get("request") or ""),
                           str(args.get("size") or ""))

    if action in ("dimensions", "params", "size"):
        p = _find(str(args.get("name") or "latest"))
        if p is None:
            return "I don't have that design."
        import re

        vars_ = re.findall(r"^\s*(\w+)\s*=\s*([\d.]+)\s*;",
                           p.read_text(encoding="utf-8"), re.M)
        if not vars_:
            return f"{p.stem.replace('_', ' ')} has no adjustable dimensions."
        return (f"{p.stem.replace('_', ' ')}: "
                + ", ".join(f"{n.replace('_', ' ')} {v} millimetres"
                            for n, v in vars_[:7]) + ".")

    if action == "tweak":
        return _tweak(str(args.get("request") or ""),
                      str(args.get("name") or "latest"))

    # default: design something new
    request = str(args.get("request") or "").strip()
    if not request:
        return "Design what, exactly? Give me the object and any sizes."
    return _design_task(request)


def _design_task(request: str) -> str:
    import json

    DESIGNS.mkdir(parents=True, exist_ok=True)
    task = (
        f"TEXT-TO-CAD DESIGN JOB. the owner asked: {request!r}\n"
        f"1. Write a clean PARAMETRIC OpenSCAD model to a new file in "
        f"{DESIGNS}\\<short_snake_name>.scad — adjustable dimensions as "
        f"named variables at the top with comments, sensible printable "
        f"defaults ($fn=64 for curves), units in millimeters.\n"
        f"2. Render it with OpenSCAD at \"{_openscad()}\":\n"
        f"   preview: openscad -o <name>.png --imgsize=1000,750 --viewall "
        f"--autocenter <name>.scad\n"
        f"   STL:     openscad -o <name>.stl <name>.scad\n"
        f"   Both outputs in the designs folder. Fix and re-render until "
        f"clean.\n"
        f"3. Do NOT open the PNG. Instead auto-open the interactive 3D "
        f"viewer: launch \"{_openscad()}\" <name>.scad DETACHED (e.g. "
        f"subprocess.Popen, do not wait on it) so the owner immediately gets "
        f"the rotatable view with live dimensions.\n"
        f"4. End SPOKEN with exactly this question: 'It's on your screen — "
        f"drag to rotate. Want me to change anything?' — after naming the "
        f"object, its key dimensions, and the STL filename."
    )
    spec = importlib.util.spec_from_file_location(
        "deep_task_skill", BASE / "skills" / "deep_task" / "skill.py")
    dt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dt)
    dt.run({"task": task})
    return ("Designing it now — the big brain is drawing up your "
            f"{request.split(',')[0][:40]}. I'll show you the preview and "
            "ask if you want changes.")
