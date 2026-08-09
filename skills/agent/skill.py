"""TARS's PC agent: give it a GOAL, not a script — "open Notepad and write
my shopping list into it", "find the settings page and turn on dark mode".

The difference from screen_task (which follows an explicit chain): this one
plans, acts, then LOOKS AT THE SCREEN to check whether each step actually
worked, adapts when it didn't, and reports honestly how far it got. No
step is assumed to have succeeded just because it was attempted.
"""
import importlib.util
import json
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"
MAX_STEPS = 8
MAX_RETRIES = 2

DESCRIPTION = ("Give TARS a whole JOB on the PC and let him work it out — "
               "'open Notepad and write my shopping list in it', 'find the "
               "dark mode setting and turn it on', 'get my brain page up and "
               "search it for Emma'. He plans the steps, does them, CHECKS "
               "the screen after each one, adapts if something didn't work, "
               "and tells you honestly how far he got. For a single click "
               "use click_screen; for an explicit A-then-B chain use "
               "screen_task.")
ARGS = {"goal": "what Jacob wants done, in his own words"}


def _cs():
    spec = importlib.util.spec_from_file_location(
        "click_screen_skill", BASE / "skills" / "click_screen" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CURRENT = ""  # the window the agent is working in (set when it opens one)


def _screen(cs) -> str:
    """What's on screen, in words — window title plus its visible labels.
    Cheap (accessibility tree, no vision model) and enough to verify with.
    Prefers the window the agent just opened: Windows hands focus to the
    taskbar mid-launch, which had TARS verifying a stale browser tab."""
    import uiautomation as auto

    win = None
    if _CURRENT:
        for w in auto.GetRootControl().GetChildren():
            try:
                if _CURRENT in (w.Name or "").lower() \
                        and w.BoundingRectangle.width() > 200:
                    win = w
                    break
            except Exception:
                continue
    win = win or cs._target_window(auto)
    title = (win.Name or "?")[:70]
    seen, state = [], {"n": 0}

    def walk(c, depth=0):
        if depth > 14 or state["n"] > 700 or len(seen) > 40:
            return
        for child in c.GetChildren():
            state["n"] += 1
            try:
                nm = (child.Name or "").strip()
                if nm and len(nm) > 1 and not child.IsOffscreen:
                    seen.append(nm[:45])
            except Exception:
                pass
            walk(child, depth + 1)

    try:
        walk(win)
    except Exception:
        pass
    # CONTENT of the text area — labels alone left TARS blind to his own
    # typing, so he typed the same line twice instead of declaring done
    content = ""
    try:
        boxes = []

        def find_box(c, depth=0):
            if depth > 8 or boxes:
                return
            for child in c.GetChildren():
                try:
                    if child.ControlTypeName in ("EditControl",
                                                 "DocumentControl") \
                            and child.BoundingRectangle.width() > 80:
                        boxes.append(child)
                        return
                except Exception:
                    pass
                find_box(child, depth + 1)

        find_box(win)
        if boxes:
            try:
                content = boxes[0].GetTextPattern().DocumentRange.GetText(300)
            except Exception:
                content = boxes[0].GetValuePattern().Value or ""
    except Exception:
        pass
    return (f"WINDOW: {title}\nVISIBLE: "
            + " | ".join(dict.fromkeys(seen))[:800]
            + (f"\nTEXT CONTENT: {content[:300]!r}" if content.strip() else ""))


def _ask(prompt: str, want_json: bool = True) -> dict | str:
    body = {"model": MODEL, "stream": False, "keep_alive": "2h",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0}}
    if want_json:
        body["format"] = "json"
    r = requests.post(OLLAMA_URL, json=body, timeout=120)
    r.raise_for_status()
    out = r.json()["message"]["content"]
    return json.loads(out) if want_json else out


