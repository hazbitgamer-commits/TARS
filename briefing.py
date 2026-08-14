"""The morning briefing, sent to his phone before he's at the PC.

There is already an afternoon nudge about homework, but it SPEAKS — which
is no use at seven in the morning when he's in the kitchen and the PC is
asleep in the bedroom. This one goes to Telegram, so it reaches him whether
he's at the desk, at the bus stop, or still in bed.

What it says, in the order he'd want it:
  - what's on at school today, from SEQTA
  - anything due today or tomorrow, soonest first
  - the weather, because Perth mornings decide what he wears

Rules it follows:
  - once a day, and never twice — a repeated briefing is worse than none
  - only on days he actually has school; a Saturday briefing is spam
  - never invents. If SEQTA is down it says so rather than guessing, which
    is the same rule that stopped it making up test dates.
  - silent failure. A missing weather service must not cost him the
    timetable half.
"""
import datetime
import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "briefing_state.json"

SEND_FROM = 6      # not before 6am
SEND_BY = 10       # if the PC didn't wake until 10, the moment has passed


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    try:
        STATE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def _lessons_today() -> str:
    try:
        import seqta

        if not seqta.configured():
            return ""
        today = seqta.day(datetime.date.today())
        if not today:
            return ""
        names = []
        for lesson in today[:6]:
            subject = str(lesson.get("subject") or lesson.get("what") or "").strip()
            if subject and subject not in names:
                names.append(subject)
        return ", ".join(names)
    except Exception:
        return ""


def _due_soon() -> list:
    try:
        import seqta

        if not seqta.configured():
            return []
        today = datetime.date.today().isoformat()
        soon = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        out = []
        for item in seqta.cached().get("due", []):
            when = str(item.get("due", ""))
            if not when or when > soon:
                continue
            label = item.get("what", "")
            if item.get("subject"):
                label += f" ({item['subject']})"
            out.append((when, label, when < today))
        return sorted(out)[:3]
    except Exception:
        return []


def _weather() -> str:
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "weather_skill", BASE / "skills" / "weather" / "skill.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        line = str(mod.run({}) or "").strip()
        # a skill's failure message is still a string. Without this the
        # briefing cheerfully read out "I couldn't reach the weather
        # service" as though it were the forecast.
        low = line.lower()
        if any(w in low for w in ("couldn't", "could not", "can't", "cannot",
                                  "sorry", "unavailable", "failed", "no data")):
            return ""
        return line
    except Exception:
        return ""


def compose() -> str:
    """The briefing text, or "" if there's nothing worth sending."""
    parts = []
    lessons = _lessons_today()
    if lessons:
        parts.append(f"Today: {lessons}.")

    due = _due_soon()
    if due:
        today = datetime.date.today().isoformat()
        bits = []
        for when, label, overdue in due:
            if overdue:
                bits.append(f"{label} (overdue)")
            elif when == today:
                bits.append(f"{label} — due TODAY")
            else:
                bits.append(f"{label} — due {when}")
        parts.append("Due: " + "; ".join(bits) + ".")

    weather = _weather()
    if weather:
        parts.append(weather)

    if not parts:
        return ""
    return "Morning.\n\n" + "\n".join(parts)


def due_today() -> bool:
    """Is it a morning we should be briefing on at all?"""
    now = datetime.datetime.now()
    if now.weekday() >= 5:              # Saturday or Sunday
        return False
    if not (SEND_FROM <= now.hour < SEND_BY):
        return False
    return _state().get("sent") != now.date().isoformat()


def send_if_due() -> str:
    """Called from proactive's tick. Returns what was sent, for the log."""
    if not due_today():
        return ""
    text = compose()
    if not text:
        # nothing known — don't send an empty "Morning." and don't mark the
        # day done, so a later tick can try again once SEQTA answers
        return ""
    try:
        import tars_phone

        if not tars_phone.paired():
            return ""
        tars_phone.send(text, force=True)
    except Exception:
        return ""
    data = _state()
    data["sent"] = datetime.date.today().isoformat()
    data["at"] = time.time()
    _save(data)
    return text
