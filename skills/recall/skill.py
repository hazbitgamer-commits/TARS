"""'What do you know about X?' — searches the vault before answering."""
import json
from pathlib import Path

import requests

VAULT = Path(__file__).resolve().parents[2] / "vault"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()

DESCRIPTION = ("Answer from TARS's permanent memory vault. E.g. 'what do you know about "
               "me', 'do you remember what I said about my monitors'.")
ARGS = {"topic": "what Jacob wants recalled"}


STOPWORDS = {"when", "did", "i", "the", "a", "an", "about", "what", "do", "you",
             "remember", "me", "my", "ask", "asked", "say", "said", "know",
             "was", "is", "it", "that", "we", "of", "in", "on", "to", "and"}


def run(args: dict) -> str:
    topic = (args.get("topic") or "").strip().lower()
    if not topic:
        return "Recall what, exactly?"
    words = {w for w in topic.split() if w not in STOPWORDS} or set(topic.split())

    scored = []
    for note in VAULT.rglob("*.md"):
        try:
            content = note.read_text(encoding="utf-8")
        except OSError:
            continue
        haystack = (note.stem + " " + content).lower()
        score = sum(1 for w in words if w in haystack)
        if not score:
            continue
        if len(content) > 800:  # long note (e.g. a conversation): pull hit lines
            hits = [l for l in content.splitlines()
                    if any(w in l.lower() for w in words)][:12]
            snippet = "\n".join(hits) if hits else content[:600]
        else:
            snippet = content[:600]
        scored.append((score, note.stem, snippet))
    scored.sort(reverse=True)

    if not scored:
        return "Nothing in my memory about that yet. Tell me and I'll remember it."

    notes = "\n\n".join(f"## {name}\n{body}" for _, name, body in scored[:3])
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content":
                f"Jacob asked his assistant TARS: {topic!r}. These notes are from "
                f"TARS's memory vault:\n{notes}\n\nAnswer in one to three short "
                f"spoken sentences using only these notes. Plain text, no markdown."}],
            "options": {"num_predict": 140}}, timeout=90)
        return r.json()["message"]["content"].strip()
    except Exception:
        return f"I have notes on {scored[0][1]}, but my summarizer choked. Check the vault."