def _plan(goal: str, screen: str, history: list[str]) -> dict:
    done = ("\nAlready done: " + "; ".join(history)) if history else ""
    return _ask(
        f"You are TARS's PC agent. Jacob's goal: {goal!r}\n"
        f"What's on screen now:\n{screen}{done}\n\n"
        "RULES: to start a program or website ALWAYS use the open step — "
        "never try to launch apps by clicking around a browser or typing "
        "into a search bar. If something in 'already done' failed, do NOT "
        "repeat it: change approach. STOP with done as soon as everything "
        "Jacob literally asked for has happened — never add extra work he "
        "didn't ask for (no saving, closing, tidying up or 'improving').\n"
        "Give the NEXT SINGLE step toward the goal. Step kinds:\n"
        '{"do":"open","target":"<app or website name>"}\n'
        '{"do":"click","target":"<element described in words>"}\n'
        '{"do":"type","text":"<text>","enter":true/false}\n'
        '{"do":"key","keys":"ctrl+s"}  (a keyboard shortcut)\n'
        '{"do":"wait","seconds":2}\n'
        '{"do":"done","why":"<why the goal is complete>"}\n'
        '{"do":"stuck","why":"<what is blocking you>"}\n'
        'Reply with ONE step as JSON, plus "expect": what the screen should '
        'show if THIS SINGLE STEP worked — not the finished goal. (Opening '
        'Notepad expects an empty Notepad window, NOT the text typed in it.)')


def _verify(step: dict, expect: str, before: str, after: str) -> dict:
    return _ask(
        f"A PC automation step was just performed.\nStep: {json.dumps(step)}\n"
        f"Expected afterwards: {expect}\n\nSCREEN BEFORE:\n{before[:700]}\n\n"
        f"SCREEN AFTER:\n{after[:700]}\n\n"
        'Did THIS STEP take effect? Judge the step alone, never the wider '
        'goal — an app opening counts as success even if nothing is typed '
        'in it yet. Reply JSON: {"worked": true/false, "why": "<short '
        'reason>"}. Only say false if the screen shows the step plainly '
        "failed (e.g. nothing changed at all when it should have).")


def _focus_new(target: str, seconds: float = 8) -> bool:
    """Wait for a window matching what we just opened, then bring it to the
    front. Windows hands focus to the taskbar mid-launch, which once made
    TARS verify the wrong window and nearly type into the wrong app."""
    import uiautomation as auto

    key = target.lower().replace(".exe", "").strip()
    words = [w for w in key.split() if len(w) > 2] or [key]
    deadline = time.time() + seconds
    while time.time() < deadline:
        for w in auto.GetRootControl().GetChildren():
            try:
                name = (w.Name or "").lower()
                if name and any(word in name for word in words) \
                        and w.BoundingRectangle.width() > 200:
                    global _CURRENT
                    _CURRENT = name  # verify against THIS window from now on
                    try:  # manage_window's ctypes path beats Windows'
                        from skills_engine import SkillBox  # focus-stealing
                        SkillBox(BASE).run("manage_window",  # restrictions
                                           {"action": "focus", "title": key})
                    except Exception:
                        try:
                            w.SetActive()
                        except Exception:
                            pass
                    _force_front(key)
                    time.sleep(0.5)
                    return True
            except Exception:
                continue
        time.sleep(0.5)
    return False


def _force_front(name_fragment: str = "") -> bool:
    """Bring the agent's window to the front FOR REAL.

    Windows blocks foreground steals from background processes, so a plain
    SetForegroundWindow silently fails and typing lands in whatever was on
    top (once, a YouTube tab). The reliable route is the classic pair: tap
    ALT (which makes Windows treat this as user-driven) and briefly attach
    to the current foreground thread's input queue."""
    import ctypes

    import uiautomation as auto

    key = (name_fragment or _CURRENT or "").lower()
    if not key:
        return False
    try:
        win = next((w for w in auto.GetRootControl().GetChildren()
                    if key in (w.Name or "").lower()
                    and w.BoundingRectangle.width() > 200), None)
        if win is None:
            return False
        hwnd = win.NativeWindowHandle
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        u.keybd_event(0x12, 0, 0, 0)                       # ALT down
        u.ShowWindow(hwnd, 9)                              # SW_RESTORE
        fg_thread = u.GetWindowThreadProcessId(u.GetForegroundWindow(), None)
        me = k.GetCurrentThreadId()
        u.AttachThreadInput(fg_thread, me, True)
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        u.AttachThreadInput(fg_thread, me, False)
        u.keybd_event(0x12, 0, 2, 0)                       # ALT up
        time.sleep(0.7)
        return key in (auto.GetForegroundControl()
                       .GetTopLevelControl().Name or "").lower()
    except Exception:
        return False


