import psutil

DESCRIPTION = "Close a running application by name. E.g. 'close spotify', 'kill chrome'."
ARGS = {"target": "the app name to close"}

ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "notepad": "notepad",
    "calculator": "calculator",
    "spotify": "spotify",
    "word": "winword",
    "excel": "excel",
    "steam": "steam",
    "discord": "discord",
    "file explorer": None,  # killing explorer nukes the desktop — refuse
    "explorer": None,
}

PROTECTED = {"explorer.exe", "svchost.exe", "csrss.exe", "winlogon.exe", "lsass.exe",
             "services.exe", "system", "wininit.exe", "dwm.exe", "python.exe", "ollama.exe"}


def run(args: dict) -> str:
    target = (args.get("target") or "").strip().lower()
    if not target:
        return "Close what, exactly?"
    if target in ALIASES and ALIASES[target] is None:
        return "Closing that would take the whole desktop down with it. Declined."
    needle = (ALIASES.get(target) or target).replace(" ", "")

    killed = 0
    for p in psutil.process_iter(["name"]):
        name = (p.info["name"] or "").lower()
        if needle in name and name not in PROTECTED:
            try:
                p.terminate()
                killed += 1
            except psutil.Error:
                pass
    if killed:
        return f"Closed {target}."
    return f"{target} doesn't seem to be running."
