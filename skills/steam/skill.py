"""Steam game hub: knows what's installed, launches games by name through
Steam itself (steam://rungameid — works even for games with no Start Menu
shortcut), and knows which game the owner touched most recently."""
import difflib
import os
import re
from pathlib import Path

DESCRIPTION = ("the owner's PC games, on BOTH Steam and the Epic Games "
               "Launcher: launch one by name ('launch FC 26', 'start Arma', "
               "'focus Rocket League', 'open Fortnite'), list what's "
               "installed ('what games do I have'), or open the most recent "
               "one ('launch my last game'). NOT for non-game apps (that's "
               "open_app) and NOT for buying anything — launching only.")
ARGS = {"game": "game name to launch, 'list' for the library, or 'last' "
                "for the most recently played one"}


def _steam_root() -> Path | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Valve\Steam") as key:
            return Path(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        return None


def _libraries(root: Path) -> list[Path]:
    libs = [root / "steamapps"]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for m in re.finditer(r'"path"\s+"([^"]+)"',
                             vdf.read_text(encoding="utf-8", errors="ignore")):
            p = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
            if p.exists() and p not in libs:
                libs.append(p)
    return libs


EPIC_MANIFESTS = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")


def _epic_installed() -> list[dict]:
    """Epic keeps one JSON manifest per installed game. Reading them is the
    only way to know what's there — asking the launcher needs it running.

    This exists because "focus Rocket League" got "I can't see Rocket League
    in your Steam library", which is true and useless: it's an Epic game, and
    half the library was invisible.
    """
    import json

    games = []
    try:
        items = sorted(EPIC_MANIFESTS.glob("*.item"))
    except OSError:
        return []
    for item in items:
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        name = str(data.get("DisplayName") or "").strip()
        app = str(data.get("AppName") or "").strip()
        if not (name and app):
            continue
        # Epic files Unreal Engine, Quixel Bridge and the UE plugins in the
        # same folder as the games. Without this, "what games have I got"
        # answers "34" and reads out a list with two plugins in it.
        cats = [str(c).lower() for c in (data.get("AppCategories") or [])]
        if cats and "games" not in cats:
            continue
        for ch in "™®©":       # or the voice reads "Rocket League R"
            name = name.replace(ch, "")
        name = " ".join(name.split())
        exe = ""
        try:
            exe = str(Path(data.get("InstallLocation", ""))
                      / data.get("LaunchExecutable", ""))
        except Exception:
            pass
        games.append({"name": name, "store": "epic", "appname": app,
                      "exe": exe, "touched": item.stat().st_mtime})
    return games


def _installed() -> list[dict]:
    root = _steam_root()
    if not root:
        return sorted(_epic_installed(), key=lambda g: -g["touched"])
    games = []
    for lib in _libraries(root):
        for acf in lib.glob("appmanifest_*.acf"):
            text = acf.read_text(encoding="utf-8", errors="ignore")
            name = re.search(r'"name"\s+"([^"]+)"', text)
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            if not (name and appid):
                continue
            if any(w in name.group(1).lower() for w in
                   ("redistributable", "steamworks", "runtime", "proton")):
                continue  # plumbing, not games
            games.append({"name": name.group(1), "appid": appid.group(1),
                          "store": "steam",
                          "touched": acf.stat().st_mtime})
    return sorted(games + _epic_installed(), key=lambda g: -g["touched"])


def _launch(game: dict) -> str:
    if game.get("store") == "epic":
        # the launcher URI is the reliable route: some Epic games refuse to
        # start without the launcher running, so going straight to the exe
        # is the fallback, not the first try
        try:
            os.startfile(f"com.epicgames.launcher://apps/{game['appname']}"
                         f"?action=launch&silent=true")
        except OSError:
            exe = game.get("exe") or ""
            if not exe or not Path(exe).exists():
                return (f"I can see {game['name']} but couldn't start it — "
                        f"is the Epic launcher installed?")
            os.startfile(exe)
        return (f"Launching {game['name']} through Epic. If the launcher was "
                f"closed it'll take a moment to wake up first.")
    os.startfile(f"steam://rungameid/{game['appid']}")
    return (f"Launching {game['name']} through Steam. If Steam was closed "
            f"it'll take a moment to wake up first.")


def run(args: dict) -> str:
    want = str(args.get("game") or "list").strip().lower()
    games = _installed()
    if not games:
        return ("I can't find any games on this PC — no Steam library and no "
                "Epic games in the usual spots.")

    if want in ("list", "library", "games", ""):
        names = [g["name"] for g in games[:8]]
        more = f" and {len(games) - 8} more" if len(games) > 8 else ""
        steam = sum(1 for g in games if g.get("store") != "epic")
        epic = len(games) - steam
        where = f"{steam} on Steam" + (f" and {epic} on Epic" if epic else "")
        return (f"You've got {len(games)} games — {where}. Most recent "
                f"first: " + ", ".join(names) + more + ".")

    if want in ("last", "latest", "recent", "my last game"):
        return _launch(games[0])

    def _norm(s: str) -> str:
        # "EA SPORTS FC™ 26" must match "fc 26" — strip trademark junk
        # (same disease as the curly-apostrophe room names)
        for ch in "™®©":
            s = s.replace(ch, "")
        return " ".join(s.lower().split())

    want = _norm(want)
    by_name = {_norm(g["name"]): g for g in games}
    subs = [g for g in games if want in _norm(g["name"])]
    if len(subs) == 1:
        return _launch(subs[0])
    if len(subs) > 1:
        return ("A few match: " + ", ".join(g["name"] for g in subs[:4])
                + ". Which one?")
    close = difflib.get_close_matches(want, list(by_name), n=1, cutoff=0.5)
    if close:
        return _launch(by_name[close[0]])
    return (f"I can't see {want} on Steam or Epic. Say 'what games do I "
            f"have' to hear what's installed.")
