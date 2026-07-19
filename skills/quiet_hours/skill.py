"""Quiet hours: a no-technology schedule for the house. Stored in quiet_hours.json.

This remembers the schedule Jacob wants (e.g. no phones/screens/tech from 8 pm to
7 am) and can report whether it's active right now. It does not control any
devices itself — there's no smart-home hookup here, just the schedule + a
reminder of it.
"""
import datetime
import json
from pathlib import Path

DESCRIPTION = ("Set or check 'quiet hours' — the overnight window when TARS won't "
               "make noise on the house speakers (and future smart-home devices). "
               "E.g. 'add quiet hours from 8 pm to 7 am', 'are we in quiet hours "
               "right now'. During quiet hours, speaker announcements are blocked "
               "unless Jacob explicitly says to override. It does not affect the "
               "PC itself.")
ARGS = {"action": "'set' to save a new quiet-hours schedule, or 'status'/'get' to check it "
                   "(default: 'set' if start/end given, otherwise 'status')",
        "start": "when quiet hours begin, e.g. '8pm', '8 o'clock', '20:00' (defaults to 8 pm)",
        "end": "when quiet hours end, e.g. '7am', '07:00' (defaults to 7 am)"}

STATE_FILE = Path(__file__).resolve().parents[2] / "quiet_hours.json"


def _parse_time(raw: str, default_ampm: str = None) -> datetime.time:
    s = raw.strip().lower().replace(".", "").replace("o'clock", "").replace("oclock", "")
    s = s.strip().replace(" ", "")
    explicit_ampm = None
    if s.endswith("am"):
        explicit_ampm, s = "am", s[:-2]
    elif s.endswith("pm"):
        explicit_ampm, s = "pm", s[:-2]
    if ":" in s:
        h_str, m_str = s.split(":", 1)
        hour, minute = int(h_str), int(m_str)
    else:
        hour, minute = int(s), 0
    # Only fall back to the default am/pm guess for plain 12-hour-style numbers
    # (e.g. "8"). A 24-hour value like "20:00" already tells us it's evening,
    # so don't add another 12 hours to it.
    ampm = explicit_ampm if explicit_ampm else (default_ampm if hour <= 12 else None)
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return datetime.time(hour=hour % 24, minute=minute)


def _fmt(t: datetime.time) -> str:
    text = t.strftime("%I:%M %p")
    if text.endswith(":00 AM") or text.endswith(":00 PM"):
        text = text.replace(":00 ", " ")
    return text.lstrip("0")


def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save(data: dict) -> None:
    STATE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def run(args: dict) -> str:
    action = str(args.get("action") or "").strip().lower()
    start_raw = str(args.get("start") or "").strip()
    end_raw = str(args.get("end") or "").strip()

    if not action:
        action = "set" if (start_raw or end_raw) else "status"

    if action in ("set", "update", "add", "save", "change"):
        try:
            start = _parse_time(start_raw, default_ampm="pm") if start_raw else datetime.time(20, 0)
            end = _parse_time(end_raw, default_ampm="am") if end_raw else datetime.time(7, 0)
        except ValueError:
            return "I didn't catch those times — try something like '8 pm' and '7 am'."
        _save({"start": start.isoformat(), "end": end.isoformat()})
        return f"Quiet hours set: no technology from {_fmt(start)} to {_fmt(end)}."

    data = _load()
    if not data:
        return "No quiet hours set yet. Say something like 'set quiet hours from 8 pm to 7 am'."

    start = datetime.time.fromisoformat(data["start"])
    end = datetime.time.fromisoformat(data["end"])
    now = datetime.datetime.now().time()
    active = (start <= now < end) if start <= end else (now >= start or now < end)
    state = "Quiet hours are active right now" if active else "Quiet hours are not active right now"
    return f"{state} — scheduled {_fmt(start)} to {_fmt(end)}."
