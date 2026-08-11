"""SEQTA Learn — the owner's actual school timetable and assessments.

SEQTA has no public API; this talks to the same endpoints the student web
app itself uses. That means it can break when his school updates SEQTA, so
every call fails SOFTLY: TARS falls back to the cached copy, and then to
whatever the owner has entered by hand, rather than pretending it knows.

Credentials live in tars/.env and never leave this machine:
    SEQTA_URL=https://learn.yourschool.wa.edu.au
    SEQTA_USER=your.username
    SEQTA_PASS=your password
the owner writes those himself — nobody else ever types them.
"""
import datetime
import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
# overridable so testing against a stand-in server can't scribble over
# the owner's real cached timetable (it did once)
CACHE = Path(os.getenv("SEQTA_CACHE") or BASE / "seqta_cache.json")
FRESH_HOURS = 6  # re-fetch at most this often; cache covers the rest


class SeqtaError(Exception):
    """Carries a sentence TARS can say out loud, not a stack trace."""


def configured() -> bool:
    return bool(_setting("SEQTA_URL") and _setting("SEQTA_USER")
                and _setting("SEQTA_PASS"))


def _setting(key: str) -> str:
    value = (os.getenv(key) or "").strip().strip('"').strip("'")
    if value:
        return value
    try:  # main.py loads .env at startup, but skills can run standalone
        for line in (BASE / ".env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _base_url() -> str:
    url = _setting("SEQTA_URL").rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    return url


def _login():
    """Returns (session, student_id). Raises SeqtaError with plain English."""
    import requests

    if not configured():
        raise SeqtaError(
            "SEQTA isn't set up yet. Put SEQTA_URL, SEQTA_USER and SEQTA_PASS "
            "into the .env file in the TARS folder, then say connect to SEQTA.")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 TARS",
                            "Content-Type": "application/json; charset=utf-8"})
    url = f"{_base_url()}/seqta/student/login"
    try:
        r = session.post(url, json={"username": _setting("SEQTA_USER"),
                                    "password": _setting("SEQTA_PASS"),
                                    "token": ""}, timeout=25)
    except requests.RequestException:
        raise SeqtaError("I couldn't reach SEQTA — check the address in .env, "
                         "or the school's site is down.")
    if r.status_code == 404:
        raise SeqtaError("That address doesn't look like a SEQTA site. It "
                         "should be the same one you log into in the browser.")
    try:
        data = r.json()
    except ValueError:
        raise SeqtaError("SEQTA answered with a login page instead of data — "
                         "your school is probably using a Microsoft or Google "
                         "sign-in, which I can't do.")
    payload = data.get("payload") or {}
    if str(data.get("status", "")) not in ("200", "ok") or not payload:
        raise SeqtaError("SEQTA turned down that username and password.")
    student = payload.get("id") or payload.get("personUUID") or 0
    return session, student


def _post(session, path: str, body: dict) -> dict:
    import requests

    try:
        r = session.post(f"{_base_url()}/seqta/student/{path}", json=body,
                         timeout=25)
        return r.json()
    except (requests.RequestException, ValueError):
        raise SeqtaError("SEQTA stopped answering halfway through.")


def _clock(value) -> str:
    """'09:05:00' -> '9:05'."""
    text = str(value or "")[:5]
    return text[1:] if text.startswith("0") else text


def fetch(days: int = 8) -> dict:
    """One trip: timetable for the next week plus upcoming assessments."""
    session, student = _login()
    today = datetime.date.today()
    lessons_raw = _post(session, "load/timetable", {
        "from": today.isoformat(),
        "until": (today + datetime.timedelta(days=days)).isoformat(),
        "student": student}).get("payload", {}).get("items", []) or []
    lessons = []
    for item in lessons_raw:
        lessons.append({
            "date": str(item.get("date", ""))[:10],
            "subject": (item.get("description") or item.get("code") or
                        "").strip(),
            "start": _clock(item.get("from")),
            "end": _clock(item.get("until")),
            # the 24-hour original, kept for ordering: sorting the spoken
            # times as text put 11:05 before 8:30 and read his day backwards
            "at": str(item.get("from") or "")[:5],
            "room": (item.get("room") or "").strip(),
            "teacher": (item.get("staff") or "").strip()})
    lessons = [l for l in lessons if l["subject"] and l["date"]]
    lessons.sort(key=lambda l: (l["date"], l["at"] or "99:99"))

    due_raw = _post(session, "assessment/list/upcoming",
                    {"student": student}).get("payload", []) or []
    due = []
    for item in due_raw:
        if not isinstance(item, dict):
            continue
        due.append({"what": (item.get("title") or "assessment").strip(),
                    "subject": (item.get("subject") or item.get("code") or
                                "").strip(),
                    "due": str(item.get("due", ""))[:10]})
    due = [d for d in due if d["due"]]
    due.sort(key=lambda d: d["due"])

    data = {"fetched": datetime.datetime.now().isoformat(timespec="seconds"),
            "lessons": lessons, "due": due}
    try:
        CACHE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass
    return data


def cached() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def data(force: bool = False) -> dict:
    """Fresh if it can be, cached if it can't. Never raises for a read —
    a school portal being down must not stop TARS answering."""
    have = cached()
    if not force and have.get("fetched"):
        age = (datetime.datetime.now() - datetime.datetime.fromisoformat(
            have["fetched"])).total_seconds() / 3600
        if age < FRESH_HOURS:
            return have
    try:
        return fetch()
    except SeqtaError:
        return have
    except Exception:
        return have


def day(when: datetime.date) -> list[dict]:
    return [l for l in data().get("lessons", [])
            if l["date"] == when.isoformat()]


def test() -> str:
    """What the owner hears when he says 'connect to SEQTA'."""
    try:
        fresh = fetch()
    except SeqtaError as e:
        return str(e)
    except Exception as e:
        return f"SEQTA connection failed: {e}"
    lessons, due = len(fresh["lessons"]), len(fresh["due"])
    if not lessons and not due:
        return ("Logged into SEQTA, but it gave me no timetable and no "
                "assessments — you might be on holidays, or your school's "
                "SEQTA is arranged differently to the one I expected.")
    parts = []
    if lessons:
        parts.append(f"{lessons} lessons over the next week")
    if due:
        parts.append(f"{due} assessments coming up")
    return "Connected to SEQTA. I can see " + " and ".join(parts) + "."