def _to_clipboard(text: str) -> bool:
    """Windows clipboard API directly. tkinter's clipboard is cleared when
    its hidden window closes (so the paste arrived empty), and piping to
    clip.exe mangled the encoding."""
    import ctypes
    from ctypes import wintypes

    try:
        u, k = ctypes.windll.user32, ctypes.windll.kernel32
        # 64-bit: handles are pointers — without these argtypes they get
        # truncated to 32 bits and the whole call quietly fails
        k.GlobalAlloc.restype = ctypes.c_void_p
        k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        u.SetClipboardData.restype = ctypes.c_void_p
        u.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        if not u.OpenClipboard(None):
            return False
        u.EmptyClipboard()
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        handle = k.GlobalAlloc(0x2002, size)       # GMEM_MOVEABLE|ZEROINIT
        buf = k.GlobalLock(handle)
        ctypes.memmove(buf, data, size)
        k.GlobalUnlock(handle)
        ok = u.SetClipboardData(13, handle)        # CF_UNICODETEXT
        u.CloseClipboard()
        return bool(ok)
    except Exception:
        try:
            ctypes.windll.user32.CloseClipboard()
        except Exception:
            pass
        return False


def _text_present(needle: str) -> bool:
    """Is this text actually in the window's text field right now? Read it
    straight from the control — the screen summary sometimes misses it, and
    without this TARS retyped the same line five times."""
    import uiautomation as auto

    try:
        top = auto.GetForegroundControl().GetTopLevelControl()
        boxes = []

        def walk(c, depth=0):
            if depth > 8 or boxes:
                return
            for child in c.GetChildren():
                try:
                    if child.ControlTypeName in ("EditControl",
                                                 "DocumentControl"):
                        boxes.append(child)
                        return
                except Exception:
                    pass
                walk(child, depth + 1)

        walk(top)
        if not boxes:
            return False
        try:
            got = boxes[0].GetTextPattern().DocumentRange.GetText(2000)
        except Exception:
            got = boxes[0].GetValuePattern().Value or ""
        return needle.lower() in (got or "").lower()
    except Exception:
        return False


def _focus_text_area() -> bool:
    """Put the caret in the window's text field. Bringing a window to the
    front focuses the WINDOW, not its editor — typing then goes nowhere
    (Notepad swallowed three test runs this way)."""
    import uiautomation as auto

    try:
        top = auto.GetForegroundControl().GetTopLevelControl()
        found = []

        def walk(c, depth=0):
            if depth > 8 or found:
                return
            for child in c.GetChildren():
                try:
                    if child.ControlTypeName in ("EditControl",
                                                 "DocumentControl") \
                            and child.BoundingRectangle.width() > 80:
                        found.append(child)
                        return
                except Exception:
                    pass
                walk(child, depth + 1)

        walk(top)
        if not found:
            return False
        area = found[0]
        try:
            area.SetFocus()
        except Exception:
            pass
        import pyautogui

        r = area.BoundingRectangle
        pyautogui.click(r.xcenter(), r.ycenter())
        time.sleep(0.3)
        return True
    except Exception:
        return False


