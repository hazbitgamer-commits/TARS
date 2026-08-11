"""School: the owner's timetable, what's due, and study sessions. Everything is
told to TARS in his own words — no school portal, no login, no account."""
import datetime
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FILE = BASE / "school.json"

DESCRIPTION = ("SCHOOL — the timetable, homework and assignment due dates, "
               "and study sessions. 'What have I got tomorrow', 'what's due "
               "this week', 'I've got a maths assignment due Friday', 'on "
               "Mondays I have maths, english and science', 'start a study "
               "session', 'I've finished the history essay', 'when's my "
               "next test', 'list the next three assessments I've got' "
               "(action 'due' with index/count). NOT for general calendar "
               "events (calendar) and NOT for plain reminders (timers).")
ARGS = {"action": "'timetable', 'set_timetable', 'due', 'add_work', 'done', "
                  "'study', or 'stop_study'",
        "text": "what the owner said — the subjects, the assignment, or the day",
        "day": "optional day name: 'today', 'tomorrow', 'monday'...",
        "minutes": "study block length, default 25",
        "index": "for 'due' — 'my next test'/'the one after' -> 0, 1, 2...",
        "count": "for 'due' — 'the next N assessments', e.g. 3"}

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday"]
SUBJECT_WORDS = {"maths", "math", "english", "science", "history",
                 "geography", "art", "music", "drama", "pe", "hass",
                 "chemistry", "physics", "biology", "italian", "japanese",
                 "french", "german", "chinese", "woodwork", "metalwork",
                 "cooking", "media", "business", "economics", "health",
                 "sport", "religion", "coding", "computing", "psychology"}

SHORT = {"mon": "monday", "tue": "tuesday", "tues": "tuesday",
         "wed": "wednesday", "weds": "wednesday", "thu": "thursday",
         "thur": "thursday", "thurs": "thursday", "fri": "friday",
         "sat": "saturday", "sun": "sunday"}


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"timetable": {}, "work": [], "study": {}}


def _save(data: dict) -> None:
    try:
        FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _day_name(word: str, base: datetime.date | None = None) -> str | None:
    """'tomorrow' / 'friday' / 'tues' -> a weekday name."""
    word = (word or "").strip().lower()
    today = base or datetime.date.today()
    if word in ("today", "tonight"):
        return DAYS[today.weekday()]
    if word == "tomorrow":
        return DAYS[(today + datetime.timedelta(days=1)).weekday()]
    if word in DAYS:
        return word
    if word.endswith("s") and word[:-1] in DAYS:
        return word[:-1]  # "on Mondays I have maths"
    return SHORT.get(word)


def _next_date(day: str) -> datetime.date:
    """The next time that weekday comes round (today counts)."""
    today = datetime.date.today()
    target = DAYS.index(day)
    ahead = (target - today.weekday()) % 7
    return today + datetime.timedelta(days=ahead)


