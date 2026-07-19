"""Move, maximize, minimize, or focus windows — including across monitors."""
import mss
import pygetwindow

DESCRIPTION = ("Manage windows: move one to the main/left/right screen, maximize, "
               "minimize, bring to front, or clear the desktop. 'it'/'this' means "
               "the window in front.")
ARGS = {"action": "move, maximize, minimize, focus, or minimize_all",
        "monitor": "main, left, or right — only for move",
        "title": "part of the window title, or 'active' for the one in front"}

ACTIVE_WORDS = ("", "active", "this", "it", "current", "that")


def _target(title: str):
    title = (title or "").strip().lower()
    if title in ACTIVE_WORDS:
        return pygetwindow.getActiveWindow()
    cleaned = (title.replace("the ", "").replace(" window", "").replace(" folder", "")
               .removeprefix("window ").removeprefix("windows ").strip())
    for win in pygetwindow.getAllWindows():
        if win.title and cleaned in win.title.lower():
            return win
    return None


def _monitors() -> list[dict]:
    with mss.mss() as grabber:
        return grabber.monitors[1:]  # [0] is the combined virtual screen


def _bring_front(win) -> None:
    """pygetwindow's activate() raises 'error 0 - completed successfully'
    when Windows won't grant focus politely; go through the Win32 API."""
    try:
        win.activate()
    except Exception:
        import ctypes

        ctypes.windll.user32.ShowWindow(win._hWnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(win._hWnd)


def run(args: dict) -> str:
    action = (args.get("action") or "").strip().lower()

    if action == "minimize_all":
        import pyautogui

        pyautogui.hotkey("win", "d")
        return "Desktop cleared."

    win = _target(args.get("title", ""))
    if win is None or not win.title:
        return "I can't find that window."
    name = win.title.split(" - ")[0]

    if action == "maximize":
        win.maximize()
        return f"Maximized {name}."
    if action == "minimize":
        win.minimize()
        return f"Minimized {name}."
    if action == "focus":
        _bring_front(win)
        return f"{name} is up front."
    if action == "move":
        where = (args.get("monitor") or "main").strip().lower()
        mons = _monitors()
        if len(mons) == 1:
            mon = mons[0]
        elif "left" in where:
            mon = min(mons, key=lambda m: m["left"])
        elif "right" in where:
            mon = max(mons, key=lambda m: m["left"])
        else:  # main = primary, whose corner is the origin
            mon = next((m for m in mons if m["left"] == 0 and m["top"] == 0), mons[0])
        try:
            win.restore()
        except Exception:
            pass
        win.moveTo(mon["left"] + 60, mon["top"] + 60)
        win.maximize()
        return f"{name} moved to the {where} screen."
    return f"I don't know the window action {action}."
