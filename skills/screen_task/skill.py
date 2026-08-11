"""Multi-step screen jobs: "click the search bar, type lofi music, find a
video 5 minutes or longer, click it." A small planner (local model) turns
the spoken chain into steps; each step runs on the click_screen machinery
(instant UIA finds, vision fallback); "find/choose" steps READ the page's
element names (titles, durations, channels ride along in the accessibility
tree) and pick the best match before clicking it. Honest partial reports:
if step 3 of 4 fails, the owner hears exactly how far it got."""
import importlib.util
import json
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
PLAN_MODEL = "qwen2.5:7b"

DESCRIPTION = ("Do a CHAIN of screen actions in one go: 'click the search "
               "bar, type lofi music, then find a video five minutes or "
               "longer and click it'. Handles click → type → find-and-pick "
               "sequences on whatever's on screen. Use for MULTI-step screen "
               "jobs; a single click or search is click_screen.")
ARGS = {"instruction": "the whole multi-step request in the owner's words"}


def _click_screen():
    spec = importlib.util.spec_from_file_location(
        "click_screen_skill", BASE / "skills" / "click_screen" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plan(instruction: str) -> list[dict]:
    r = requests.post(OLLAMA_URL, json={
        "model": PLAN_MODEL, "stream": False, "format": "json",
        "keep_alive": "2h",
        "messages": [{"role": "user", "content":
            "Turn this spoken screen-automation request into steps. "
            "Step kinds:\n"
            '  {"do": "click", "target": "<element described in words>"}\n'
            '  {"do": "type", "text": "<text>", "enter": true/false}\n'
            '  {"do": "choose", "criteria": "<what to pick from the page>"} '
            "— finds the best matching item on the page AND clicks it "
            "(use ONE choose step for 'find X and click it')\n"
            '  {"do": "wait", "seconds": <1-5>} — after searches/navigation\n'
            "Typing a SEARCH QUERY must have enter=true — nothing loads "
            "without it. Insert a wait step after any type-with-enter or "
            "click that loads a new page.\n"
            "Example — 'click the search bar, type cat videos, find one "
            "under 10 minutes and click it' becomes:\n"
            '{"steps": [{"do": "click", "target": "the search bar"}, '
            '{"do": "type", "text": "cat videos", "enter": true}, '
            '{"do": "wait", "seconds": 3}, '
            '{"do": "choose", "criteria": "a video under 10 minutes"}]}\n'
            f"Request: {instruction!r}\n"
            'Reply JSON: {"steps": [...]} (max 8 steps)'}],
        "options": {"temperature": 0}}, timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"]).get("steps", [])[:8]


def _candidates(cs) -> list[tuple[str, tuple[int, int]]]:
    """Visible, named, clickable page items (links/listitems) with coords —
    YouTube result names carry title + channel + duration, so criteria
    like 'longer than 5 minutes' are genuinely checkable."""
    import uiautomation as auto

    win = cs._target_window(auto)
    try:
        wr = win.BoundingRectangle
        bounds = (wr.left, wr.top, wr.right, wr.bottom)
    except Exception:
        bounds = None
    found, state = [], {"count": 0}

    def walk(c, depth=0):
        if depth > 24 or state["count"] > 2500 or len(found) >= 30:
            return
        for child in c.GetChildren():
            state["count"] += 1
            try:
                name = (child.Name or "").strip()
                if (name and len(name) >= 8 and child.ControlTypeName in
                        ("HyperlinkControl", "ListItemControl",
                         "ButtonControl")):
                    r = child.BoundingRectangle
                    inside = (not bounds or
                              (bounds[0] <= r.xcenter() <= bounds[2]
                               and bounds[1] <= r.ycenter() <= bounds[3]))
                    if r.width() > 2 and not child.IsOffscreen and inside:
                        found.append((name[:200], (r.xcenter(), r.ycenter())))
            except Exception:
                pass
            walk(child, depth + 1)

    walk(win)
    return found


def _choose(cs, criteria: str):
    items = _candidates(cs)
    if not items:
        return None, "the page shows nothing I can pick from"
    menu = "\n".join(f"{i}: {name}" for i, (name, _) in enumerate(items))
    r = requests.post(OLLAMA_URL, json={
        "model": PLAN_MODEL, "stream": False, "format": "json",
        "keep_alive": "2h",
        "messages": [{"role": "user", "content":
            f"Items visible on screen:\n{menu}\n\n"
            f"Pick the one best matching: {criteria!r}. Durations/views/"
            "channels appear in the item text — use them for constraints "
            "like 'longer than 5 minutes' (5:00+ or the words minutes/"
            "hour). Reply JSON: {\"index\": <int>} or {\"index\": -1} if "
            "nothing qualifies."}],
        "options": {"temperature": 0}}, timeout=120)
    r.raise_for_status()
    idx = int(json.loads(r.json()["message"]["content"]).get("index", -1))
    if not 0 <= idx < len(items):
        return None, f"nothing on screen matches {criteria}"
    return items[idx], None


def run(args: dict) -> str:
    instruction = str(args.get("instruction") or "").strip()
    if not instruction:
        return "Walk me through it — what's the chain of steps?"

    cs = _click_screen()
    if cs._forbidden(instruction):
        return ("Part of that chain would spend, send, or delete something "
                "— those clicks stay yours, so I'm not running it.")

    try:
        steps = _plan(instruction)
    except Exception:
        return "I couldn't work out the steps — say it again, simpler?"
    if not steps:
        return "That didn't break down into screen steps for me."

    import pyautogui

    done = []
    for n, step in enumerate(steps, 1):
        kind = str(step.get("do", "")).lower()
        try:
            if kind == "click":
                target = str(step.get("target", ""))
                spot = None
                try:
                    spot = cs._uia_locate(target)
                except Exception:
                    pass
                if spot is None:
                    spot = cs.locate(target)
                if spot is None:
                    return (f"I got through {', '.join(done) or 'nothing'} "
                            f"but couldn't find {target} — stopped there.")
                cs._glide_and_click(spot[0], spot[1], False)
                done.append(f"clicked {target}")
            elif kind == "type":
                pyautogui.sleep(0.3)
                pyautogui.write(str(step.get("text", "")), interval=0.01)
                if step.get("enter"):
                    pyautogui.press("enter")
                done.append(f"typed {step.get('text', '')}")
            elif kind == "wait":
                time.sleep(min(6, float(step.get("seconds", 2.5))))
            elif kind == "choose":
                criteria = str(step.get("criteria", ""))
                picked, why = _choose(cs, criteria)
                if picked is None:
                    return (f"I did {', '.join(done) or 'the first steps'}, "
                            f"but then {why}. Stopped there.")
                cs._glide_and_click(picked[1][0], picked[1][1], False)
                done.append(f"picked \"{picked[0][:60]}\"")
        except Exception as e:
            return (f"I got through {', '.join(done) or 'nothing'} but step "
                    f"{n} fell over: {e}")

    return "All done — " + ", then ".join(done) + "."
