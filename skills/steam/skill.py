"""Steam game hub: knows what's installed, launches games by name through
Steam itself (steam://rungameid — works even for games with no Start Menu
shortcut), and knows which game the owner touched most recently."""
import difflib
import os
import re
from pathlib import Path

DESCRIPTION = ("the owner's Steam games: launch one by name ('launch FC 26', "
               "'start Arma'), list what's installed ('what games do I "
               "have'), or open the most recent one ('launch my last "
               "game'). NOT for non-Steam apps (that's open_app) and NOT "
               "for buying anything — launching only.")
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


def _installed() -> list[dict]:
    root = _steam_root()
    if not root:
        return []
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
                          "touched": acf.stat().st_mtime})
    return sorted(games, key=lambda g: -g["touched"])


def _launch(game: dict) -> str:
    os.startfile(f"steam://rungameid/{game['appid']}")
    return (f"Launching {game['name']} through Steam. If Steam was closed "
            f"it'll take a moment to wake up first.")


def run(args: dict) -> str:
    want = str(args.get("game") or "list").strip().lower()
    games = _installed()
    if not games:
        return ("I can't find a Steam library on this PC — is Steam "
                "installed in the usual spot?")

    if want in ("list", "library", "games", ""):
        names = [g["name"] for g in games[:8]]
        more = f" and {len(games) - 8} more" if len(games) > 8 else ""
        return (f"You've got {len(games)} Steam games. Most recent first: "
                + ", ".join(names) + more + ".")

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
    return (f"I can't see {want} in your Steam library. Say 'what games do "
            f"I have' to hear what's installed.")
