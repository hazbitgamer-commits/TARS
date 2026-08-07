"""Proactive check-ins: TARS speaks up UNPROMPTED — but only on hard
rules, never on a whim. v1 rules:
  - a calendar event starts within 15 minutes (announced once per event)
  - suppressed entirely during quiet hours and while Jacob is mid-game
    (game_watch sets the flag) — being useful never means being annoying.
Ticked ~1/sec from main's standby loop; real checks every 5 minutes."""
import datetime
import json
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "proactive_state.json"
CHECK_EVERY = 300
_last = 0.0


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def _gaming() -> bool:
    try:
        import game_watch

        return game_watch.in_session()
    except Exception:
        return False


def _check() -> None:
    try:
        import announce
        import quiet

        if quiet.is_active()[0] or _gaming():
            return
        from google_auth import get_service

        service = get_service("calendar", "v3")
        now = datetime.datetime.now(datetime.timezone.utc)
        soon = now + datetime.timedelta(minutes=15)
        events = service.events().list(
            calendarId="primary", timeMin=now.isoformat(),
            timeMax=soon.isoformat(), singleEvents=True,
            orderBy="startTime", maxResults=3).execute().get("items", [])
        s = _state()
        announced = s.get("announced", [])
        for e in events:
            eid = e.get("id", "")
            start_raw = e.get("start", {}).get("dateTime")
            if not eid or eid in announced or not start_raw:
                continue
            start = datetime.datetime.fromisoformat(start_raw).astimezone()
            mins = max(1, round((start - datetime.datetime.now(
                start.tzinfo)).total_seconds() / 60))
            title = e.get("summary", "something on the calendar")
            announce.post(f"Heads up — {title} in about {mins} "
                          f"minute{'s' if mins != 1 else ''}.")
            announced.append(eid)
        s["announced"] = announced[-50:]
        _save(s)
    except Exception:
        pass  # never let a check-in break the voice loop


def tick() -> None:
    global _last
    now = time.time()
    if now - _last < CHECK_EVERY:
        return
    _last = now
    threading.Thread(target=_check, daemon=True).start()
