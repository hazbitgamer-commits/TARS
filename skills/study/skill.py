"""Study mode: TARS quizzes the owner on a real upcoming assessment.

Questions come from what SEQTA actually says the assessment covers — the
titles carry the topics ("Test 3 (parallel, perpendicular, quadratic,
parabola, factorisation, circles)") — so this is revision for the test he
is actually sitting, not generic worksheet filler. Wrong answers are
remembered and asked again, because the ones you get wrong are the whole
point of revising.
"""
import datetime
import json
import re
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model

MODEL = bg_model()
SESSION = BASE / "study_session.json"
PROGRESS = BASE / "study_progress.json"

DESCRIPTION = ("STUDY MODE — quiz the owner on a real upcoming test or "
               "assessment. 'Help me study for physics', 'quiz me on maths', "
               "'test me on the history topic test', 'how am I going with "
               "revision'. Asks questions one at a time, marks the answers, "
               "and comes back to whatever he keeps getting wrong. NOT for "
               "listing what's due (school) and NOT for a plain study timer "
               "(school study).")
ARGS = {"action": "'start', 'answer', 'skip', 'stop', or 'progress'",
        "subject": "for start — the subject or assessment, e.g. 'physics'",
        "text": "for answer — what the owner said"}


# what the owner calls a subject vs what the school calls it
ALIASES = {"maths": "math", "math": "math", "phys": "physics",
           "sci": "science", "hass": "humanities", "history": "humanities",
           "geo": "humanities", "english": "english", "pe": "physical",
           "footy": "football", "re": "christian", "religion": "christian"}


