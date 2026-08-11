"""'What did I miss?' — everything that happened while the owner was at school,
asleep, or otherwise not listening.

Built entirely from what was actually logged: announcements TARS made to an
empty room, timers that fired, phone messages, and what Kipp shipped or had
reverted. No summarising model, because a catch-up that invents an event is
worse than no catch-up at all.
"""
import datetime
import json
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SEEN = BASE / "missed_seen.json"

DESCRIPTION = ("Catch the owner up on what happened while he was away — 'what "
               "did I miss', 'anything happen while I was out', 'catch me "
               "up', 'what have I missed today'. Reports announcements he "
               "wasn't there for, timers that went off, phone messages, and "
               "what Kipp changed. NOT a recap of what HE did (day_recap) "
               "and NOT the day's plan (nightly_wrap, calendar).")
ARGS = {"since": "optional: 'today' to sweep the whole day regardless"}


def _since() -> float:
    try:
        return float(json.loads(SEEN.read_text(encoding="utf-8"))["at"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return time.time() - 43200  # first ask: the last twelve hours


def _mark() -> None:
    try:
        SEEN.write_text(json.dumps({"at": time.time()}), encoding="utf-8")
    except OSError:
        pass


def _stamp(row: dict) -> float:
    try:
        return datetime.datetime.fromisoformat(row["t"]).timestamp()
    except (KeyError, ValueError, TypeError):
        return 0.0


def _log_rows(cutoff: float) -> list[dict]:
    rows = []
    today = datetime.date.today()
    for day in (today - datetime.timedelta(days=1), today):
        path = BASE / "logs" / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8",
                                   errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _stamp(row) >= cutoff:
                rows.append(row)
    return rows


def _kipp(cutoff: float) -> list[str]:
    out = []
    try:
        lines = (BASE / "improvements.log").read_text(
            encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines[-60:]:
        stamp, _, rest = line.partition(" ")
        try:
            when = datetime.datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            continue
        if when < cutoff:
            continue
        if rest.startswith("DONE"):
            out.append("Kipp shipped " + rest.split("—", 1)[-1].strip()[:90])
        elif rest.startswith("UNVERIFIED"):
            out.append("Kipp tried " + rest.split(":", 1)[-1].split("—")[0]
                       .strip()[:70] + " but couldn't prove it, so it was "
                       "put back")
        elif rest.startswith("PROPOSAL OFFERED"):
            out.append("Kipp's asking about " + rest.split("—", 1)[0]
                       .replace("PROPOSAL OFFERED:", "").strip()[:70])
    return out


def run(args: dict) -> str:
    cutoff = (time.time() - 86400 if "today" in str(args.get("since", "")).lower()
              else _since())
    away = max(1, int((time.time() - cutoff) / 60))
    rows = _log_rows(cutoff)
    _mark()

    announcements, phone, timers = [], [], []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text or row.get("kind") != "said":
            if row.get("kind") == "heard" and text.startswith("[phone]"):
                phone.append(text[7:].strip()[:80])
            continue
        if text.startswith("(voice:"):
            continue
        if re.match(r"^(time'?s up|timer|reminder\b|heads up)", text, re.I):
            timers.append(text[:90])
        elif text.startswith(("Kipp here", "Scout here", "Big brain")):
            continue  # improvements.log covers these, with the outcome
        elif re.match(r"^(reminder —|don'?t forget)", text, re.I):
            timers.append(text[:90])

    # the same warning announced six times is one thing to tell him, not six
    def _unique(items: list[str]) -> list[str]:
        seen, out = set(), []
        for item in items:
            key = item[:40].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    parts = []
    for label, items in (("went off", _unique(timers)),
                         ("from your phone", _unique(phone))):
        if items:
            extra = ""
            if label == "went off":
                repeats = len(timers) - len(items)
                extra = f", plus {repeats} repeats" if repeats else ""
            parts.append(f"{'; '.join(items[:3])}{extra} ({label})")
    parts += _kipp(cutoff)[:3]

    window = (f"{away} minutes" if away < 90 else
              f"{round(away / 60)} hours" if away < 2880 else "a while")
    if not parts:
        return f"Nothing to report from the last {window}. All quiet."
    return f"In the last {window}: " + ". ".join(parts) + "."
