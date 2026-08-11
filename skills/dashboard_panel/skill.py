"""Add or remove a data panel (card) on the TARS dashboard's home screen.

Edits three things in place, each wrapped in matching BEGIN/END marker
comments so a later "remove" can find and strip exactly what was added,
and running "add" twice never duplicates anything:
  - dashboard/index.html   -> the card itself, next to an existing card
  - dashboard/index.html   -> a small block inside pollExtras() that fills it
  - dashboard.py           -> extra data for it inside the /api/extras route

dashboard.py reads dashboard/index.html fresh on every request, so changes
show up on the next browser refresh — no restart needed.

Currently knows two panels: Assessments, showing upcoming school work/tests
straight from school.json (the same file the school skill reads/writes),
merged with SEQTA if the owner has that connected; and Steam Games, showing
what's installed (same library lookup as the steam skill). More panel
types can be added later by extending PANELS below.
"""
import re
from pathlib import Path

DESCRIPTION = ("Add or remove a data PANEL (a card) on the TARS dashboard's home "
               "screen (the page from 'open the dashboard') — an actual box on "
               "screen, not a spoken list. Currently supports an Assessments "
               "panel (upcoming school work/tests) and a Steam Games panel "
               "(installed games). E.g. 'add an assessment panel underneath "
               "shopping on the dashboard', 'add a games panel above timers', "
               "'remove the assessments panel from the dashboard'. NOT for the "
               "brain page's look (redesign_brain), NOT for opening the "
               "dashboard (open_dashboard), and NOT for asking what's due or "
               "what games are installed out loud (school, steam).")
ARGS = {"request": "plain-English description, e.g. 'add an assessment panel "
                    "underneath shopping' or 'remove the games panel'"}

BASE = Path(__file__).resolve().parents[2]  # was hardcoded to the owner's C: path
INDEX_HTML = BASE / "dashboard" / "index.html"
DASHBOARD_PY = BASE / "dashboard.py"

# known anchor cards in the left column of the dashboard, by the text inside
# their <h3>...</h3>
CARD_LABELS = {"weather": "Weather — Perth", "timers": "Timers",
                "todo": "To-do", "to-do": "To-do", "to do": "To-do",
                "shopping": "Shopping", "assessments": "Assessments",
                "games": "Steam Games", "steam": "Steam Games",
                "kipp": "Kipp"}