def _load(path: Path, fallback: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(fallback)


def _save(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def _ask_model(prompt: str, want_json: bool = False, timeout: int = 120):
    body = {"model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": prompt}]}
    if want_json:
        body["format"] = "json"
    r = requests.post(OLLAMA_URL, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def _assessments() -> list[dict]:
    """Everything upcoming, SEQTA plus whatever he's typed in himself."""
    out = []
    try:
        import seqta

        for item in seqta.cached().get("due", []):
            out.append({"what": item.get("what", ""),
                        "subject": item.get("subject", ""),
                        "due": item.get("due", "")})
    except Exception:
        pass
    for work in _load(BASE / "school.json", {}).get("work", []):
        if not work.get("done"):
            out.append({"what": work.get("what", ""), "subject": "",
                        "due": work.get("due", "")})
    today = datetime.date.today().isoformat()
    out = [a for a in out if a["what"] and a.get("due", "") >= today]
    out.sort(key=lambda a: a["due"])
    return out


def _pick(subject: str) -> dict | None:
    items = _assessments()
    if not items:
        return None
    words = [w for w in re.findall(r"[a-z]{3,}", subject.lower())
             if w not in ("the", "for", "test", "one", "help", "study",
                          "quiz", "assessment", "revision", "revise", "next",
                          "exam", "tomorrow", "with", "and", "our")]
    # "maths" must find "Mathematics (Advanced)", and "phys" find "Physics".
    # No truncated stem here on purpose: a 4-letter stem crushes "physics"
    # and "physical" (PE) down to the same "phys" and picks whichever
    # subject happens to sort first, quizzing him on the wrong one.
    words = [ALIASES.get(w, w) for w in words]
    for item in items:
        blob = (item["what"] + " " + item["subject"]).lower()
        parts = re.findall(r"[a-z]{3,}", blob)
        for word in words:
            if any(p.startswith(word) for p in parts):
                return item
    return items[0] if not words else None


def _topics(item: dict) -> str:
    """The bracketed list in a SEQTA title is a topic list, and it's the
    best revision material available — use it verbatim when it's there."""
    inside = re.findall(r"\(([^)]{8,})\)", item["what"])
    for chunk in inside:
        if "," in chunk or len(chunk.split()) > 2:
            if "take-home" in chunk.lower():
                continue
            return chunk
    # no topic list in the title — the assessment name plus the subject is
    # all SEQTA gives, so say so rather than quizzing him on "Science"
    title = re.sub(r"^(task|test|assessment)\s*\w*\s*[-:]\s*", "",
                   item["what"], flags=re.I).strip()
    return f"{title}" + (f" ({item['subject']})" if item["subject"] else "")


def _questions(item: dict, weak: list[str]) -> list[dict]:
    topics = _topics(item)
    revisit = (f"\nHe has previously got these wrong, so include one on each: "
               f"{'; '.join(weak[:3])}" if weak else "")
    prompt = (
        "You are setting short revision questions for a 15-year-old "
        f"Australian student sitting this assessment: \"{item['what']}\""
        + (f" in {item['subject']}" if item["subject"] else "")
        + f".\nThe topics it covers: {topics}{revisit}\n\n"
        "Write SIX questions that test understanding of those topics, "
        "getting harder as they go. They will be READ ALOUD and answered "
        "out loud, so: no diagrams, no 'refer to the figure', nothing "
        "needing more than about 20 words to answer, and no multiple "
        "choice. Give the expected answer for each, briefly.\n"
        'Reply with JSON only: {"questions": [{"q": "...", "a": "..."}]}')
    try:
        raw = _ask_model(prompt, want_json=True, timeout=180)
        rows = json.loads(raw).get("questions", [])
    except Exception:
        return []
    out = []
    for row in rows:
        if isinstance(row, dict) and row.get("q"):
            out.append({"q": str(row["q"])[:300],
                        "a": str(row.get("a", ""))[:300]})
    return out[:6]


def _mark(question: dict, said: str) -> tuple[str, str]:
    """(verdict, one-line feedback). Marking is the model's job, but the
    verdict is forced into three words so the code can count them."""
    prompt = (
        "You are marking a spoken answer from a 15-year-old. Be fair: "
        "spoken answers are short and informal, and the words don't have "
        "to match — the understanding does.\n"
        f"QUESTION: {question['q']}\nEXPECTED: {question['a']}\n"
        f"HE SAID: {said}\n\n"
        'Reply with JSON only: {"verdict": "right" or "close" or "wrong", '
        '"feedback": "one short sentence spoken TO him — say \\"you\\", '
        'never \\"he\\". If he is wrong or close, say what the right answer '
        'is. If he is right, add nothing or one word of detail."}')
    try:
        data = json.loads(_ask_model(prompt, want_json=True, timeout=90))
        verdict = str(data.get("verdict", "")).lower().strip()
        if verdict not in ("right", "close", "wrong"):
            verdict = "close"
        note = str(data.get("feedback", ""))[:300].strip()
        return verdict, (note[0].upper() + note[1:] if note else note)
    except Exception:
        return "close", f"The expected answer was: {question['a']}"


def _remember(topic: str, question: str, got_it: bool, subject: str = "") -> None:
    data = _load(PROGRESS, {"weak": [], "history": []})
    weak = data.get("weak", [])
    if got_it:
        weak = [w for w in weak if w.get("q") != question]
    elif not any(w.get("q") == question for w in weak):
        weak.append({"q": question, "topic": topic, "subject": subject,
                     "when": datetime.date.today().isoformat()})
    data["weak"] = weak[-40:]
    data.setdefault("history", []).append(
        {"day": datetime.date.today().isoformat(), "topic": topic,
         "right": got_it})
    data["history"] = data["history"][-400:]
    _save(PROGRESS, data)


def active() -> bool:
    session = _load(SESSION, {})
    if not session.get("questions"):
        return False
    started = session.get("started", 0)
    return (datetime.datetime.now().timestamp() - started) < 7200


def _start(subject: str) -> str:
    item = _pick(subject)
    if not item:
        if not _assessments():
            return ("I've got nothing upcoming to revise for. Connect SEQTA "
                    "or tell me what you've got and I'll quiz you on it.")
        return (f"I can't tell which one you mean. Coming up: "
                + ", ".join(a["what"][:45] for a in _assessments()[:3]) + ".")
    # only revisit misses from THIS subject — a physics quiz asked him
    # "what is the condition for two lines to be parallel" because the
    # maths session's weak list was pulled in wholesale
    mine = (item.get("subject") or item.get("what", "")).lower()
    weak = [w["q"] for w in _load(PROGRESS, {}).get("weak", [])
            if not w.get("subject") or w["subject"].lower() == mine]
    questions = _questions(item, weak)
    if not questions:
        return "My question-writing brain isn't answering. Try again in a moment."
    _save(SESSION, {"item": item, "questions": questions, "at": 0,
                    "right": 0, "close": 0, "wrong": 0,
                    "started": datetime.datetime.now().timestamp()})
    due = item.get("due", "")
    when = ""
    if due:
        days = (datetime.date.fromisoformat(due) - datetime.date.today()).days
        when = (" — that's tomorrow" if days == 1 else
                " — that's today" if days == 0 else f" — {days} days away")
    return (f"Right, {item['what'][:70]}{when}. Six questions, say stop "
            f"whenever. First one: {questions[0]['q']}")


def _answer(said: str) -> str:
    session = _load(SESSION, {})
    questions = session.get("questions") or []
    at = session.get("at", 0)
    if not questions or at >= len(questions):
        return "No question on the table. Say help me study for physics to start."
    question = questions[at]
    verdict, feedback = _mark(question, said)
    session[verdict] = session.get(verdict, 0) + 1
    item = session.get("item", {"what": "", "subject": ""})
    _remember(_topics(item), question["q"], verdict == "right",
              subject=item.get("subject") or item.get("what", ""))
    lead = {"right": "Yep.", "close": "Close.", "wrong": "Not quite."}[verdict]
    session["at"] = at + 1
    _save(SESSION, session)
    if session["at"] >= len(questions):
        return f"{lead} {feedback} " + _finish(session)
    nxt = questions[session["at"]]["q"]
    return f"{lead} {feedback} Next: {nxt}"


def _finish(session: dict, early: bool = False) -> str:
    right = session.get("right", 0)
    close = session.get("close", 0)
    wrong = session.get("wrong", 0)
    total = right + close + wrong
    _save(SESSION, {})
    if not total:
        return "Stopped there."
    body = (f"Stopping there — {right} out of {total} solid" if early
            else f"That's the lot — {right} out of {total} solid")
    if close:
        body += f", {close} nearly"
    if wrong:
        weak = _load(PROGRESS, {}).get("weak", [])
        body += f", {wrong} to go back over"
        if weak:
            body += f". I'll ask you those again next time"
    return body + "."


def run(args: dict) -> str:
    action = str(args.get("action") or "start").strip().lower()
    if action == "answer":
        return _answer(str(args.get("text") or ""))
    if action in ("skip", "next"):
        session = _load(SESSION, {})
        if not session.get("questions"):
            return "Nothing to skip."
        session["at"] = session.get("at", 0) + 1
        session["wrong"] = session.get("wrong", 0) + 1
        _save(SESSION, session)
        if session["at"] >= len(session["questions"]):
            return _finish(session)
        return f"Fair enough. Next: {session['questions'][session['at']]['q']}"
    if action in ("stop", "quit", "end"):
        return _finish(_load(SESSION, {}), early=True)
    if action == "progress":
        data = _load(PROGRESS, {})
        history = data.get("history", [])
        if not history:
            return "You've not done any revision with me yet."
        today = datetime.date.today().isoformat()
        todays = [h for h in history if h["day"] == today]
        right = len([h for h in history if h.get("right")])
        weak = data.get("weak", [])
        line = (f"{right} out of {len(history)} right overall"
                + (f", {len(todays)} questions today" if todays else ""))
        if weak:
            line += f". Still shaky on {len(weak)}: {weak[0]['q'][:80]}"
        return line + "."
    return _start(str(args.get("subject") or args.get("text") or ""))
