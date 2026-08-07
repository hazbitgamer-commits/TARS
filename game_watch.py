"""Game session buddy: notices when Jacob is gaming (foreground window
matches an installed Steam game or known game list), tracks the session,
and after 2 hours offers a gentle hourly nudge. Sets in_session() so
proactive check-ins keep quiet during matches. Ticked from standby."""
import ctypes
import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "game_state.json"
CHECK_EVERY = 60
NUDGE_AFTER = 2 * 3600
NUDGE_GAP = 3600
_last = 0.0
_session = {"game": None, "since": 0.0, "last_nudge": 0.0}
EXTRA_GAMES = ("ea sports fc", "fc 26", "fortnite", "minecraft", "arma",
               "rocket league", "call of duty", "valorant")


def _foreground_title() -> str:
    try:
        h = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(h, buf, n + 1)
        return buf.value or ""
    except Exception:
        return ""


def _steam_titles() -> list[str]:
    try:
        cache = json.loads(STATE.read_text(encoding="utf-8"))
        if time.time() - cache.get("steam_cached", 0) < 3600:
            return cache.get("steam_titles", [])
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    titles = []
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "steam_skill", BASE / "skills" / "steam" / "skill.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        titles = [g["name"].lower() for g in mod._installed()]
    except Exception:
        pass
    cache.update({"steam_titles": titles, "steam_cached": time.time()})
    STATE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return titles


def in_session() -> bool:
    return bool(_session["game"])


def session_minutes() -> int:
    return round((time.time() - _session["since"]) / 60) if in_session() else 0


def _check() -> None:
    import announce
    import quiet

    title = _foreground_title().lower()
    known = _steam_titles() + list(EXTRA_GAMES)
    playing = next((g for g in known if g and g in title), None)

    if playing and not _session["game"]:
        _session.update(game=playing, since=time.time(), last_nudge=0.0)
    elif not playing and _session["game"]:
        _session.update(game=None, since=0.0, last_nudge=0.0)

    if _session["game"]:
        length = time.time() - _session["since"]
        since_nudge = time.time() - (_session["last_nudge"] or _session["since"])
        if length >= NUDGE_AFTER and since_nudge >= NUDGE_GAP \
                and not quiet.is_active()[0]:
            hours = round(length / 3600, 1)
            _session["last_nudge"] = time.time()
            announce.post(f"You've been on {_session['game'].title()} about "
                          f"{hours:g} hours — water, stretch, or one more "
                          f"match, your call.")


def tick() -> None:
    global _last
    now = time.time()
    if now - _last < CHECK_EVERY:
        return
    _last = now
    try:
        _check()
    except Exception:
        pass
