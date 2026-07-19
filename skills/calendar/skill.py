"""Google Calendar: read the agenda, add events."""
import datetime
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Google Calendar: what's on today/tomorrow/this week, or add an event. "
               "E.g. 'what's on my calendar today', 'add dentist to my calendar "
               "friday at 3 pm'.")
ARGS = {"action": "'agenda' or 'add'",
        "when": "'today', 'tomorrow', 'week', or for add: a day like 'friday'/'tomorrow'",
        "time": "clock time for add, e.g. '3 pm'",
        "title": "event name, for add"}

NOT_CONNECTED = ("Google isn't connected yet — the setup steps are in the readme, "
                 "or ask Claude to walk you through it.")

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _svc():
    from google_auth import get_service

    return get_service("calendar", "v3")


def _day_from(when: str) -> datetime.date:
    today = datetime.date.today()
    when = when.strip().lower()
    if when in ("", "today"):
        return today
    if when == "tomorrow":
        return today + datetime.timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if name in when:
            ahead = (i - today.weekday()) % 7 or 7
            return today + datetime.timedelta(days=ahead)
    return today


def _fmt_time(iso: str) -> str:
    if "T" not in iso:
        return "all day"
    # the calendar may store times in another timezone — speak Jacob's local time
    t = datetime.datetime.fromisoformat(iso).astimezone()
    return t.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def run(args: dict) -> str:
    action = (args.get("action") or "agenda").strip().lower()
    try:
        svc = _svc()
    except Exception as e:
        return f"Google sign-in hiccuped: {e}"
    if svc is None:
        return NOT_CONNECTED

    if action == "agenda":
        when = (args.get("when") or "today").strip().lower()
        start_day = _day_from("today" if when == "week" else when)
        days = 7 if when == "week" else 1
        start = datetime.datetime.combine(start_day, datetime.time.min).astimezone()
        end = start + datetime.timedelta(days=days)
        res = svc.events().list(
            calendarId="primary", timeMin=start.isoformat(),
            timeMax=end.isoformat(), singleEvents=True,
            orderBy="startTime", maxResults=10).execute()
        events = res.get("items", [])
        label = when if when != "week" else "this week"
        if not events:
            return f"Nothing on the calendar {label}. A blank slate."
        parts = []
        for e in events:
            startv = e["start"].get("dateTime", e["start"].get("date", ""))
            daytag = ""
            if days > 1 and "T" in startv:
                daytag = datetime.datetime.fromisoformat(startv).astimezone().strftime("%A ")
            parts.append(f"{daytag}{_fmt_time(startv)}: {e.get('summary', 'busy')}")
        return f"On the calendar {label}: " + "; ".join(parts) + "."

    if action == "add":
        title = (args.get("title") or "").strip()
        if not title:
            return "Add what to the calendar?"
        day = _day_from(args.get("when") or "today")
        time_raw = (args.get("time") or "").strip().lower().replace(".", "")
        m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", time_raw)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            if m.group(3) == "pm" and hour < 12:
                hour += 12
            if m.group(3) == "am" and hour == 12:
                hour = 0
            start = datetime.datetime.combine(day, datetime.time(hour % 24, minute)).astimezone()
            end = start + datetime.timedelta(hours=1)
            body = {"summary": title,
                    "start": {"dateTime": start.isoformat()},
                    "end": {"dateTime": end.isoformat()}}
            spoken_when = f"{day.strftime('%A')} at {start.strftime('%I:%M %p').lstrip('0')}"
        else:
            body = {"summary": title,
                    "start": {"date": day.isoformat()},
                    "end": {"date": (day + datetime.timedelta(days=1)).isoformat()}}
            spoken_when = f"{day.strftime('%A')}, all day"
        svc.events().insert(calendarId="primary", body=body).execute()
        return f"Added: {title}, {spoken_when}."

    return f"I don't know the calendar action {action}."