def _speak_date(date: datetime.date) -> str:
    today = datetime.date.today()
    days = (date - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if 0 < days < 7:
        return f"on {date.strftime('%A')}"
    if days < 0:
        return f"{-days} days ago"
    return f"on {date.strftime('%A the %d').lstrip('0')}"


def _subjects(text: str) -> list[str]:
    """'maths, english and science' -> ['Maths', 'English', 'Science']"""
    body = re.split(r"\bi have\b|\bi've got\b|\bi got\b|:", text, 1)[-1]
    body = re.sub(r"\bon \w+day\b|\bevery\b|\bmy\b", "", body, flags=re.I)
    out = []
    for chunk in re.split(r",|\band\b|\bthen\b", body):
        name = chunk.strip(" .!?").strip()
        name = re.sub(r"^(a|an|the)\s+", "", name, flags=re.I)
        if not (1 < len(name) <= 30) or name.lower().startswith("period"):
            continue
        # "maths english and science" with no comma is TWO subjects, but
        # "food tech" and "design and technology" are one — only split when
        # both halves are subjects in their own right
        pieces = name.split()
        if len(pieces) == 2 and all(p.lower() in SUBJECT_WORDS for p in pieces):
            out += [p[0].upper() + p[1:] for p in pieces]
        else:
            out.append(name[0].upper() + name[1:])
    return out[:9]


def _set_timetable(data: dict, text: str, day_hint: str) -> str:
    day = None
    for word in re.findall(r"[a-z]+", text.lower()):
        day = _day_name(word) or day
        if day:
            break
    day = day or _day_name(day_hint)
    if not day:
        return "Which day? Say something like 'on Mondays I have maths and english'."
    subjects = _subjects(text)
    if not subjects:
        return f"What have you got on {day.title()}?"
    data.setdefault("timetable", {})[day] = subjects
    _save(data)
    return f"{day.title()}: {', '.join(subjects)}. Got it."


def _seqta():
    """The real school portal, if the owner has connected it. Never fatal."""
    import importlib.util
    import sys

    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    try:
        import seqta

        return seqta if seqta.configured() else None
    except Exception:
        return None


def _lesson_line(lesson: dict) -> str:
    bit = f"{lesson['subject']} at {lesson['start']}"
    if lesson.get("room"):
        bit += f" in {lesson['room']}"
    return bit


def _seqta_day(when: datetime.date, period: str = "") -> str:
    """SEQTA's own timetable for a date, spoken. '' if it has nothing.
    `period` picks one lesson out: 'first', 'last', or a number."""
    portal = _seqta()
    if not portal:
        return ""
    try:
        lessons = portal.day(when)
    except Exception:
        return ""
    if not lessons:
        return ""
    label = _speak_date(when).capitalize()
    if period:
        if period == "first":
            index = 0
        elif period == "last":
            index = len(lessons) - 1
        else:
            try:
                index = max(0, int(period) - 1)
            except ValueError:
                index = 0
        if index >= len(lessons):
            return (f"You've only got {len(lessons)} lessons {_speak_date(when)}. "
                    f"The last one is {_lesson_line(lessons[-1])}.")
        which = {0: "First up", len(lessons) - 1: "Last"}.get(
            index, f"Lesson {index + 1}")
        return f"{which} {_speak_date(when)}: {_lesson_line(lessons[index])}."
    parts = [_lesson_line(l) for l in lessons]
    return f"{label} — " + ", then ".join(parts) + "."


def _timetable(data: dict, day_hint: str, text: str, period: str = "") -> str:
    # the portal wins when it's connected: it knows about relief teachers,
    # room changes and one-off timetables in a way a saved list never will
    day_word = _day_name(day_hint) or next(
        (d for d in (_day_name(w) for w in re.findall(r"[a-z]+", text.lower()))
         if d), None)
    if day_word:
        spoken = _seqta_day(_next_date(day_word), str(period or ""))
        if spoken:
            return spoken

    table = data.get("timetable", {})
    if not table:
        return ("I don't know your timetable yet. Tell me like this: 'on "
                "Mondays I have maths, english and science'.")
    day = _day_name(day_hint) or None
    if not day:
        for word in re.findall(r"[a-z]+", text.lower()):
            day = _day_name(word)
            if day:
                break
    if not day:
        listed = [f"{d.title()}: {', '.join(s)}" for d, s in table.items()]
        return "Your week — " + ". ".join(listed) + "."
    subjects = table.get(day)
    if not subjects:
        return f"Nothing saved for {day.title()}."
    when = "Today" if day == DAYS[datetime.date.today().weekday()] else day.title()
    return f"{when}: {', '.join(subjects)}."


def _add_work(data: dict, text: str, day_hint: str) -> str:
    due_day = None
    match = re.search(r"\b(?:due|for|by|on)\s+(next\s+)?([a-z]+)", text.lower())
    if match:
        due_day = _day_name(match.group(2))
    due_day = due_day or _day_name(day_hint)
    title = re.sub(r"\b(i'?ve got|i have|i got|remember|don'?t forget)\b", "",
                   text, flags=re.I)
    title = re.sub(r"\b(due|by|for|on)\s+(next\s+)?\w+day\b|\bdue tomorrow\b|"
                   r"\bdue today\b", "", title, flags=re.I).strip(" ,.!?")
    title = re.sub(r"^(a|an|the)\s+", "", title, flags=re.I) or "school work"
    entry = {"what": title[:80], "added": datetime.date.today().isoformat(),
             "done": False}
    if due_day:
        entry["due"] = _next_date(due_day).isoformat()
    data.setdefault("work", []).append(entry)
    _save(data)
    if due_day:
        return (f"Noted: {entry['what']}, due "
                f"{_speak_date(datetime.date.fromisoformat(entry['due']))}.")
    return f"Noted: {entry['what']}. No due date — say when it's due if you want one."


def _due(data: dict, text: str, index: str = "", count: str = "") -> str:
    work = [w for w in data.get("work", []) if not w.get("done")]
    # SEQTA's assessments sit alongside whatever he's told me himself —
    # marked, so he knows which came from school and which he added
    portal = _seqta()
    if portal:
        try:
            done = {w["what"].lower() for w in data.get("work", [])
                    if w.get("done")}
            for item in portal.data().get("due", []):
                if item["what"].lower() in done:
                    continue  # he's already told me it's finished
                label = (f"{item['what']} for {item['subject']}"
                         if item.get("subject") else item["what"])
                work.append({"what": label, "due": item["due"],
                             "from_seqta": True})
        except Exception:
            pass
    # "when's my next test" — ONE answer, from real data. Chat used to
    # invent these out of the timetable sitting in the conversation
    # ("your next test is Maths on Thursday at 9am"), which is the worst
    # kind of wrong: confident, specific, and completely made up.
    # "list the next three assessments" — a straight countdown, no horizon
    if count:
        stamp = datetime.date.today().isoformat()
        every = sorted((w for w in work if w.get("due")), key=lambda w: w["due"])
        upcoming = [w for w in every if w["due"] >= stamp]
        late = [w for w in every if w["due"] < stamp]
        try:
            wanted = max(1, min(10, int(count)))
        except ValueError:
            wanted = 3
        if not upcoming:
            return ("Nothing upcoming at all."
                    + (f" {len(late)} are overdue though." if late else ""))
        parts = []
        for item in upcoming[:wanted]:
            when = _speak_date(datetime.date.fromisoformat(item["due"]))
            parts.append(f"{item['what']} {when}")
        lead = (f"Your next {len(parts)}" if len(parts) > 1 else "Just one")
        answer = f"{lead}: " + ". ".join(parts) + "."
        if len(upcoming) > wanted:
            answer += f" {len(upcoming) - wanted} more after that."
        if late:
            answer += f" {len(late)} overdue as well."
        return answer

    if index != "":
        stamp = datetime.date.today().isoformat()
        every = sorted((w for w in work if w.get("due")), key=lambda w: w["due"])
        # SEQTA's "upcoming" list still carries things whose date has passed.
        # Calling one of those "next up" is worse than useless, so overdue
        # work is named as overdue and the countdown starts from today.
        dated = [w for w in every if w["due"] >= stamp]
        late = [w for w in every if w["due"] < stamp]
        if not dated and late:
            item = late[-1]
            when = _speak_date(datetime.date.fromisoformat(item["due"]))
            return (f"Nothing upcoming — but {item['what']} was due {when}"
                    + (f", and {len(late) - 1} more are overdue." if len(late) > 1
                       else "."))
        if not dated:
            extra = ("" if portal else
                     " I'm not connected to SEQTA, so I only know what you've "
                     "told me.")
            return f"Nothing with a due date on your list.{extra}"
        try:
            pick = int(index)
        except ValueError:
            pick = 0
        if pick >= len(dated):
            return (f"That's the lot — I've only got {len(dated)} coming up. "
                    f"The last is {dated[-1]['what']} "
                    f"{_speak_date(datetime.date.fromisoformat(dated[-1]['due']))}.")
        item = dated[pick]
        when = _speak_date(datetime.date.fromisoformat(item["due"]))
        lead = ("Next up" if pick == 0 else f"Number {pick + 1}")
        answer = f"{lead}: {item['what']}, due {when}."
        if pick == 0 and late:
            answer += (f" Worth knowing: {len(late)} already past their date, "
                       f"the oldest being {late[0]['what']}.")
        return answer

    if not work:
        return "Nothing on your list. You're all clear."
    today = datetime.date.today()
    horizon = 7 if "week" in text.lower() else 30
    soon = []
    for item in work:
        if not item.get("due"):
            continue
        days = (datetime.date.fromisoformat(item["due"]) - today).days
        if days <= horizon:
            soon.append((days, item))
    soon.sort(key=lambda pair: pair[0])
    undated = [w for w in work if not w.get("due")]
    if not soon and not undated:
        return "Nothing due in that stretch."
    parts = []
    for days, item in soon[:5]:
        when = _speak_date(datetime.date.fromisoformat(item["due"]))
        parts.append(f"{item['what']} {when}"
                     + (" — that's overdue" if days < 0 else ""))
    if undated:
        parts.append(f"{len(undated)} with no date: "
                     + ", ".join(w["what"] for w in undated[:3]))
    return "Due: " + ". ".join(parts) + "."


def _done(data: dict, text: str) -> str:
    work = [w for w in data.get("work", []) if not w.get("done")]
    if not work:
        return "There's nothing on your list to tick off."
    words = [w for w in re.findall(r"[a-z]{3,}", text.lower())
             if w not in ("ive", "finished", "done", "the", "and", "with",
                          "that", "handed", "submitted", "my")]
    hit = None
    for item in work:
        if any(w in item["what"].lower() for w in words):
            hit = item
            break
    hit = hit or (work[0] if len(work) == 1 else None)
    if not hit:
        return ("Which one? " + ", ".join(w["what"] for w in work[:4]) + ".")
    hit["done"] = True
    hit["finished"] = datetime.date.today().isoformat()
    _save(data)
    left = len([w for w in data.get("work", []) if not w.get("done")])
    return (f"Ticked off {hit['what']}. "
            + (f"{left} left." if left else "That's your list clear."))


def _study(data: dict, minutes: int) -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "timers", BASE / "skills" / "timers" / "skill.py")
    timers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(timers)
    timers.run({"action": "set", "when": f"{minutes} minutes",
                "label": "break time — five minutes off the screen"})
    session = data.setdefault("study", {})
    session["started"] = datetime.datetime.now().isoformat(timespec="seconds")
    session["minutes"] = minutes
    log = data.setdefault("study_log", [])
    log.append({"date": datetime.date.today().isoformat(), "minutes": minutes})
    data["study_log"] = log[-200:]
    _save(data)
    today = sum(s["minutes"] for s in data["study_log"]
                if s["date"] == datetime.date.today().isoformat())
    return (f"{minutes} minutes on the clock. I'll tell you when it's break "
            f"time. That's {today} minutes of study today.")


