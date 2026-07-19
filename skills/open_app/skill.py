"""Open anything: apps (EVERY installed one, via the Start Menu + Store apps),
user folders, or websites. Fuzzy name matching, so 'open epic games' works."""
import difflib
import os
import time
from pathlib import Path

DESCRIPTION = ("Open an application (any installed program), a user folder, or a "
               "website. E.g. 'open chrome', 'open epic games', 'open my pictures "
               "folder', 'open youtube dot com'.")
ARGS = {"target": "the app name, folder name, or website address to open"}

FOLDERS = {"pictures": "Pictures", "photos": "Pictures", "downloads": "Downloads",
           "documents": "Documents", "desktop": "Desktop", "videos": "Videos",
           "music": "Music"}

# instant paths for the most common asks (protocols beat shortcut resolution)
ALIASES = {
    "chrome": "chrome", "google chrome": "chrome", "browser": "brave",
    "notepad": "notepad", "calculator": "calc", "file explorer": "explorer",
    "explorer": "explorer", "files": "explorer", "word": "winword",
    "excel": "excel", "spotify": "spotify:", "settings": "ms-settings:",
    "steam": "steam://open/main", "task manager": "taskmgr", "paint": "mspaint",
    "obsidian": "obsidian://", "discord": "discord:",
}

SITE_WORDS = {" dot com": ".com", " dot net": ".net", " dot org": ".org", " dot au": ".au"}

_index: dict = {"t": 0.0, "apps": {}}


def _build_index() -> dict[str, str]:
    """name -> launchable path for everything in the Start Menu + Store apps."""
    apps: dict[str, str] = {}
    for root in (os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
                 os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs")):
        for dirpath, dirnames, files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in
                           ("uninstall", "windows tools")]
            for f in files:
                if f.lower().endswith((".lnk", ".url")):
                    name = f.rsplit(".", 1)[0].lower()
                    if "uninstall" not in name:
                        apps.setdefault(name, str(Path(dirpath) / f))
    try:  # Store/UWP apps (Settings, Xbox, WhatsApp...)
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("Shell.Application")
        for item in shell.NameSpace("shell:AppsFolder").Items():
            apps.setdefault(item.Name.lower(), "shell:AppsFolder\\" + item.Path)
    except Exception:
        pass
    return apps


def _apps() -> dict[str, str]:
    if time.time() - _index["t"] > 300 or not _index["apps"]:
        _index["apps"] = _build_index()
        _index["t"] = time.time()
    return _index["apps"]


def _resolve(target: str):
    """(path, name) | list of candidate names | None."""
    apps = _apps()
    t = target.lower().strip()
    if t in apps:
        return apps[t], t
    contains = sorted((n for n in apps if t in n), key=len)
    if contains:
        return apps[contains[0]], contains[0]
    words = [w for w in t.split() if len(w) >= 2]
    if words:
        word_hits = sorted((n for n in apps if all(w in n for w in words)), key=len)
        if word_hits:
            return apps[word_hits[0]], word_hits[0]
    close = difflib.get_close_matches(t, list(apps), n=3, cutoff=0.72)
    if len(close) == 1:
        return apps[close[0]], close[0]
    if close:
        return close  # ambiguous — let TARS ask
    return None


def run(args: dict) -> str:
    target = (args.get("target") or "").strip().lower()
    if not target:
        return "Open what, exactly?"
    for spoken, real in SITE_WORDS.items():
        target = target.replace(spoken, real)

    # files TARS created live in the workshop — check there before anything else
    workshop = Path(__file__).resolve().parents[2] / "workshop"
    candidate = workshop / Path(target).name
    if candidate.is_file():
        os.startfile(candidate)
        return f"Opening {candidate.name}."

    if "." in target and " " not in target:  # looks like a website
        url = target if target.startswith("http") else "https://" + target
        os.startfile(url)
        return f"Opening {target}."

    cleaned = target.replace("my ", "").replace(" folder", "").strip()
    if cleaned in FOLDERS:
        folder = Path.home() / FOLDERS[cleaned]
        if folder.exists():
            os.startfile(folder)
            return f"Opening your {FOLDERS[cleaned]} folder."

    if target in ALIASES:
        try:
            os.startfile(ALIASES[target])
            return f"Opening {target}."
        except OSError:
            pass  # alias broken on this machine — fall through to the index

    stripped = target.replace("the ", "").replace(" app", "").strip()
    hit = _resolve(stripped)
    if isinstance(hit, tuple):
        try:
            os.startfile(hit[0])
            return f"Opening {hit[1].title()}."
        except OSError:
            return f"I found {hit[1]} but Windows wouldn't launch it."
    if isinstance(hit, list):
        return ("Did you mean " + ", ".join(h.title() for h in hit[:3]) +
                "? Say the full name.")
    return f"I can't find anything called {target} installed on this PC."
