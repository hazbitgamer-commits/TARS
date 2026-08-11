"""Revision sheets: one page of actual study material for a real upcoming
test. Written from the topics SEQTA gives, saved as a file the owner can print,
read on his phone, or revise from before letting TARS quiz him on it."""
import datetime
import importlib.util
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
SHEETS = BASE / "workshop" / "revision"

DESCRIPTION = ("Write a REVISION SHEET (study notes / cheat sheet) for an "
               "upcoming test — 'make me a revision sheet for the maths "
               "test', 'write me a cheat sheet for physics', 'summarise "
               "what I need to know for the history test'. Saves a page of "
               "notes with the key ideas, formulas, worked examples and "
               "common mistakes, and can open it. NOT for being asked "
               "questions (study) and NOT for what's due (school).")
ARGS = {"subject": "the subject or test, e.g. 'maths', 'the physics test'",
        "action": "'make' (default) or 'open' to reopen the last one"}


def _study():
    spec = importlib.util.spec_from_file_location(
        "study_for_revision", BASE / "skills" / "study" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _open(path: Path) -> None:
    from platform_caps import open_file

    if not open_file(path):  # cross-platform: startfile / open / xdg-open
        import webbrowser

        webbrowser.open(path.as_uri())


def _write_sheet(item: dict, topics: str) -> str:
    known = ("The test title lists exactly these topics: " + topics
             if "," in topics else
             "All the school gave is the assessment name: " + topics)
    prompt = (
        "Write a one-page revision sheet for a 15-year-old Australian "
        f"student (Year 10) sitting: \"{item['what']}\""
        + (f" in {item['subject']}" if item.get("subject") else "") + ".\n"
        f"{known}.\n\n"
        "Structure it as markdown:\n"
        "- A heading per topic, in the order listed.\n"
        "- Under each: the key idea in one or two sentences, then the rule "
        "or formula, then ONE short worked example with the working shown.\n"
        "- Finish with '## Easy marks to lose' — three specific mistakes "
        "students actually make on this material.\n\n"
        "Rules: no waffle, no introduction, no 'good luck'. If you are not "
        "sure what a topic covers at Year 10 level, say so under that "
        "heading rather than inventing content. Plain markdown only.")
    r = requests.post(OLLAMA_URL, json={
        "model": MODEL, "stream": False, "think": False,
        "messages": [{"role": "user", "content": prompt}]}, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def run(args: dict) -> str:
    action = str(args.get("action") or "make").strip().lower()
    SHEETS.mkdir(parents=True, exist_ok=True)

    study = _study()
    if action in ("study", "ensure"):
        # "Help me study for maths" means READ then be tested — so hand him
        # the notes if he hasn't got them, and go straight to the quiz if he
        # has. the owner asked for the sheet and got questions fired at him.
        item = study._pick(str(args.get("subject") or ""))
        if item:
            slug = re.sub(r"[^a-z0-9]+", "-",
                          item["what"].lower())[:50].strip("-")
            if any(SHEETS.glob(f"{slug}-*.md")):
                return "__QUIZ__"  # he's already got the notes for this one
        args = {"action": "make", "subject": args.get("subject", "")}
        action = "make"

    if action in ("open", "reopen", "show"):
        sheets = sorted(SHEETS.glob("*.md"), key=lambda p: p.stat().st_mtime)
        if not sheets:
            return "I haven't written you a revision sheet yet."
        _open(sheets[-1])
        return f"Opening {sheets[-1].stem.replace('-', ' ')}."

    subject = str(args.get("subject") or "").strip()
    item = study._pick(subject)
    if not item:
        upcoming = study._assessments()
        if not upcoming:
            return ("Nothing upcoming to revise for. Connect SEQTA or tell me "
                    "what you've got on.")
        return ("Which one? " + ", ".join(a["what"][:45]
                                          for a in upcoming[:3]) + ".")
    topics = study._topics(item)
    try:
        body = _write_sheet(item, topics)
    except Exception:
        return "My writing brain isn't answering. Try again in a moment."
    if len(body) < 120:
        return "That came out empty — try asking again."

    stamp = datetime.date.today().isoformat()
    slug = re.sub(r"[^a-z0-9]+", "-", item["what"].lower())[:50].strip("-")
    path = SHEETS / f"{slug}-{stamp}.md"
    header = (f"# {item['what']}\n\n_{item.get('subject', '')}"
              + (f" — due {item['due']}" if item.get("due") else "")
              + f". Written {stamp} from the topics your school listed._\n\n")
    try:
        path.write_text(header + body, encoding="utf-8")
    except OSError:
        return "I wrote it but couldn't save the file."
    _open(path)

    headings = [l.lstrip("# ").strip() for l in body.splitlines()
                if l.startswith("#") and len(l.strip()) > 3][:4]
    covered = (" It covers " + ", ".join(headings) + "." if headings else "")
    warn = ("" if "," in topics else
            " Your school didn't say what that one covers, so it's general "
            "for the subject — worth checking against your notes.")
    return (f"Revision sheet for {item['what'][:60]} is on screen.{covered}"
            f"{warn} Read it, then say quiz me and I'll test you on it.")