PANELS = {
    "assessments": {
        "mark": "assessments",
        "title": "Assessments",
        "empty": "nothing due",
        "source": "your school list",
        "card": ('    <div class="card" style="flex:1"><h3>Assessments</h3>'
                 '<div id="assessments" class="empty">nothing due</div></div>\n'),
        "js": ('    const aEl = document.getElementById("assessments");\n'
               '    if(aEl){\n'
               '      const items = x.assessments || [];\n'
               '      if(items.length){ aEl.className=""; aEl.innerHTML = items.slice(0,6).map(i =>\n'
               '        `<div class="rowitem"><span>${esc(i.what)}</span>'
               '<span class="when">${esc(i.due||"")}</span></div>`).join("");\n'
               '      } else { aEl.className = "empty"; aEl.textContent = "nothing due"; }\n'
               '    }\n'),
        "py": ('            try:\n'
               '                import datetime as _dt_dp, sys as _sys_dp\n'
               '                sdata = json.loads((BASE / "school.json").read_text(encoding="utf-8"))\n'
               '            except (OSError, json.JSONDecodeError):\n'
               '                sdata = {"work": []}\n'
               '            except Exception:\n'
               '                sdata = {"work": []}\n'
               '            work = [w for w in sdata.get("work", []) if not w.get("done")]\n'
               '            try:\n'
               '                if str(BASE) not in _sys_dp.path:\n'
               '                    _sys_dp.path.insert(0, str(BASE))\n'
               '                import seqta as _seqta_dp\n'
               '                if _seqta_dp.configured():\n'
               '                    done_titles = {w["what"].lower() for w in sdata.get("work", []) if w.get("done")}\n'
               '                    for item in _seqta_dp.data().get("due", []):\n'
               '                        if item["what"].lower() in done_titles:\n'
               '                            continue\n'
               '                        label = (f"{item[\'what\']} for {item[\'subject\']}"\n'
               '                                 if item.get("subject") else item["what"])\n'
               '                        work.append({"what": label, "due": item["due"]})\n'
               '            except Exception:\n'
               '                pass\n'
               '            try:\n'
               '                _stamp_dp = _dt_dp.date.today().isoformat()\n'
               '                _upcoming_dp = sorted((w for w in work if w.get("due") and w["due"] >= _stamp_dp),\n'
               '                                       key=lambda w: w["due"])\n'
               '                extras["assessments"] = [{"what": w["what"], "due": w["due"]}\n'
               '                                          for w in _upcoming_dp[:6]]\n'
               '            except Exception:\n'
               '                extras["assessments"] = []\n'),
    },
    "kipp": {
        "mark": "kipp",
        "title": "Kipp",
        "empty": "nothing lately",
        "source": "Kipp's improvement log",
        "card": ('    <div class="card" style="flex:1"><h3>Kipp</h3>'
                 '<div id="kipp" class="empty">nothing lately</div></div>\n'),
        "js": ('    const kEl = document.getElementById("kipp");\n'
               '    if(kEl){\n'
               '      const items = x.kipp || [];\n'
               '      if(items.length){ kEl.className=""; kEl.innerHTML = items.map(i =>\n'
               '        `<div class="rowitem"><span>${esc(i.what)}</span>'
               '<span class="when">${esc(i.state)}</span></div>`).join("");\n'
               '      } else { kEl.className = "empty"; kEl.textContent = "nothing lately"; }\n'
               '    }\n'),
        "py": ('            _kipp_dp = []\n'
               '            try:\n'
               '                _klines_dp = (BASE / "improvements.log").read_text(\n'
               '                    encoding="utf-8", errors="replace").splitlines()[-40:]\n'
               '                for _kl_dp in reversed(_klines_dp):\n'
               '                    _kbody_dp = _kl_dp.partition(" ")[2]\n'
               '                    if _kbody_dp.startswith("DONE"):\n'
               '                        _kstate_dp = "shipped"\n'
               '                    elif _kbody_dp.startswith("UNVERIFIED"):\n'
               '                        _kstate_dp = "reverted"\n'
               '                    elif _kbody_dp.startswith("PROPOSAL OFFERED"):\n'
               '                        _kstate_dp = "asking"\n'
               '                    elif _kbody_dp.startswith("FAILED"):\n'
               '                        _kstate_dp = "failed"\n'
               '                    else:\n'
               '                        continue\n'
               '                    _kwhat_dp = _kbody_dp.split(":", 1)[-1].split("—")[0].strip()\n'
               '                    if _kwhat_dp and not any(_kr_dp["what"] == _kwhat_dp[:48]\n'
               '                                             for _kr_dp in _kipp_dp):\n'
               '                        _kipp_dp.append({"what": _kwhat_dp[:48],\n'
               '                                         "state": _kstate_dp})\n'
               '                    if len(_kipp_dp) >= 5:\n'
               '                        break\n'
               '            except Exception:\n'
               '                pass\n'
               '            extras["kipp"] = _kipp_dp\n'),
    },
    "games": {
        "mark": "games",
        "title": "Steam Games",
        "empty": "no steam library found",
        "source": "your Steam library",
        "card": ('    <div class="card" style="flex:1"><h3>Steam Games</h3>'
                 '<div id="games" class="empty">no steam library found</div></div>\n'),
        "js": ('    const gEl = document.getElementById("games");\n'
               '    if(gEl){\n'
               '      const items = x.games || [];\n'
               '      if(items.length){ gEl.className=""; gEl.innerHTML = items.map(i =>\n'
               '        `<div class="rowitem"><span>${esc(i.name)}</span></div>`).join("")\n'
               '        + ((x.games_count||0) > items.length ?\n'
               '           `<div class="rowitem"><span class="when">+ ${x.games_count - items.length} more</span></div>` : "");\n'
               '      } else { gEl.className = "empty"; gEl.textContent = "no steam library found"; }\n'
               '    }\n'),
        "py": ('            try:\n'
               '                import re as _re_dp, winreg as _winreg_dp\n'
               '                with _winreg_dp.OpenKey(_winreg_dp.HKEY_CURRENT_USER,\n'
               '                                        r"Software\\Valve\\Steam") as _key_dp:\n'
               '                    _sroot_dp = Path(_winreg_dp.QueryValueEx(_key_dp, "SteamPath")[0])\n'
               '            except Exception:\n'
               '                _sroot_dp = None\n'
               '            _sgames_dp = []\n'
               '            try:\n'
               '                if _sroot_dp:\n'
               '                    _slibs_dp = [_sroot_dp / "steamapps"]\n'
               '                    _svdf_dp = _sroot_dp / "steamapps" / "libraryfolders.vdf"\n'
               '                    if _svdf_dp.exists():\n'
               '                        for _sm_dp in _re_dp.finditer(r\'"path"\\s+"([^"]+)"\',\n'
               '                                                      _svdf_dp.read_text(encoding="utf-8", errors="ignore")):\n'
               '                            _sp_dp = Path(_sm_dp.group(1).replace("\\\\\\\\", "\\\\")) / "steamapps"\n'
               '                            if _sp_dp.exists() and _sp_dp not in _slibs_dp:\n'
               '                                _slibs_dp.append(_sp_dp)\n'
               '                    for _slib_dp in _slibs_dp:\n'
               '                        for _acf_dp in _slib_dp.glob("appmanifest_*.acf"):\n'
               '                            _stext_dp = _acf_dp.read_text(encoding="utf-8", errors="ignore")\n'
               '                            _sname_dp = _re_dp.search(r\'"name"\\s+"([^"]+)"\', _stext_dp)\n'
               '                            if not _sname_dp:\n'
               '                                continue\n'
               '                            _snm_dp = _sname_dp.group(1)\n'
               '                            if any(w in _snm_dp.lower() for w in\n'
               '                                   ("redistributable", "steamworks", "runtime", "proton")):\n'
               '                                continue\n'
               '                            _sgames_dp.append({"name": _snm_dp, "touched": _acf_dp.stat().st_mtime})\n'
               '                    _sgames_dp.sort(key=lambda g: -g["touched"])\n'
               '            except Exception:\n'
               '                _sgames_dp = []\n'
               '            extras["games"] = [{"name": g["name"]} for g in _sgames_dp[:10]]\n'
               '            extras["games_count"] = len(_sgames_dp)\n'),
    },
}


