"""Game session buddy: notices when the owner is gaming (foreground window
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


SESSIONS = BASE / "game_sessions.json"
EXTRA_FILE = BASE / "known_games.json"


def _log_session(game: str, started: float, ended: float) -> None:
    """Keep a play history — 'what have I been playing this week' needs
    more than the session happening right now."""
    minutes = round((ended - started) / 60)
    if minutes < 3:            # alt-tabbing through a launcher isn't a session
        return
    try:
        rows = json.loads(SESSIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rows = []
    rows.append({"game": game, "minutes": minutes,
                 "day": time.strftime("%Y-%m-%d", time.localtime(started)),
                 "start": time.strftime("%H:%M", time.localtime(started))})
    SESSIONS.write_text(json.dumps(rows[-400:], indent=1), encoding="utf-8")


def learn_game(title: str) -> str:
    """'Call this a game' — teaches TARS a title his Steam list can't see
    (Epic, EA app, browser games)."""
    title = (title or _foreground_title()).strip()
    if len(title) < 3:
        return "I can't see a window title to learn."
    key = title.lower().split(" - ")[0][:40]
    try:
        known = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        known = []
    if key not in known:
        known.append(key)
        EXTRA_FILE.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return f"Got it — I'll count {key} as a game from now on."


def _learned() -> list:
    try:
        return json.loads(EXTRA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def in_session() -> bool:
    return bool(_session["game"])


def playing_now() -> bool:
    """Is a game in front RIGHT NOW — asked without changing anything.

    in_session() is only refreshed on the once-a-minute tick, which is fine
    for nudges and wrong for decisions made the instant he speaks: for the
    first minute of a game it still says no. _check() knows the answer but
    can't be called to find out, because it also logs sessions and announces
    things — asking a question shouldn't cause an announcement.

    The Steam list behind this is cached for an hour, so it costs a window
    title and a substring match.
    """
    try:
        title = _foreground_title().lower()
        if not title:
            return bool(_session["game"])
        known = _steam_titles() + list(EXTRA_GAMES) + _learned()
        return any(game and game in title for game in known)
    except Exception:
        return bool(_session["game"])


def session_minutes() -> int:
    return round((time.time() - _session["since"]) / 60) if in_session() else 0


def _check() -> None:
    import announce
    import quiet

    title = _foreground_title().lower()
    known = _steam_titles() + list(EXTRA_GAMES) + _learned()
    playing = next((g for g in known if g and g in title), None)

    if playing and not _session["game"]:
        _session.update(game=playing, since=time.time(), last_nudge=0.0)
    elif not playing and _session["game"]:
        _log_session(_session["game"], _session["since"], time.time())
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