def run(args: dict) -> str:
    data = _load()
    action = str(args.get("action") or "").strip().lower()
    text = str(args.get("text") or "")
    day_hint = str(args.get("day") or "")

    if action in ("set_timetable", "settimetable"):
        return _set_timetable(data, text, day_hint)
    if action in ("add_work", "addwork", "add", "homework"):
        return _add_work(data, text, day_hint)
    if action in ("done", "finished", "tick"):
        return _done(data, text)
    if action in ("due", "work", "assignments", "homework_due"):
        return _due(data, text, str(args.get("index", "")),
                    str(args.get("count") or ""))
    if action in ("study", "study_session", "revise"):
        try:
            minutes = int(re.sub(r"\D", "", str(args.get("minutes") or "")) or 25)
        except ValueError:
            minutes = 25
        return _study(data, max(5, min(120, minutes)))
    if action in ("seqta", "connect", "sync", "refresh"):
        portal = _seqta()
        if not portal:
            return ("SEQTA isn't set up. Put SEQTA_URL, SEQTA_USER and "
                    "SEQTA_PASS into the .env file in the TARS folder — I "
                    "never see them, they stay on this PC — then say connect "
                    "to SEQTA again.")
        return portal.test()
    if action in ("study_stats", "how_much"):
        log = data.get("study_log", [])
        today = sum(s["minutes"] for s in log
                    if s["date"] == datetime.date.today().isoformat())
        week = sum(s["minutes"] for s in log[-40:])
        return f"{today} minutes of study today, {week} across recent sessions."
    # nothing here recognises what he's asking. Reciting "tell me your
    # timetable" at a question about a maths test is worse than admitting
    # it isn't mine — hand it back to the part of TARS that can think.
    if not action and not re.search(
            r"timetable|classes|lessons|subjects|periods?|what have i got|"
            r"school day|my day", text.lower()):
        return "__PASS__"
    return _timetable(data, day_hint, text, str(args.get("period") or ""))
