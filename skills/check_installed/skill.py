"""Check whether a program is installed, by reading Windows' installed-programs
list straight from the registry (the same data Control Panel > Programs and
Features shows) — a deeper check than open_app's Start Menu shortcut search.
Grew out of Jacob asking to open "Minicat 3D" and TARS saying it couldn't find
anything by that name: that only meant no Start Menu shortcut matched, not
that the program isn't actually installed. This gives a direct yes/no answer.
"""
import itertools
import winreg

DESCRIPTION = ("Check whether a specific program is installed on this PC, by searching "
               "Windows' installed-programs list (Control Panel > Programs and Features) "
               "rather than just the Start Menu. E.g. 'is minicat 3d installed', 'check "
               "if Blender is installed', 'do I have Steam installed'.")
ARGS = {"name": "the program name to check for"}

UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def _installed_names() -> list[str]:
    """Every DisplayName in the registry's uninstall list, skipping Windows'
    own update/component entries which have no useful name anyway."""
    names = []
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
                display = winreg.QueryValueEx(sub, "DisplayName")[0]
                try:
                    is_component = winreg.QueryValueEx(sub, "SystemComponent")[0]
                except OSError:
                    is_component = 0
                if display and not is_component:
                    names.append(display)
            except OSError:
                pass
    return names


def run(args: dict) -> str:
    target = (args.get("name") or "").strip()
    if not target:
        return "Check if what is installed?"

    names = _installed_names()
    t = target.lower()

    exact = next((n for n in names if n.lower() == t), None)
    if exact:
        return f"Yes — {exact} is installed."

    contains = next((n for n in names if t in n.lower()), None)
    if contains:
        return f"Yes — {contains} is installed."

    import difflib
    close = difflib.get_close_matches(t, [n.lower() for n in names], n=1, cutoff=0.72)
    if close:
        match = next(n for n in names if n.lower() == close[0])
        return f"I don't see an exact match, but {match} is installed — could that be it?"

    return f"I don't see {target} in the list of installed programs on this PC."
