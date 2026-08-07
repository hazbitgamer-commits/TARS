"""TARS's hands: click things on screen by describing them, visibly.

v2 polish (Jacob: "I want to see how it does things"):
  - TWO-STAGE look: rough find on the downscaled full screen, then a zoomed
    full-resolution second look at that spot for a precise click — fixes the
    old blind spot with small targets like taskbar icons.
  - VISIBLE glide: the cursor travels smoothly to the target and circles it
    once before clicking, so Jacob can confirm it picked the right element
    (e.g. the actual search bar, not a lookalike) — and knock the mouse to
    abort (pyautogui's corner failsafe also kills it instantly).
  - CLICK-AND-TYPE: 'search for dog videos' = click the box, type, enter —
    one command.
  - HARD GATE: refuses to click anything that spends money, sends a
    message, or deletes — those clicks stay Jacob's (spec §8).
"""
import base64
import io
import json
from pathlib import Path

import pyautogui
import requests
from mss import mss
from PIL import Image

DESCRIPTION = ("CLICK things on screen with the visible mouse, described in "
               "words: 'click the first video', 'press play', 'click the "
               "search bar'. Can also TYPE after clicking: 'click the search "
               "bar and search for funny dogs' (target + type + enter). "
               "Jacob watches the cursor glide there before it clicks. "
               "NOT for opening apps by name (open_app is faster) and NOT "
               "for continuous dictation (that's dictation).")
ARGS = {"target": "what to click, described in words",
        "type": "optional text to type right after the click",
        "enter": "'true' to press Enter after typing (searches, forms)",
        "monitor": "'left' for the left screen, otherwise the main one",
        "double": "'true' for a double-click"}

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
VISION_MODEL = "qwen2.5vl:7b"
VIEW_WIDTH = 1280   # pass-1 downscale; pass 2 looks at full-res crop
ZOOM = 440          # px square around the rough hit for the precise look

# clicks that spend real money, send, or destroy stay Jacob's — no
# exceptions anywhere. FUT COIN actions (bid/buy now/list) are allowed
# ONLY while the FC web app is the window in front (Jacob's 2026-07-22
# call — in-game coins, his account, his command). Real-money terms
# (purchase/pay/checkout) stay blocked even there: FUT Points cost cash.
FORBIDDEN = ("purchase", "pay", "checkout", "subscribe",
             "send", "post", "publish", "delete", "uninstall", "format",
             "confirm payment", "place order")
MARKET_TERMS = ("buy", "bid", "make offer", "buy now", "order",
                "list on transfer market", "list item")
FUT_WINDOW = ("ultimate team", "ea sports fc", "web app", "fut")


def _forbidden(text: str) -> bool:
    import re as _re

    low = text.lower()
    terms = FORBIDDEN
    in_fut = False
    try:
        import uiautomation as auto

        fg = (auto.GetForegroundControl().GetTopLevelControl().Name or "").lower()
        in_fut = any(k in fg for k in FUT_WINDOW)
    except Exception:
        pass
    if not in_fut:
        terms = terms + MARKET_TERMS
    return any(_re.search(rf"\b{_re.escape(w)}\b", low) for w in terms)


def _ask_eyes(png: bytes, target: str, width: int, height: int):
    r = requests.post(OLLAMA_URL, json={
        "model": VISION_MODEL, "stream": False, "format": "json",
        "keep_alive": "30m",
        "messages": [{
            "role": "user",
            "content": (f"This image is {width}x{height} pixels. Find: "
                        f"{target!r}. It may appear as an ICON standing in "
                        "for it (a magnifying glass for search, a gear for "
                        "settings, three dots for a menu). Reply JSON: "
                        '{"found": true/false, "x": <int>, "y": <int>} — '
                        "x,y = CENTER of that element in THIS image's pixels. "
                        "found=false if nothing like it is visible."),
            "images": [base64.b64encode(png).decode()],
        }],
        "options": {"num_predict": 80, "num_ctx": 8192}}, timeout=180)
    r.raise_for_status()
    data = json.loads(r.json()["message"]["content"])
    if not data.get("found"):
        return None
    return int(data["x"]), int(data["y"])


# "the most relevant/interesting video thumbnail" describes an opinion, not
# a pixel — the eyes model has nothing to compare against and just reports
# not-found (Jacob heard "I can't see it" for exactly this phrasing). Result
# lists are already ordered by relevance, so treat that as "the first one".
SUBJECTIVE_PICKS = ("relevant", "interesting", "best", "top", "recommended")


