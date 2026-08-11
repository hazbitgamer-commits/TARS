"""Redesign the look of TARS's 3D brain map — dashboard/brain.html.

The brain page draws each memory as a circle ("node") with connecting lines
("edges") between related ones. All of its visual knobs — circle size, line
thickness, colours, and whether the legend shows — live in one small STYLE /
COLORS / AGENT_STYLE block near the top of that file's <script>, plus a
handful of CSS variables in its <style> block. This skill edits those in
place with regex, so it never has to touch the drawing logic itself.
"""
import re
from pathlib import Path

DESCRIPTION = ("Redesign the LOOK of TARS's brain visualization page (the neuron "
               "map you get from 'show me the brain', served at "
               "dashboard/brain.html) — shrink or grow the node circles, thin or "
               "thicken the connection lines, swap the colour palette (changes "
               "categories, agents, and accent colours together), or show/hide "
               "the legend. E.g. 'make the brain circles smaller', 'thinner lines "
               "on the brain', 'change the brain's colours', 'add a legend to the "
               "brain'. NOT for opening the brain page — that's open_brain — and "
               "NOT for anything other than its visual style.")
ARGS = {"request": "plain-English description of the visual change wanted, e.g. "
                    "'smaller circles, thinner lines, new colours, add a legend'"}

BRAIN_HTML = (Path(__file__).resolve().parents[2] / "dashboard" / "brain.html")

# Palette 0 must match the colours currently baked into brain.html (the
# starting point). Each later entry is a full alternate look: category
# colours, agent colours, the HUD/panel accent, the learned-synapse colour,
# and the plain-link edge colour — everything gets swapped together.
PALETTES = [
    {"colors": ["#2ecc71", "#2bc9ff", "#ffb14d", "#b06cff", "#7f93a8"],
     "agents": ["#4dd2ff", "#ffc23d", "#b06cff", "#2ecc71", "#ff9f43"],
     "accent": "#2bc9ff", "synapse": "255,77,141", "edge": "90,130,170"},
    {"colors": ["#ff9f43", "#2dd4bf", "#c084fc", "#fb7185", "#94a3b8"],
     "agents": ["#38bdf8", "#fbbf24", "#f472b6", "#34d399", "#fb923c"],
     "accent": "#a78bfa", "synapse": "255,176,32", "edge": "120,130,150"},
    {"colors": ["#f43f5e", "#22d3ee", "#facc15", "#818cf8", "#a3a3a3"],
     "agents": ["#34d399", "#fb923c", "#e879f9", "#38bdf8", "#facc15"],
     "accent": "#22d3ee", "synapse": "244,63,94", "edge": "110,120,140"},
]
CATEGORY_KEYS = ["About the owner", "Knowledge", "People", "Projects", "vault"]
AGENT_KEYS = ["Scout", "Archivist", "Librarian", "Curator", "Kipp"]


def _get_style(html: str) -> dict:
    m = re.search(r"const STYLE=\{(.*?)\};", html, re.S)
    if not m:
        raise ValueError("couldn't find the STYLE block in brain.html")
    style = {}
    for key, val in re.findall(r'(\w+)\s*:\s*("[^"]*"|[-\d.]+|true|false)', m.group(1)):
        if val == "true":
            style[key] = True
        elif val == "false":
            style[key] = False
        elif val.startswith('"'):
            style[key] = val.strip('"')
        else:
            style[key] = float(val) if "." in val else int(val)
    return style


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


def _write_style(html: str, s: dict) -> str:
    body = (f"nodeBase:{_fmt(s['nodeBase'])},nodeMax:{_fmt(s['nodeMax'])},"
            f"nodeMul:{_fmt(s['nodeMul'])},\n             "
            f"lineNormal:{_fmt(s['lineNormal'])},"
            f"lineLearnedBase:{_fmt(s['lineLearnedBase'])},"
            f"lineLearnedMul:{_fmt(s['lineLearnedMul'])},\n             "
            f"legend:{_fmt(s['legend'])},edgeNormal:{_fmt(s['edgeNormal'])},"
            f"synapse:{_fmt(s['synapse'])}")
    return re.sub(r"const STYLE=\{.*?\};", f"const STYLE={{{body}}};", html, count=1, flags=re.S)


