"""Draw interactive-looking diagrams styled like TARS's own dashboard.

Don't-reinvent-it: the actual box-and-arrow layout is done by Mermaid.js
(https://mermaid.js.org), a maintained, widely-used diagramming library —
vendored locally as mermaid.min.js (same pattern the dashboard already uses
for three.min.js) so it works with no internet needed once saved. This skill
is a thin wrapper: it turns a plain-English chain like "A -> B -> C" into a
Mermaid flowchart definition, wraps it in a page that reuses the exact CSS
variables from dashboard/index.html (--bg, --panel, --cyan, ...) so it reads
as part of the same Jarvis-style HUD, adds a couple of small CSS/JS touches
(animated dashed edges, glow-on-hover nodes, wheel-zoom + drag-pan) so it
*feels* interactive rather than a static picture, and opens it as a
chromeless app window — the same trick tars_window.py uses for the brain
and dashboard pages.
"""
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SKILL_DIR = Path(__file__).resolve().parent
MERMAID_JS = SKILL_DIR / "mermaid.min.js"
OUT_DIR = BASE / "workshop" / "diagrams"

DESCRIPTION = ("Draw and design a diagram — flowchart, system/architecture diagram, "
               "or mind map — that looks interactive and styled like TARS's own "
               "dashboard (dark HUD look, glowing cyan lines, hover/zoom/pan). "
               "E.g. 'draw a diagram of my morning routine', 'design a system "
               "diagram showing how my skills talk to the brain', 'sketch a "
               "flowchart for the login process'. Say 'what diagrams do I have' "
               "to list saved ones, or name one to reopen it. NOT for 3D objects "
               "(design/cad) and NOT for the brain page's own visual style "
               "(redesign_brain).")
ARGS = {
    "spec": ("what the diagram should show, as a simple chain: 'Wake up -> Check "
              "phone -> Coffee -> Work', or several chains separated by a newline "
              "or semicolon to branch, e.g. 'TARS -> Skills; Skills -> Brain; "
              "Skills -> Vault'. Reused node names automatically connect to the "
              "same box. Leave as 'list' to hear saved diagrams, or give a saved "
              "diagram's title to reopen it instead of making a new one."),
    "title": "short title for a new diagram, e.g. 'Morning Routine' (optional)",
}

_ARROW_RE = re.compile(r"->|→")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return s or "diagram"


def _node_id(existing: dict, label: str) -> str:
    label = label.strip()
    if label in existing:
        return existing[label]
    nid = f"n{len(existing)}"
    existing[label] = nid
    return nid


def _spec_to_mermaid(spec: str) -> str:
    """Turn 'A -> B -> C; A -> D' into a Mermaid flowchart definition."""
    spec = spec.strip()
    low = spec.lower()
    if low.startswith("graph") or low.startswith("flowchart"):
        return spec  # owner/router already handed us real Mermaid syntax

    chains = re.split(r"[;\n]+", spec)
    ids: dict[str, str] = {}
    lines = ["flowchart LR"]
    for chain in chains:
        chain = chain.strip()
        if not chain:
            continue
        if _ARROW_RE.search(chain):
            steps = [s.strip() for s in _ARROW_RE.split(chain) if s.strip()]
        else:
            steps = [s.strip() for s in re.split(r"\bthen\b", chain, flags=re.I) if s.strip()]
        if len(steps) < 2:
            if steps:
                nid = _node_id(ids, steps[0])
                esc = steps[0].replace('"', "'")
                lines.append(f'  {nid}["{esc}"]')
            continue
        for a, b in zip(steps, steps[1:]):
            aid, bid = _node_id(ids, a), _node_id(ids, b)
            ea, eb = a.replace('"', "'"), b.replace('"', "'")
            lines.append(f'  {aid}["{ea}"] --> {bid}["{eb}"]')
    if len(lines) == 1:
        raise ValueError("empty spec")
    return "\n".join(lines)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title} — TARS</title>
<style>
:root{{
  --bg:#04060c; --panel:rgba(13,20,33,.62); --panel-edge:rgba(90,140,200,.14);
  --cyan:#46d4ff; --amber:#ffb340; --violet:#a78bfa; --green:#3ddc97; --red:#ff5d7a;
  --txt:#d7e3f0; --dim:#5d7288; --faint:#3a4a5c;
}}
*{{box-sizing:border-box;margin:0}}
html,body{{height:100%}}
body{{background:
    radial-gradient(ellipse at 50% 20%,rgba(70,212,255,.06),transparent 60%),
    repeating-linear-gradient(0deg,rgba(90,140,200,.035) 0 1px,transparent 1px 3px),
    var(--bg);
  color:var(--txt);overflow:hidden;
  font:14px/1.5 "Segoe UI Variable Display","Segoe UI",system-ui,sans-serif}}
header{{position:fixed;top:0;left:0;right:0;z-index:5;display:flex;align-items:center;
  gap:12px;padding:14px 20px}}
#title{{font-size:15px;font-weight:600;letter-spacing:5px;text-transform:uppercase;
  color:#eaf6ff;background:rgba(5,9,16,.72);border:1px solid var(--panel-edge);
  padding:7px 16px;border-radius:9px;backdrop-filter:blur(8px)}}
#hint{{color:var(--dim);font-size:11px;letter-spacing:1px}}
#stage{{position:absolute;inset:0;cursor:grab;display:flex;align-items:center;
  justify-content:center}}