def _markers(mark: str, style: str):
    if style == "html":
        return f"<!-- BEGIN dashboard_panel:{mark} -->", f"<!-- END dashboard_panel:{mark} -->"
    if style == "js":
        return f"/* BEGIN dashboard_panel:{mark} */", f"/* END dashboard_panel:{mark} */"
    return f"# BEGIN dashboard_panel:{mark}", f"# END dashboard_panel:{mark}"


def _strip_block(text: str, begin: str, end: str) -> str:
    # eat any indentation sitting directly in front of the begin marker too
    # (added along with it), so removal leaves the surrounding lines exactly
    # as they were before the block was ever inserted
    pattern = r"[ \t]*" + re.escape(begin) + r".*?" + re.escape(end) + r"\n?"
    return re.sub(pattern, "", text, count=1, flags=re.S)


def _find_card_block(html: str, label: str):
    """Return (start, end) char offsets of the whole <div class="card">...
    </div> block whose <h3> reads `label`, however many lines it spans."""
    h3 = f"<h3>{label}</h3>"
    h3_pos = html.find(h3)
    if h3_pos == -1:
        return None
    start = html.rfind('<div class="card"', 0, h3_pos)
    if start == -1:
        return None
    pos = start
    depth = 0
    for m in re.finditer(r"<div\b|</div>", html[start:]):
        if m.group() == "</div>":
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            pos = start + m.end()
            break
    return start, pos


