"""List installed software (from the Windows Uninstall registry — the same
source Add/Remove Programs reads), or check whether a specific program is
installed. Grew from the owner asking to open "cadm" and getting back "nothing
installed by that name" — this lets him ask directly whether something's
on the PC, or see what is, instead of guessing from a failed open."""
import itertools
import winreg

DESCRIPTION = ("List installed software, or check if a specific program is "
               "installed — 'what's installed on this PC', 'is cadm "
               "installed', 'do I have Python installed', 'list installed "
               "programs'. Reads the same registry Add/Remove Programs "
               "does. NOT for opening an app (open_app), PC specs "
               "(pc_specs), or code project folders/repos/repositories "
               "(project_status).")
ARGS = {"name": "optional — part of a program's name to check for; blank lists everything"}

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]
SKIP_RELEASE_TYPES = {"Update", "Hotfix", "Security Update"}


def _installed() -> list[str]:
    """Program display names from the registry — deduped, with system
    components and Windows updates filtered out."""
    names = set()
    for hive, path in UNINSTALL_KEYS:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in itertools.count():
            try:
                sub_name = winreg.EnumKey(key, i)
            except OSError:
                break
            try:
                sub = winreg.OpenKey(key, sub_name)
                name = winreg.QueryValueEx(sub, "DisplayName")[0].strip()
                if not name:
                    continue
                try:
                    if winreg.QueryValueEx(sub, "SystemComponent")[0] == 1:
                        continue
                except OSError:
                    pass
                try:
                    if winreg.QueryValueEx(sub, "ReleaseType")[0] in SKIP_RELEASE_TYPES:
                        continue
                except OSError:
                    pass
                names.add(name)
            except OSError:
                continue
    return sorted(names, key=str.lower)


def run(args: dict) -> str:
    query = (args.get("name") or "").strip()
    try:
        names = _installed()
    except Exception:
        return "I couldn't read the installed-programs list."
    if not names:
        return "I couldn't find any installed programs listed."

    if query:
        hits = [n for n in names if query.lower() in n.lower()]
        if not hits:
            return f"I don't see anything installed matching {query}."
        if len(hits) == 1:
            return f"Yes — {hits[0]} is installed."
        shown = ", ".join(hits[:6])
        more = f", and {len(hits) - 6} more" if len(hits) > 6 else ""
        return f"Found {len(hits)} matching {query}: {shown}{more}."

    sample = ", ".join(names[:12])
    return (f"You have {len(names)} programs installed. A few: {sample}. "
            "Ask me about a specific one to check.")
