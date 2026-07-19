import pygetwindow

DESCRIPTION = ("Close a single window by its title — folder windows, browser windows, etc. "
               "E.g. 'close the pictures window'. (Use close_app to quit a whole program.)")
ARGS = {"title": "part of the window title to close"}

PROTECTED = ("tars", "cmd", "command prompt")


OWN_WINDOW_MSG = ("That one's my own window — say 'goodbye TARS' if you want me to shut down.")


def run(args: dict) -> str:
    title = (args.get("title") or "").strip().lower()
    if not title:
        return "Close which window?"

    if title in ("this", "active", "current", "it", "that"):
        win = pygetwindow.getActiveWindow()
        if win is None or not win.title:
            return "Nothing seems to be in front right now."
        if any(p in win.title.lower() for p in PROTECTED):
            return OWN_WINDOW_MSG
        wt = win.title
        win.close()
        return f"Closed the {wt.split(' - ')[0]} window."

    cleaned = (title.replace("the ", "").replace(" window", "").replace(" folder", "")
               .removeprefix("window ").removeprefix("windows ").strip())
    if cleaned in ("terminal", "console", "cmd", "command prompt", "tars"):
        return OWN_WINDOW_MSG

    for win in pygetwindow.getAllWindows():
        wt = (win.title or "").strip()
        if not wt or any(p in wt.lower() for p in PROTECTED):
            continue
        if cleaned in wt.lower():
            win.close()
            return f"Closed the {wt.split(' - ')[0]} window."
    return f"I can't see a window called {cleaned}."
