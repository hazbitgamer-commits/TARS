"""Launch a specific game already installed in Steam, by name (not just the
Steam client itself — open_app already handles that)."""
import difflib
import os
import re
import winreg
from pathlib import Path

DESCRIPTION = ("Launch a specific game through Steam by name. E.g. 'open FC26 on "
               "Steam', 'play Counter-Strike 2 on Steam', 'launch Elden Ring in "
               "Steam'. NOT for opening the bare Steam client with no game named "
               "— that's the open_app skill.")
ARGS = {"game": "the name of the Steam game to launch, e.g. 'FC26' or 'Counter-Strike 2'"}


def _steam_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        path, _ = winreg.QueryValueEx(key, "SteamPath")
        p = Path(path)
        if p.exists():
            return p
    except OSError:
        pass
    for guess in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if Path(guess).exists():
            return Path(guess)
    return None


def _library_folders(steam: Path):
    libs = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        text = vdf.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p not in libs:
                libs.append(p)
    return libs


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _installed_games(steam: Path):
    """list of (normalized_name, display_name, appid) for every installed game."""
    games = []
    for lib in _library_folders(steam):
        apps_dir = lib / "steamapps"
        if not apps_dir.is_dir():
            continue
        for manifest in apps_dir.glob("appmanifest_*.acf"):
            try:
                text = manifest.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            name_m = re.search(r'"name"\s+"([^"]+)"', text)
            id_m = re.search(r'"appid"\s+"([^"]+)"', text)
            if name_m and id_m:
                # strip trademark/registered/copyright marks — they read badly out loud
                clean_name = re.sub(r"[™®©]", "", name_m.group(1)).strip()
                games.append((_normalize(clean_name), clean_name, id_m.group(1)))
    return games


def _find(target: str, games: list):
    norm = _normalize(target)
    if not norm:
        return None
    # exact normalized match
    for n, name, appid in games:
        if n == norm:
            return name, appid
    # substring either way (handles "fc26" vs "easportsfc26")
    contains = [(n, name, appid) for n, name, appid in games if norm in n or n in norm]
    if len(contains) == 1:
        _, name, appid = contains[0]
        return name, appid
    if contains:
        contains.sort(key=lambda t: len(t[0]))
        _, name, appid = contains[0]
        return name, appid
    # fuzzy fallback
    close = difflib.get_close_matches(norm, [n for n, _, _ in games], n=1, cutoff=0.5)
    if close:
        for n, name, appid in games:
            if n == close[0]:
                return name, appid
    return None


def run(args: dict) -> str:
    game = (args.get("game") or "").strip()
    if not game:
        return "Which game do you want me to open on Steam?"

    steam = _steam_path()
    if not steam:
        return "I can't find Steam installed on this PC."

    games = _installed_games(steam)
    if not games:
        return "I couldn't find any games installed in your Steam library."

    hit = _find(game, games)
    if not hit:
        return f"I couldn't find {game} in your Steam library."

    name, appid = hit
    os.startfile(f"steam://rungameid/{appid}")
    return f"Launching {name} on Steam."