#stage.grabbing{{cursor:grabbing}}
#canvas{{transform-origin:50% 50%;transition:transform .05s linear}}
.mermaid{{background:transparent!important}}
/* nodes glow like the rest of the HUD, and light up on hover to feel alive */
.node rect,.node polygon,.node circle{{
  fill:var(--panel)!important;stroke:var(--cyan)!important;stroke-width:1.3px!important;
  filter:drop-shadow(0 0 4px rgba(70,212,255,.35));transition:filter .2s}}
.node:hover rect,.node:hover polygon,.node:hover circle{{
  filter:drop-shadow(0 0 12px rgba(70,212,255,.85))!important;cursor:pointer}}
.nodeLabel,.edgeLabel{{color:var(--txt)!important;background:transparent!important}}
/* animated dashes on the connecting lines so it reads as "live" data flow */
.edgePath path{{stroke:var(--cyan)!important;stroke-width:1.6px!important;
  stroke-dasharray:5,4;animation:dash 1.1s linear infinite;
  filter:drop-shadow(0 0 3px rgba(70,212,255,.5))}}
@keyframes dash{{to{{stroke-dashoffset:-18}}}}
.marker{{fill:var(--cyan)!important;stroke:var(--cyan)!important}}
</style></head>
<body>
<header><div id="title">{title}</div><div id="hint">scroll to zoom · drag to pan</div></header>
<div id="stage"><div id="canvas"><div class="mermaid">
{mermaid_def}
</div></div></div>
<script src="mermaid.min.js"></script>
<script>
mermaid.initialize({{
  startOnLoad:true, theme:'base', securityLevel:'loose',
  themeVariables:{{
    background:'#04060c', primaryColor:'rgba(13,20,33,.85)', primaryTextColor:'#d7e3f0',
    primaryBorderColor:'#46d4ff', lineColor:'#46d4ff', secondaryColor:'#0d1421',
    tertiaryColor:'#0d1421', fontFamily:'Segoe UI, system-ui, sans-serif'
  }},
  flowchart:{{curve:'basis'}}
}});
// tiny wheel-zoom + drag-pan so a static diagram behaves like part of the HUD
(function(){{
  var stage=document.getElementById('stage'), canvas=document.getElementById('canvas');
  var scale=1, x=0, y=0, dragging=false, lastX=0, lastY=0;
  function apply(){{canvas.style.transform='translate('+x+'px,'+y+'px) scale('+scale+')';}}
  stage.addEventListener('wheel', function(e){{
    e.preventDefault();
    scale=Math.min(2.5, Math.max(0.4, scale + (e.deltaY<0?0.1:-0.1)));
    apply();
  }}, {{passive:false}});
  stage.addEventListener('mousedown', function(e){{dragging=true; lastX=e.clientX; lastY=e.clientY; stage.classList.add('grabbing');}});
  window.addEventListener('mouseup', function(){{dragging=false; stage.classList.remove('grabbing');}});
  window.addEventListener('mousemove', function(e){{
    if(!dragging) return;
    x += e.clientX-lastX; y += e.clientY-lastY; lastX=e.clientX; lastY=e.clientY; apply();
  }});
}})();
</script>
</body></html>
"""


def _open_file(path: Path):
    url = path.resolve().as_uri()
    brave = None
    import os
    for cand in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ):
        if cand.exists():
            brave = cand
            break
    if brave:
        try:
            subprocess.Popen([str(brave), f"--app={url}", "--window-size=1200,800"])
            return
        except OSError:
            pass
    webbrowser.open(url)


def _saved() -> list[Path]:
    if not OUT_DIR.exists():
        return []
    return sorted(OUT_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)


def run(args: dict) -> str:
    spec = str(args.get("spec", "")).strip()
    title = str(args.get("title", "")).strip()

    if not spec or spec.lower() in ("list", "what diagrams do i have", "list diagrams"):
        files = _saved()
        if not files:
            return "I haven't drawn any diagrams yet — describe one and I'll sketch it."
        names = ", ".join(p.stem.replace("_", " ") for p in files[:8])
        return f"You've got {len(files)} saved diagram{'s' if len(files) != 1 else ''}: {names}."

    # reopen an existing one if the spec names it and doesn't look like a chain
    if not _ARROW_RE.search(spec) and " then " not in spec.lower():
        for p in _saved():
            if p.stem.replace("_", " ").lower() == spec.lower() or _slug(spec) == p.stem:
                _open_file(p)
                return f"Reopened your '{p.stem.replace('_', ' ')}' diagram."

    if not MERMAID_JS.exists():
        return "My diagram library file is missing, so I can't draw one right now."

    try:
        mermaid_def = _spec_to_mermaid(spec)
    except ValueError:
        return "I didn't catch a clear chain to diagram — try 'A -> B -> C'."

    if not title:
        first_chain = re.split(r"[;\n]+", spec)[0]
        first_node = _ARROW_RE.split(first_chain)[0].strip() if _ARROW_RE.search(first_chain) else first_chain.strip()
        title = (first_node[:40] or "Diagram").title()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(title) or f"diagram_{int(time.time())}"
    out_path = OUT_DIR / f"{slug}.html"
    html = _PAGE.format(title=title.replace("<", "").replace(">", ""), mermaid_def=mermaid_def)
    out_path.write_text(html, encoding="utf-8")

    # vendor the js next to every diagram so relative <script src> keeps working
    local_js = OUT_DIR / "mermaid.min.js"
    if not local_js.exists():
        local_js.write_bytes(MERMAID_JS.read_bytes())

    _open_file(out_path)
    return f"Drew it — '{title}' is up on screen, HUD-styled. Scroll to zoom, drag to pan."
