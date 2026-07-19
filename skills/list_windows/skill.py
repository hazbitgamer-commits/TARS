import pygetwindow

DESCRIPTION = "List the windows currently open on screen. E.g. 'what windows are open'."
ARGS = {}


IGNORE = {"tk", "program manager", "windows input experience", "settings"}


def run(args: dict) -> str:
    titles = []
    for win in pygetwindow.getAllWindows():
        t = (win.title or "").strip()
        if not t or win.isMinimized or t.lower() in IGNORE:
            continue
        if "\\" in t or "rainmeter" in t.lower():  # raw paths, desktop widgets
            continue
        short = t.split(" - ")[-1] if " - " in t and len(t) > 40 else t
        if short not in titles:
            titles.append(short[:50])
    minimized = sum(1 for w in pygetwindow.getAllWindows()
                    if (w.title or "").strip() and w.isMinimized)
    if not titles:
        return "Nothing's open right now."
    spoken = ", ".join(titles[:8])
    extra = f", plus {minimized} minimized" if minimized else ""
    return f"On screen: {spoken}{extra}."
