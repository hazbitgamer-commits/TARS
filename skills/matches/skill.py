"""Gaming companion — TARS remembers your sessions and how they went.

game_watch already notices when a game starts and stops; this is the part
that cares: it logs results ("won 3-1"), tracks form over time, and can
save the last 30 seconds of play through Windows' own Game Bar when
something good happens.
"""
import datetime
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))
FILE = BASE / "matches.json"

DESCRIPTION = ("GAMING log and clips — record results ('won three one', "
               "'lost that one', 'we drew'), ask how you're going ('how's "
               "my form', 'how many did I win today'), or save the last 30 "
               "seconds of play ('clip that', 'save that goal'). NOT for "
               "launching games (steam) and NOT for game-session nudges "
               "(that's automatic).")
ARGS = {"action": "'log' (default), 'form', or 'clip'",
        "result": "for log: 'won 3-1', 'lost 0-2', 'drew 1-1'",
        "game": "optional game name"}


def _load() -> list:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save(rows: list) -> None:
    FILE.write_text(json.dumps(rows[-500:], indent=1), encoding="utf-8")


def _current_game() -> str:
    try:
        import game_watch

        return (game_watch._session.get("game") or "").title()
    except Exception:
        return ""


def clip() -> str:
    """Windows Game Bar keeps a rolling buffer; Win+Alt+G saves it."""
    try:
        import pyautogui

        pyautogui.hotkey("win", "alt", "g")
        return ("Clipped — Windows saved the last stretch of play to your "
                "Captures folder.")
    except Exception:
        return "I couldn't reach the Game Bar shortcut."


def run(args: dict) -> str:
    action = str(args.get("action") or "log").strip().lower()
    if action in ("clip", "save", "record"):
        return clip()

    if action in ("played", "playtime", "sessions"):
        try:
            sessions = json.loads(
                (BASE / "game_sessions.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sessions = []
        now = _current_game()
        if not sessions:
            return ("I haven't logged any play sessions yet"
                    + (f" — though you're on {now} right now." if now
                       else ". I'll start once you play something."))
        import collections

        week = [s for s in sessions
                if (datetime.date.today()
                    - datetime.date.fromisoformat(s["day"])).days < 7]
        today = [s for s in sessions
                 if s["day"] == datetime.date.today().isoformat()]
        by_game = collections.Counter()
        for s in week:
            by_game[s["game"].title()] += s["minutes"]
        top = ", ".join(f"{g} {m // 60}h {m % 60}m" if m >= 60
                        else f"{g} {m}m" for g, m in by_game.most_common(3))
        line = f"This week: {top}." if top else "Nothing logged this week."
        if today:
            mins = sum(s["minutes"] for s in today)
            line += f" Today: {mins // 60}h {mins % 60}m across {len(today)} session"
            line += "s." if len(today) != 1 else "."
        if now:
            line += f" You're on {now.title()} right now."
        return line

    if action in ("learn", "teach", "this is a game"):
        import game_watch

        return game_watch.learn_game(str(args.get("game") or ""))

    rows = _load()
    if action in ("form", "record", "stats", "how"):
        if not rows:
            return "No matches logged yet — tell me how one goes and I'll start."
        today = datetime.date.today().isoformat()
        todays = [r for r in rows if r["day"] == today]
        recent = rows[-10:]
        w = sum(1 for r in recent if r["outcome"] == "won")
        l = sum(1 for r in recent if r["outcome"] == "lost")
        d = len(recent) - w - l
        line = (f"Last {len(recent)}: {w} won, {l} lost"
                + (f", {d} drawn" if d else "") + ".")
        if todays:
            tw = sum(1 for r in todays if r["outcome"] == "won")
            line += f" Today: {tw} of {len(todays)}."
        streak = 0
        for r in reversed(rows):
            if r["outcome"] == rows[-1]["outcome"]:
                streak += 1
            else:
                break
        if streak > 1:
            line += f" That's {streak} {rows[-1]['outcome']} in a row."
        return line

    result = str(args.get("result") or "").strip().lower()
    outcome = ("won" if any(w in result for w in ("won", "win", "beat"))
               else "lost" if any(w in result for w in ("lost", "lose", "beaten"))
               else "drew" if any(w in result for w in ("drew", "draw", "tie"))
               else "")
    if not outcome:
        return "Did you win, lose or draw?"
    import re

    score = re.search(r"(\d+)\s*[-–to ]+\s*(\d+)", result)
    rows.append({"day": datetime.date.today().isoformat(),
                 "time": datetime.datetime.now().strftime("%H:%M"),
                 "game": str(args.get("game") or _current_game() or "FC 26"),
                 "outcome": outcome,
                 "score": f"{score.group(1)}-{score.group(2)}" if score else ""})
    _save(rows)
    today = [r for r in rows if r["day"] == datetime.date.today().isoformat()]
    tw = sum(1 for r in today if r["outcome"] == "won")
    return (f"Logged: {outcome}"
            + (f" {score.group(1)}-{score.group(2)}" if score else "")
            + f". That's {tw} win{'s' if tw != 1 else ''} from "
            f"{len(today)} today.")