def _normalize_target(target: str) -> str:
    low = target.lower()
    if ("video" in low or "thumbnail" in low) and any(w in low for w in SUBJECTIVE_PICKS):
        return "the first video thumbnail in the list of results"
    return target


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _grab(which: str):
    with mss() as grabber:
        monitors = grabber.monitors[1:]
        if "left" in which and len(monitors) > 1:
            mon = min(monitors, key=lambda m: m["left"])
        else:
            mon = next((m for m in monitors if m["left"] == 0 and m["top"] == 0),
                       monitors[0])
        shot = grabber.grab(mon)
    return Image.frombytes("RGB", shot.size, shot.rgb), mon


def locate(target: str, which: str = "main"):
    """Two-stage find → (screen_x, screen_y), or None."""
    full, mon = _grab(which)

    # pass 1: rough position on the downscaled whole screen
    scale = max(1.0, full.width / VIEW_WIDTH)
    small = full.resize((round(full.width / scale), round(full.height / scale)))
    rough = _ask_eyes(_png(small), target, small.width, small.height)
    if rough is None:
        return None
    fx, fy = round(rough[0] * scale), round(rough[1] * scale)

    # pass 2: zoom into a full-resolution crop around the rough hit and
    # ask again — small targets become huge and unmissable
    half = ZOOM // 2
    left = max(0, min(full.width - ZOOM, fx - half))
    top = max(0, min(full.height - ZOOM, fy - half))
    crop = full.crop((left, top, left + ZOOM, top + ZOOM))
    precise = _ask_eyes(_png(crop), target, crop.width, crop.height)
    if precise is not None:
        fx, fy = left + precise[0], top + precise[1]

    return mon["left"] + fx, mon["top"] + fy


STOPWORDS = {"the", "a", "an", "on", "in", "of", "to", "for", "at", "my",
             "that", "this", "icon", "element", "thing", "please",
             # app/brand names say WHERE, not WHAT — "the Brave search bar"
             # is just the search bar (elements never carry the app's name)
             "brave", "chrome", "edge", "firefox", "google", "windows",
             "youtube", "steam", "spotify", "browser", "page", "website"}
TYPE_WORDS = {"button": "ButtonControl", "link": "HyperlinkControl",
              "tab": "TabItemControl", "bar": "EditControl",
              "box": "EditControl", "field": "EditControl",
              "file": "ListItemControl", "folder": "ListItemControl",
              "menu": "MenuItemControl", "checkbox": "CheckBoxControl",
              "video": "HyperlinkControl"}
CLICKABLE = ("EditControl", "ButtonControl", "HyperlinkControl",
             "ListItemControl", "TabItemControl", "MenuItemControl",
             "ComboBoxControl", "CheckBoxControl", "RadioButtonControl",
             "TreeItemControl", "SplitButtonControl", "TextControl")


def _score_walk(win, match_words, type_hint):
    """Walk one window's accessibility tree scoring named clickables."""
    import difflib

    best, best_score = None, 0.0
    state = {"count": 0}
    try:
        wr = win.BoundingRectangle
        bounds = (wr.left, wr.top, wr.right, wr.bottom)
    except Exception:
        bounds = None

    def visible(child, r) -> bool:
        # scrolled-away page content stays in the tree with phantom
        # coordinates — clicking those misses the window entirely
        try:
            if child.IsOffscreen:
                return False
        except Exception:
            pass
        if bounds:
            return (bounds[0] <= r.xcenter() <= bounds[2]
                    and bounds[1] <= r.ycenter() <= bounds[3])
        return True

    def walk(c, depth=0):
        nonlocal best, best_score
        if depth > 24 or state["count"] > 2500:
            return
        for child in c.GetChildren():
            state["count"] += 1
            try:
                name = (child.Name or "").strip()
                ctype = child.ControlTypeName
                if name and ctype in CLICKABLE:
                    low = name.lower()
                    overlap = sum(w in low for w in match_words) / len(match_words)
                    fuzz = difflib.SequenceMatcher(
                        None, " ".join(match_words), low).ratio()
                    score = max(overlap, fuzz)
                    if type_hint and ctype == type_hint:
                        score += 0.15
                    elif ctype == "TextControl":
                        score -= 0.2  # prefer the real control over its label
                    if score > best_score:
                        r = child.BoundingRectangle
                        if r.width() > 2 and r.height() > 2 and visible(child, r):
                            best, best_score = (r.xcenter(), r.ycenter()), score
            except Exception:
                pass
            walk(child, depth + 1)

    walk(win)
    return best, best_score


# windows TARS must never click inside: his own console, his status pill,
# and Windows decoration surfaces. When one of these has focus, the click
# Jacob wants is in the app BEHIND them.
SELF_CLASSES = ("CASCADIA_HOSTING_WINDOW_CLAS", "ConsoleWindowClass",
                "TkTopLevel")