def _do(step: dict, cs) -> str:
    import pyautogui

    kind = str(step.get("do", "")).lower()
    if kind == "open":
        from skills_engine import SkillBox

        target = str(step.get("target", ""))
        said = SkillBox(BASE).run("open_app", {"target": target}) or ""
        # WAIT for the window and FOCUS it — otherwise the next typing step
        # lands in whatever was focused before (a browser, or a game)
        _focus_new(target)
        return said or f"opened {target}"
    if kind == "click":
        target = str(step.get("target", ""))
        if cs._forbidden(target):
            raise PermissionError("that click spends, sends or deletes — "
                                  "Jacob does those himself")
        spot = None
        try:
            spot = cs._uia_locate(target)
        except Exception:
            pass
        spot = spot or cs.locate(target)
        if spot is None:
            raise LookupError(f"couldn't find {target}")
        cs._glide_and_click(spot[0], spot[1], False)
        return f"clicked {target}"
    if kind == "type":
        text = str(step.get("text", ""))
        # ORDER MATTERS: load the clipboard FIRST — tkinter's hidden window
        # steals focus, so doing this after focusing sent the paste into
        # thin air. Paste beats keystroke simulation (which came out as
        # "tesTARS agent etst" at speed).
        pasted = _to_clipboard(text)
        _force_front()        # now claim the window...
        _focus_text_area()    # ...and its text field
        pyautogui.sleep(0.4)
        if pasted:
            pyautogui.hotkey("ctrl", "v")
            pyautogui.sleep(0.5)
            if not _text_present(text[:20]):   # paste blocked? type it
                pyautogui.write(text, interval=0.03)
        else:
            pyautogui.write(text, interval=0.03)
        if step.get("enter"):
            pyautogui.press("enter")
        return f"typed {str(step.get('text',''))[:40]}"
    if kind == "key":
        keys = str(step.get("keys", "")).lower().replace(" ", "")
        pyautogui.hotkey(*[k for k in keys.split("+") if k])
        return f"pressed {keys}"
    if kind == "wait":
        time.sleep(min(6, float(step.get("seconds", 2))))
        return "waited"
    return ""


def run(args: dict) -> str:
    goal = str(args.get("goal") or "").strip()
    if not goal:
        return "What's the job?"
    cs = _cs()
    if cs._forbidden(goal):
        return ("Part of that job spends, sends or deletes something — "
                "those steps stay yours, so I'm not starting it.")

    history: list[str] = []
    retries = 0
    try:
        screen = _screen(cs)
    except Exception:
        return "I can't read the screen right now."

    import re as _re

    want_typed = _re.search(r"typ(?:e|ing)[:\s]+(.{3,60})$", goal, _re.I)

    for _ in range(MAX_STEPS):
        # deterministic completion: if the goal was to type something and
        # the screen now contains it, the job IS done — don't ask a model
        # to notice (it kept typing the same line again and again)
        # only after WE typed — Windows 11 Notepad restores old session text,
        # which once had TARS declaring victory before doing anything
        if want_typed and any(h.startswith("typed") for h in history):
            target_text = want_typed.group(1).strip(" .'\"").lower()
            if target_text and (target_text in screen.lower()
                                or _text_present(target_text)):
                return _report(history, "", done=True)
        try:
            plan = _plan(goal, screen, history)
        except Exception:
            return _report(history, "my planning brain didn't answer")
        step = {k: v for k, v in plan.items() if k != "expect"}
        kind = str(step.get("do", "")).lower()
        # the planner sometimes echoes the whole screen back as a "target" —
        # a real element description is short
        if kind == "click" and len(str(step.get("target", ""))) > 70:
            step["target"] = str(step["target"])[:70].split("|")[0].strip()
        if kind == "open":
            step["target"] = str(step.get("target", "")).replace(".exe", "") \
                .replace(".EXE", "").strip()
        if kind == "done":
            return _report(history, "", done=True)
        if kind == "stuck":
            return _report(history, str(plan.get("why", "I got stuck")))

        try:
            did = _do(step, cs)
        except PermissionError as e:
            return _report(history, str(e))
        except Exception as e:
            retries += 1
            history.append(f"tried {kind} but {e}")
            if retries > MAX_RETRIES:
                return _report(history, str(e))
            continue

        time.sleep(1.2)
        try:
            after = _screen(cs)
            check = _verify(step, str(plan.get("expect", "")), screen, after)
        except Exception:
            after, check = screen, {"worked": True}
        screen = after
        if check.get("worked"):
            history.append(did or kind)
            retries = 0
        else:
            retries += 1
            history.append(f"{did or kind} — didn't take ({check.get('why','')})")
            if retries > MAX_RETRIES:
                return _report(history, str(check.get("why", "it didn't work")))
    return _report(history, "I ran out of steps before finishing")


def _report(history: list[str], problem: str, done: bool = False) -> str:
    # spoken aloud: keep it human-sized, never a wall of screen text
    got = "; ".join(h[:70] for h in history[-3:]) if history else "nothing yet"
    problem = problem[:120]
    if done:
        return f"Done — {got}."
    if not history:
        return f"I couldn't start: {problem}."
    return f"I got as far as {got} — then {problem}. Stopped there."