def _parse(request: str):
    action = "remove" if any(w in request for w in ("remove", "delete", "take off", "get rid")) else "add"
    # "asses" catches both "assessment" and common typos like "assesment"
    # the panel being ADDED is whichever is named FIRST — "add a kipp panel
    # underneath assessments" names two, and the second one is the anchor
    hits = []
    for name, words in (("kipp", ("kipp", "upgrade", "self-improve")),
                        ("assessments", ("asses", "assignment", "test")),
                        ("games", ("game", "steam"))):
        spot = min((request.find(w) for w in words if w in request),
                   default=-1)
        if spot >= 0:
            hits.append((spot, name))
    panel = min(hits)[1] if hits else None
    anchor, position = "shopping", "after"
    for key, label in CARD_LABELS.items():
        if key in request:
            anchor = key
            break
    if any(w in request for w in ("above", "before", "over ")):
        position = "before"
    return action, panel, anchor, position


def run(args: dict) -> str:
    request = str(args.get("request", "")).strip().lower()
    if not request:
        return "Tell me which panel and where, e.g. 'add an assessment panel underneath shopping'."
    if not INDEX_HTML.exists() or not DASHBOARD_PY.exists():
        return "I can't find the dashboard files, so I couldn't change the panel."

    action, panel_key, anchor_key, position = _parse(request)
    if not panel_key:
        return ("I only know how to build an Assessments or Steam Games panel "
                "right now — try 'add a games panel above shopping'.")

    panel = PANELS[panel_key]
    html = INDEX_HTML.read_text(encoding="utf-8")
    py = DASHBOARD_PY.read_text(encoding="utf-8")

    card_b, card_e = _markers(panel["mark"], "html")
    js_b, js_e = _markers(panel["mark"], "js")
    py_b, py_e = _markers(panel["mark"], "py")

    has_card = card_b in html
    has_js = js_b in html
    has_py = py_b in py

    if action == "remove":
        if not (has_card or has_js or has_py):
            return f"There's no {panel['title'].lower()} panel on the dashboard to remove."
        html = _strip_block(html, card_b, card_e)
        html = _strip_block(html, js_b, js_e)
        py = _strip_block(py, py_b, py_e)
        INDEX_HTML.write_text(html, encoding="utf-8")
        DASHBOARD_PY.write_text(py, encoding="utf-8")
        return f"Removed the {panel['title']} panel from the dashboard. Refresh the page to see it gone."

    # action == "add"
    if has_card and has_js and has_py:
        return f"The {panel['title']} panel is already on the dashboard."

    if not has_card:
        label = CARD_LABELS.get(anchor_key, "Shopping")
        block = _find_card_block(html, label)
        if not block:
            # fall back to right after the Shopping card, which always exists
            block = _find_card_block(html, "Shopping")
        if not block:
            return "I couldn't find where to put it on the dashboard layout."
        start, end = block
        card_html = f"{card_b}\n{panel['card']}    {card_e}\n"
        if position == "before":
            html = html[:start] + card_html + html[start:]
        else:
            html = html[:end] + "\n" + card_html.rstrip("\n") + html[end:]

    if not has_js:
        anchor_js = 'const k = document.getElementById("kipp");'
        if anchor_js not in html:
            return "Couldn't find the dashboard's script to wire the panel up."
        js_block = f"{js_b}\n{panel['js']}    {js_e}\n    "
        html = html.replace(anchor_js, js_block + anchor_js, 1)

    if not has_py:
        anchor_py = 'extras = {"lists": {}, "kipp": [], "learning": []}\n'
        if anchor_py not in py:
            return "Couldn't find the dashboard's data route to wire the panel up."
        py_block = f"            {py_b}\n{panel['py']}            {py_e}\n"
        py = py.replace(anchor_py, anchor_py + py_block, 1)

    INDEX_HTML.write_text(html, encoding="utf-8")
    DASHBOARD_PY.write_text(py, encoding="utf-8")
    where = f"{position} the {CARD_LABELS.get(anchor_key, 'Shopping')} panel"
    return (f"Added the {panel['title']} panel to the dashboard, {where}. It pulls straight "
            f"from {panel['source']}. Refresh the dashboard page to see it.")