DECO_CLASSES = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Worker Window",
                "RainmeterMeterWindow", "Progman", "WorkerW")


def _is_self_or_deco(w) -> bool:
    cls = (w.ClassName or "")
    if any(cls.startswith(c) for c in SELF_CLASSES + DECO_CLASSES):
        return True
    return "rainmeter" in (w.Name or "").lower()


def _target_window(auto):
    """The window Jacob actually means: the foreground one — unless that's
    TARS's own console/pill (he often talks with it focused; typing into it
    once swallowed a whole search silently). Then: first real app window
    beneath it in z-order."""
    fg = auto.GetForegroundControl().GetTopLevelControl()
    if not _is_self_or_deco(fg):
        return fg
    for w in auto.GetRootControl().GetChildren():  # top of z-order first
        try:
            if _is_self_or_deco(w) or not (w.Name or "").strip():
                continue
            r = w.BoundingRectangle
            if r.width() > 300 and r.height() > 300:
                return w
        except Exception:
            continue
    return fg


def _uia_locate(target: str):
    """The FAST path (~1s): ask Windows' accessibility tree for the element
    instead of looking at pixels. Returns (x, y) or None — games and
    unnamed canvases return None and fall through to the vision eyes."""
    import re
    import time as _t

    import uiautomation as auto

    words = [w for w in re.findall(r"[a-z0-9']+", target.lower())
             if w not in STOPWORDS]
    type_hint = next((TYPE_WORDS[w] for w in words if w in TYPE_WORDS), None)
    match_words = [w for w in words if w not in TYPE_WORDS] or words
    if not match_words:
        return None

    win = _target_window(auto)
    best, score = _score_walk(win, match_words, type_hint)
    if score < 0.75 and (win.ClassName or "").startswith("Chrome_WidgetWin"):
        # Chromium browsers (Brave/Chrome/Edge) hide the PAGE's elements
        # until an accessibility client pokes the document — poke, give the
        # renderer a beat to publish the tree, then look again
        try:
            doc = win.DocumentControl(searchDepth=20)
            if doc.Exists(2, 0.2):
                doc.GetChildren()
                _t.sleep(0.8)
                best, score = _score_walk(win, match_words, type_hint)
        except Exception:
            pass
    return best if score >= 0.75 else None


def _highlight(x: int, y: int, radius: int = 14) -> None:
    """Trace a quick circle around the target before the click lands — a
    silent 'is this the one?' so Jacob can see exactly which element got
    picked (search bars especially look alike) instead of finding out only
    after the click, then having to repeat the whole command."""
    import math
    steps = 10
    for i in range(steps + 1):
        angle = 2 * math.pi * i / steps
        pyautogui.moveTo(x + radius * math.cos(angle),
                          y + radius * math.sin(angle), duration=0.02)
    pyautogui.moveTo(x, y, duration=0.03)


def _glide_and_click(x: int, y: int, double: bool) -> None:
    """Rapid: dart to the target, circle it once so Jacob can confirm it's
    the right spot, then click. Corner-slam failsafe still aborts everything."""
    pyautogui.moveTo(x, y, duration=0.12)
    _highlight(x, y)
    if double:
        pyautogui.doubleClick()
    else:
        pyautogui.click()


def run(args: dict) -> str:
    target = str(args.get("target") or "").strip()
    text = str(args.get("type") or "").strip()
    if not target:
        return "Click what, exactly?"
    target = _normalize_target(target)
    if _forbidden(f"{target} {text}"):
        return ("That click could spend, send, or delete something — "
                "those ones stay yours. You press it; I'll happily do "
                "everything up to it.")

    # fast path first: Windows' own element map, ~1 second, exact coords
    spot = None
    try:
        spot = _uia_locate(target)
    except Exception:
        pass
    used_eyes = spot is None
    if spot is None:  # games / unnamed pixels — fall back to the vision eyes
        try:
            spot = locate(target, str(args.get("monitor") or "main").lower())
        except requests.RequestException:
            return "My eyes aren't answering — is the vision model still loading?"
        except Exception:
            return f"I couldn't make sense of the screen looking for {target}."
    if spot is None:
        return f"I can't see {target} on that screen right now."

    _glide_and_click(spot[0], spot[1],
                     str(args.get("double", "")).lower() == "true")
    slow = " Had to eyeball that one." if used_eyes else ""
    if text:
        pyautogui.sleep(0.2)  # just enough for the field to take focus
        pyautogui.write(text, interval=0.01)
        if str(args.get("enter", "")).lower() == "true":
            pyautogui.press("enter")
            return f"Clicked {target}, typed it in, and hit enter.{slow}"
        return f"Clicked {target} and typed it in.{slow}"
    return f"Clicked {target}.{slow}"