def _current_palette_index(html: str) -> int:
    m = re.search(r'const COLORS=\{"About the owner":"(#[0-9a-fA-F]{6})"', html)
    if not m:
        return -1
    hexval = m.group(1).lower()
    for i, p in enumerate(PALETTES):
        if p["colors"][0].lower() == hexval:
            return i
    return -1


def _write_palette(html: str, p: dict) -> str:
    colors_body = ",".join(f'"{k}":"{c}"' for k, c in zip(CATEGORY_KEYS, p["colors"]))
    html = re.sub(r"const COLORS=\{.*?\};", f"const COLORS={{{colors_body}}};", html, count=1, flags=re.S)
    agents_body = ",".join(f'{k}:"{c}"' for k, c in zip(AGENT_KEYS, p["agents"]))
    html = re.sub(r"const AGENT_STYLE=\{.*?\};", f"const AGENT_STYLE={{{agents_body}}};", html, count=1, flags=re.S)
    html = re.sub(r"--accent:#[0-9a-fA-F]{6};", f"--accent:{p['accent']};", html, count=1)
    html = re.sub(r"--synapse:#[0-9a-fA-F]{6};", f"--synapse:#{'%02x%02x%02x' % tuple(int(x) for x in p['synapse'].split(','))};", html, count=1)
    style = _get_style(html)
    style["synapse"] = p["synapse"]
    style["edgeNormal"] = p["edge"]
    return _write_style(html, style)


def run(args: dict) -> str:
    request = str(args.get("request", "")).strip().lower()
    if not BRAIN_HTML.exists():
        return "I can't find the brain page file, so I couldn't redesign it."

    html = BRAIN_HTML.read_text(encoding="utf-8")
    style = _get_style(html)
    changes = []

    if any(w in request for w in ("smaller", "shrink", "tiny")):
        style["nodeBase"] = round(max(3, style["nodeBase"] * 0.7), 2)
        style["nodeMax"] = round(max(3, style["nodeMax"] * 0.7), 2)
        changes.append("made the circles smaller")
    elif any(w in request for w in ("bigger", "larger", "grow")):
        style["nodeBase"] = round(style["nodeBase"] * 1.3, 2)
        style["nodeMax"] = round(style["nodeMax"] * 1.3, 2)
        changes.append("made the circles bigger")

    if any(w in request for w in ("thin", "less thick", "lighter line")):
        style["lineNormal"] = round(max(0.2, style["lineNormal"] * 0.6), 2)
        style["lineLearnedBase"] = round(max(0.2, style["lineLearnedBase"] * 0.6), 2)
        style["lineLearnedMul"] = round(max(0.3, style["lineLearnedMul"] * 0.6), 2)
        changes.append("made the lines thinner")
    elif any(w in request for w in ("thick", "thicker", "bolder")):
        style["lineNormal"] = round(style["lineNormal"] * 1.4, 2)
        style["lineLearnedBase"] = round(style["lineLearnedBase"] * 1.4, 2)
        style["lineLearnedMul"] = round(style["lineLearnedMul"] * 1.4, 2)
        changes.append("made the lines thicker")

    if "legend" in request:
        if any(w in request for w in ("hide", "remove", " off", "no legend")):
            style["legend"] = False
            changes.append("hid the legend")
        else:
            style["legend"] = True
            changes.append("turned the legend on")

    html = _write_style(html, style)

    if any(w in request for w in ("colour", "color")):
        idx = _current_palette_index(html)
        nxt = PALETTES[(idx + 1) % len(PALETTES)]
        html = _write_palette(html, nxt)
        changes.append("gave it a new colour palette")

    if not changes:
        return ("I didn't catch a specific look to change there — try things like "
                "'smaller circles', 'thinner lines', 'new colours', or 'add a legend'.")

    BRAIN_HTML.write_text(html, encoding="utf-8")
    return "Brain redesigned — " + ", ".join(changes) + ". Refresh the brain page to see it."
