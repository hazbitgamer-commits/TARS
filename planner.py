"""Working backwards from a due date to "start it on Sunday".

TARS already reads out what's due. That's a list, and a list is not a plan —
"History test Monday, Video Analysis Monday, Physics overdue" tells him
he's behind without telling him what to do about it tonight.

This turns due dates into start dates. It does NOT pretend to know how long
his homework takes: it estimates from the kind of task, says so, and stays
out of the way. A wrong estimate he can argue with is more use than no
estimate at all — but it must never be dressed up as fact, which is the
same rule that stopped him inventing test dates.

Nothing here writes to SEQTA or marks anything done. "Done" already lives
in school.json, where the school skill puts it, and this reads that so
finishing something makes it disappear from the plan.
"""
import datetime
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent

# How much work a thing looks like, from what it's called. Deliberately
# coarse — the point is "a test needs a few short revision sessions, an
# investigation needs several longer ones", not false precision.
SHAPES = [
    (r"\b(investigation|report|essay|project|portfolio|folio|design)\b",
     {"sessions": 4, "minutes": 45, "lead": 10, "kind": "a big piece of work"}),
    (r"\b(video|presentation|speech|oral|performance)\b",
     {"sessions": 3, "minutes": 40, "lead": 7, "kind": "something to prepare and practise"}),
    (r"\b(test|exam|quiz|topic test)\b",
     {"sessions": 3, "minutes": 30, "lead": 5, "kind": "revision"}),
    (r"\b(task|assignment|worksheet|questions|analysis)\b",
     {"sessions": 2, "minutes": 40, "lead": 5, "kind": "a task to work through"}),
]
DEFAULT = {"sessions": 2, "minutes": 30, "lead": 4, "kind": "school work"}


def _shape(title: str) -> dict:
    low = (title or "").lower()
    for pattern, shape in SHAPES:
        if re.search(pattern, low):
            return shape
    return DEFAULT


def _done_titles() -> set:
    """What he's already told TARS he's finished."""
    try:
        data = json.loads((BASE / "school.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(w.get("what", "")).lower().strip()
            for w in data.get("work", []) if w.get("done")}


def _upcoming() -> list:
    try:
        import seqta

        if not seqta.configured():
            return []
        return seqta.cached().get("due", []) or []
    except Exception:
        return []


def items(within_days: int = 21) -> list:
    """Everything outstanding, each with a suggested start date.

    Sorted by when it needs STARTING, not when it's due — which is the whole
    point. The thing due furthest away can still be the thing to start
    tonight, if it's the biggest.
    """
    today = datetime.date.today()
    done = _done_titles()
    out = []
    for entry in _upcoming():
        title = str(entry.get("what", "")).strip()
        if not title or title.lower() in done:
            continue
        raw = str(entry.get("due", ""))[:10]
        try:
            due = datetime.date.fromisoformat(raw)
        except ValueError:
            continue
        if (due - today).days > within_days:
            continue
        shape = _shape(title)
        start = due - datetime.timedelta(days=shape["lead"])
        out.append({
            "what": title,
            "subject": str(entry.get("subject", "")).strip(),
            "due": due,
            "days_left": (due - today).days,
            "start": start,
            "start_in": (start - today).days,
            "overdue": due < today,
            "sessions": shape["sessions"],
            "minutes": shape["minutes"],
            "kind": shape["kind"],
        })
    out.sort(key=lambda i: (not i["overdue"], i["start"], i["due"]))
    return out


def _name(item: dict) -> str:
    what = item["what"]
    if len(what) > 52:
        what = what[:49].rstrip() + "..."
    return f"{what} ({item['subject']})" if item["subject"] else what


def today_plan() -> str:
    """What to actually do tonight."""
    jobs = items()
    if not jobs:
        return "Nothing's due in the next three weeks. Enjoy it."

    overdue = [j for j in jobs if j["overdue"]]
    now = [j for j in jobs if not j["overdue"] and j["start_in"] <= 0]
    soon = [j for j in jobs if not j["overdue"] and j["start_in"] > 0]

    lines = []
    if overdue:
        lines.append(f"Overdue: {_name(overdue[0])}"
                     + (f", and {len(overdue) - 1} more" if len(overdue) > 1 else "")
                     + ". Worth asking about an extension if it's not in.")
    if now:
        first = now[0]
        lines.append(f"Start today: {_name(first)} — due in "
                     f"{first['days_left']} day{'s' if first['days_left'] != 1 else ''}. "
                     f"That's {first['kind']}; I'd give it about "
                     f"{first['minutes']} minutes tonight.")
        for job in now[1:2]:
            lines.append(f"Also running: {_name(job)}, due in "
                         f"{job['days_left']} days.")
    if not overdue and not now and soon:
        nxt = soon[0]
        lines.append(f"Nothing needs starting today. Next up is "
                     f"{_name(nxt)} — start in {nxt['start_in']} "
                     f"day{'s' if nxt['start_in'] != 1 else ''}, due "
                     f"{nxt['due'].strftime('%a %d %b')}.")
    return " ".join(lines)


def week_plan() -> str:
    """The next fortnight, as a schedule rather than a list."""
    jobs = items()
    if not jobs:
        return "Nothing due in the next three weeks."

    today = datetime.date.today()
    lines = []
    for job in jobs[:6]:
        if job["overdue"]:
            when = "OVERDUE"
        elif job["start_in"] <= 0:
            when = "start now"
        else:
            when = f"start {job['start'].strftime('%a %d %b')}"
        lines.append(f"{_name(job)} — due {job['due'].strftime('%a %d %b')}, "
                     f"{when}, about {job['sessions']} x {job['minutes']} min")
    extra = len(jobs) - 6
    tail = f"\n...and {extra} more further out." if extra > 0 else ""
    return ("Working backwards from the due dates (my estimates, not the "
            "school's):\n" + "\n".join(lines) + tail)


def when_to_start(query: str) -> str:
    """'When should I start the history test?'"""
    words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower())
             if len(w) > 2]
    if not words:
        return week_plan()
    best, score = None, 0
    for job in items(within_days=60):
        hay = f"{job['what']} {job['subject']}".lower()
        hits = sum(1 for w in words if w in hay)
        if hits > score:
            best, score = job, hits
    if not best:
        return ("I can't find that in your assessments. Say 'what should I "
                "work on' and I'll go through what's actually due.")
    if best["overdue"]:
        return f"{_name(best)} was due {best['due'].strftime('%a %d %b')} — that one's late."
    if best["start_in"] <= 0:
        return (f"{_name(best)} is due {best['due'].strftime('%a %d %b')} — "
                f"you should already be on it. It's {best['kind']}, so about "
                f"{best['sessions']} sessions of {best['minutes']} minutes.")
    return (f"{_name(best)} is due {best['due'].strftime('%a %d %b')}. I'd "
            f"start it {best['start'].strftime('%a %d %b')} — "
            f"{best['start_in']} days away — and give it about "
            f"{best['sessions']} sessions of {best['minutes']} minutes.")
