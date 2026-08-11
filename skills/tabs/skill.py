"""Browser tab control by voice: switch to / close tabs by name, or list
them — through the browser's tab strip in the accessibility tree."""
import importlib.util
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]

DESCRIPTION = ("Browser TABS — 'switch to the YouTube tab', 'go to the "
               "gmail tab', 'close this tab', 'close the shopping tab', "
               "'open a new tab', 'what tabs are open'. Works on the "
               "browser's actual tab strip. NOT for closing whole windows "
               "(close_window) and NOT for opening apps (open_app).")
ARGS = {"action": "'switch', 'close', 'new', or 'list'",
        "tab": "part of the tab's name, or 'this' for the current tab"}

# words that name no tab at all — they arrive when a command was misrouted
# ("open them in my browser" once became a tab search for nothing)
VAGUE = {"", "them", "those", "these", "it", "that", "they", "one", "a", "new",
         "tab", "tabs", "some"}


def _cs():
    spec = importlib.util.spec_from_file_location(
        "cs", BASE / "skills" / "click_screen" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tabs():
    import uiautomation as auto

    cs = _cs()
    win = cs._target_window(auto)
    if not (win.ClassName or "").startswith("Chrome_WidgetWin"):
        return win, []
    found, state = [], {"count": 0}

    def walk(c, depth=0):
        if depth > 12 or state["count"] > 600:
            return
        for child in c.GetChildren():
            state["count"] += 1
            try:
                if child.ControlTypeName == "TabItemControl" and child.Name:
                    r = child.BoundingRectangle
                    if r.width() > 2 and not child.IsOffscreen:
                        found.append((child.Name, (r.xcenter(), r.ycenter())))
            except Exception:
                pass
            walk(child, depth + 1)

    walk(win)
    return win, found


def run(args: dict) -> str:
    import pyautogui

    action = str(args.get("action", "list")).strip().lower()
    want = str(args.get("tab", "")).strip().lower()

    if action in ("new", "open"):
        import webbrowser

        webbrowser.open_new_tab("about:blank")
        return "New tab open."

    win, tabs = _tabs()
    if action == "close" and want in ("", "this", "current", "active"):
        pyautogui.hotkey("ctrl", "w")
        return "Closed this tab."
    # a vague name means the command was misrouted here — say so instead of
    # answering "No open tab looks like ."
    if action in ("switch", "go", "close") and want in VAGUE:
        return ("Which tab? Give me a word from its name — or ask what tabs "
                "are open.")
    if not tabs:
        return "I can't see a browser tab strip on the window in front."
    if action == "list":
        names = [t[0].split("-")[0].strip()[:40] for t in tabs][:8]
        return f"{len(tabs)} tabs open: " + "; ".join(names) + "."

    words = [w for w in want.replace("tab", "").split() if len(w) > 2]
    match = next((t for t in tabs
                  if all(w in t[0].lower() for w in words)), None) if words \
        else None
    if match is None and words:
        match = next((t for t in tabs
                      if any(w in t[0].lower() for w in words)), None)
    if match is None:
        return f"No open tab looks like {want}."
    name, (x, y) = match
    if action == "close":
        pyautogui.middleClick(x, y)  # middle-click closes a Chromium tab
        return f"Closed the {name.split('-')[0].strip()[:40]} tab."
    pyautogui.click(x, y)
    return f"Switched to {name.split('-')[0].strip()[:40]}."
