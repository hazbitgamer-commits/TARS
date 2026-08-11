"""Topic digestion: after each conversation, distill what was discussed into
per-topic notes in vault/Knowledge, wikilinked to each other and to the raw
Conversation transcript — so the Obsidian graph grows around topics."""
import json
import re
from pathlib import Path

import requests

BASE = Path(__file__).parent
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()


def _clean(title: str) -> str:
    return re.sub(r'[<>:"/\\|?*\[\]#^]', "", title).strip()[:60]


def _note_for(title: str) -> Path | None:
    knowledge = BASE / "vault" / "Knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    safe = _clean(title)
    if not safe:
        return None
    for existing in knowledge.glob("*.md"):
        if existing.stem.lower() == safe.lower():
            return existing
    return knowledge / f"{safe}.md"


def _extract(lines: list[str], day: str) -> list[dict]:
    transcript = "\n".join(lines)[-6000:]
    existing = sorted(p.stem for p in (BASE / "vault" / "Knowledge").glob("*.md"))[:40]
    r = requests.post(OLLAMA_URL, json={
        "model": MODEL, "stream": False, "think": False, "format": "json",
        "messages": [{"role": "user", "content":
            f"Part of a conversation between the owner and his assistant TARS on {day}:\n"
            f"{transcript}\n\n"
            f"EXISTING topic notes: {json.dumps(existing)}\n"
            "If the conversation fits an existing topic, use its EXACT title "
            "instead of inventing a similar new one.\n"
            "Extract up to 3 real TOPICS discussed — things with substance "
            "(subjects, plans, problems, interests). SKIP greetings, small talk, "
            "routine commands (volume, screenshots, timers), and sessions of "
            "OPERATING OR UPGRADING TARS ITSELF (testing its camera or brain "
            "page, teaching it skills, GitHub uploads, memory cleanup) — those "
            "are work chatter, not knowledge worth keeping. Reply JSON:\n"
            '{"topics": [{"title": "<2-4 word noun phrase>", '
            '"tags": ["<one-word>", ...], '
            '"summary": "<one sentence: what was discussed or decided>", '
            '"related": ["<another topic title if clearly connected>", ...]}]}\n'
            'Nothing substantial? {"topics": []}'}],
        "options": {"temperature": 0.2}}, timeout=120)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"]).get("topics", [])[:3]


def digest(lines: list[str], day: str) -> list[str]:
    """Returns the topic note names it wrote (for tests/logging)."""
    try:
        topics = _extract(lines, day)
    except Exception:
        return []
    written = []
    for t in topics:
        title = _clean(str(t.get("title", "")))
        summary = str(t.get("summary", "")).strip()
        if not title or not summary:
            continue
        note = _note_for(title)
        if note is None:
            continue
        related = [_clean(r) for r in t.get("related", [])
                   if r and _clean(r).lower() != title.lower()]
        rel_txt = (" Related: " + ", ".join(f"[[{r}]]" for r in related)
                   if related else "")
        if not note.exists():
            tags = "".join(f"\n  - {re.sub(r'[^a-z0-9-]', '', str(x).lower())}"
                           for x in t.get("tags", [])[:3])
            note.write_text(f"---\ncreated: {day}\ntags:{tags or ' []'}\n---\n\n",
                            encoding="utf-8")
        with open(note, "a", encoding="utf-8") as f:
            f.write(f"- {summary} *({day})* — from [[Conversation {day}]].{rel_txt}\n")
        written.append(note.stem)

    if written:
        conv = BASE / "vault" / "Conversations" / f"Conversation {day}.md"
        if conv.exists():
            with open(conv, "a", encoding="utf-8") as f:
                f.write("\n> Topics: " + ", ".join(f"[[{w}]]" for w in written) + "\n")
        try:
            import agents

            agents.log_touch("Archivist", written)
        except Exception:
            pass
    return written
