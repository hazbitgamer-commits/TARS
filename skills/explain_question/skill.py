"""'What's this question actually asking?' — TARS reads a question off the
screen and explains what it wants, what it's testing, and how to start.

Deliberately does NOT hand over the final answer: the point is to get the owner
unstuck on his own homework, not to do it for him. He can ask for the
answer outright and get it, but he has to ask.
"""
import importlib.util
import sys
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model

MODEL = bg_model()

DESCRIPTION = ("Read a QUESTION off the screen and explain what it's asking "
               "— 'what's this question asking', 'explain this question', "
               "'I don't get this question', 'help me with this one', "
               "'what do I do here'. Explains the task and the first step "
               "WITHOUT giving the final answer, unless the owner asks for the "
               "answer outright. NOT for describing the screen generally "
               "(look_at_screen) and NOT for quizzing him (study).")
ARGS = {"monitor": "'left' for the left screen, otherwise the main one",
        "answer": "'true' only if the owner explicitly asked for the answer"}


def _eyes():
    spec = importlib.util.spec_from_file_location(
        "look_for_question", BASE / "skills" / "look_at_screen" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_screen(which: str) -> str:
    """The vision model's job is only to TRANSCRIBE — working out what the
    question means is done by the text model, which is better at it."""
    eyes = _eyes()
    return eyes.run({
        "monitor": which,
        "question": ("Transcribe the question or task visible on this screen, "
                     "word for word, including any numbers, equations, "
                     "options or instructions. If there are several, "
                     "transcribe the one that is most prominent or nearest "
                     "the centre. Reply with the text only — no commentary. "
                     "If there is no question on screen, reply exactly: "
                     "NO QUESTION")})


def run(args: dict) -> str:
    which = str(args.get("monitor") or "main").strip().lower()
    give_answer = str(args.get("answer") or "").strip().lower() in (
        "true", "yes", "1")

    seen = _read_screen(which)
    if not seen or "NO QUESTION" in seen.upper():
        return ("I can't see a question on your screen. Bring it up and ask "
                "me again.")
    if len(seen) < 12:
        return "I could see something but couldn't read it clearly enough."

    if give_answer:
        rule = ("Give the answer, then show the working in two or three "
                "short steps so he can follow it.")
    else:
        rule = ("Do NOT give the final answer — he's doing his own homework. "
                "Say what it's asking for in plain words, what topic it's "
                "testing, and the FIRST step he should take. Stop there.")
    prompt = (
        "This question is on a 15-year-old Australian student's screen:\n\n"
        f"\"{seen[:1200]}\"\n\n"
        f"{rule}\n"
        "You are speaking out loud, so: no markdown, no lists, no symbols "
        "he can't hear — say 'squared' not '^2'. Three or four sentences at "
        "most. If the transcription is garbled or isn't really a question, "
        "say so plainly instead of guessing what it meant.")
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()[:900]
    except Exception:
        return "I read the question but my explaining brain isn't answering."
