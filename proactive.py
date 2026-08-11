"""Proactive check-ins: TARS speaks up UNPROMPTED — but only on hard
rules, never on a whim. v1 rules:
  - a calendar event starts within 15 minutes (announced once per event)
  - suppressed entirely during quiet hours and while the owner is mid-game
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


def _school() -> None:
    """One nudge, late afternoon, about school work due tomorrow — what
    the owner's told me himself AND, if SEQTA's connected, real assessments the
    school portal knows about (so he doesn't have to type those in for a
    reminder to happen). Homework is only useful to hear about while
    there's still an evening left."""
    try:
        import announce

        now = datetime.datetime.now()
        if now.hour < 16 or now.hour >= 21:
            return
        s = _state()
        today = now.date().isoformat()
        if s.get("school_nudge") == today:
            return
        # school.json only exists once the owner has typed something in himself.
        # Reading it unguarded threw straight past the SEQTA block below, so
        # the SEQTA half of this reminder had never once fired.
        try:
            data = json.loads((BASE / "school.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"work": []}
        tomorrow = (now.date() + datetime.timedelta(days=1)).isoformat()
        due = [(w["what"], w.get("due", "")) for w in data.get("work", [])
               if not w.get("done") and w.get("due", "") <= tomorrow]
        try:
            import seqta

            if seqta.configured():
                marked_done = {w["what"].lower() for w in data.get("work", [])
                               if w.get("done")}
                for item in seqta.cached().get("due", []):
                    # a reminder must not wait on a school-portal login
                    if item.get("due", "") > tomorrow:
                        continue
                    if item.get("what", "").lower() in marked_done:
                        continue  # he's already told me it's finished
                    label = (f"{item['what']} for {item['subject']}"
                             if item.get("subject") else item["what"])
                    if label not in [d[0] for d in due]:
                        due.append((label, item.get("due", "")))
        except Exception:
            pass  # SEQTA being down must never break the nudge
        s["school_nudge"] = today
        _save(s)
        # something 6 days late is not "due by tomorrow" — say which is which
        soon = [label for label, when in due if when >= today]
        late = [label for label, when in due if when < today]
        line = ""
        if soon:
            line = f"Reminder — {', '.join(soon[:3])} due by tomorrow."
            if late:
                line += f" {len(late)} still overdue as well."
        elif late:
            line = (f"Reminder — {late[0]} is overdue"
                    + (f", and {len(late) - 1} more." if len(late) > 1 else "."))
        if line:
            announce.post(line)
    except Exception:
        pass


def _check() -> None:
    try:
        import announce
        import quiet

        if quiet.is_active()[0] or _gaming():
            return
        _school()
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
