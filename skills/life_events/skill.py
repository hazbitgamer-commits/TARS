"""Remembers dated personal milestones (first day of school, first job, moving
house, etc.) and answers questions about them later. Separate from the general
'remember'/'recall' vault skills because these facts have a specific shape —
an event, a date, and usually a place — so they get stored structured and
answered precisely (with the date) instead of via fuzzy note search.
"""
import json
import os
import re

from dateutil import parser as dateparser

DESCRIPTION = ("Remember or recall a dated personal milestone/life event, e.g. "
               "first day of school, a graduation, when Jacob moved house, his "
               "first day at a job. E.g. 'my first day at primary school was 1st "
               "of February 2016 at Orbin Grove Primary School' to store one, or "
               "'when was my first day of school' / 'what school did I start at' "
               "to recall it. NOT for general facts or preferences (that's the "
               "remember/recall skills) — this is specifically for life events "
               "with a date attached.")
ARGS = {"text": ("the full sentence — either the milestone to remember (include "
                  "the date and any names/places), or a question asking about a "
                  "previously stored milestone")}

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
_STORE_FILE = os.path.join(_SKILL_DIR, "events.json")

_QUESTION_WORDS = ("when", "what", "where", "who", "which", "how", "did", "do i",
                    "was my", "is my")
_STOPWORDS = {"when", "did", "i", "the", "a", "an", "about", "what", "do", "you",
              "remember", "me", "my", "ever", "first", "was", "is", "it", "that",
              "we", "of", "in", "on", "to", "and", "at", "went"}


def _load():
    if not os.path.exists(_STORE_FILE):
        return []
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(events):
    with open(_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)


def _extract_date(text: str):
    """Try to pull a date out of the sentence; return ISO string or None."""
    # Look for a chunk like "1st of February 2016" or "February 1st 2016" or "2016-02-01"
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.I)
    try:
        dt = dateparser.parse(cleaned, fuzzy=True, default=None)
        if dt:
            return dt.date().isoformat()
    except (ValueError, OverflowError):
        pass
    return None


def _is_question(text: str) -> bool:
    t = text.strip().lower()
    if t.endswith("?"):
        return True
    return any(t.startswith(w) for w in _QUESTION_WORDS)


def _pretty_date(iso: str) -> str:
    dt = dateparser.parse(iso)
    day = dt.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"the {day}{suffix} of {dt.strftime('%B %Y')}"


def run(args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "What's the event, exactly?"

    if _is_question(text):
        events = _load()
        if not events:
            return "I don't have any milestones stored yet. Tell me one and I'll remember it."
        words = {w for w in re.findall(r"[a-z']+", text.lower()) if w not in _STOPWORDS}
        best, best_score = None, 0
        for ev in events:
            haystack = ev["text"].lower()
            score = sum(1 for w in words if w in haystack)
            if score > best_score:
                best, best_score = ev, score
        if not best:
            best = events[-1]  # fall back to most recent
        if best.get("date"):
            return f"That was {_pretty_date(best['date'])}. {best['text']}"
        return best["text"]

    date_iso = _extract_date(text)
    events = _load()
    events.append({"text": text, "date": date_iso})
    _save(events)
    if date_iso:
        return f"Got it, I'll remember that — {_pretty_date(date_iso)}."
    return "Got it, I'll remember that."
