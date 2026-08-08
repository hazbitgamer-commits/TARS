"""TARS's agent staff — background specialists that work the brain.

Scout     — morning briefing: weather, email, calendar, timers → spoken + journaled
Archivist — files each conversation into topic notes (lives in topics.py, reports here)
Librarian — housekeeping: finds near-duplicate memories and cross-links them

Every touch is logged to brain_activity.jsonl with the agent's name as source,
so the 3D brain page can show them flying to the neurons they read/write.
"""
import datetime
import json
import os
import threading
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
STATE = BASE / "agents_state.json"
ACTIVITY = BASE / "brain_activity.jsonl"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()

AGENTS = {
    "Scout": "gathers the morning briefing: weather, unread email, calendar, timers",
    "Archivist": "files every conversation into topic memories",
    "Librarian": "housekeeps the brain: links near-duplicate memories together",
    "Curator": "audits quarantined memories against the real transcripts — "
               "restores the genuine, rejects the fabricated",
    "Kipp": "self-improvement engineer: re-reads the day's transcripts for "
            "friction while TARS idles, then upgrades TARS's own code",
}


def log_touch(agent: str, names: list[str], strength: float = 0.9) -> None:
    with open(ACTIVITY, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "source": agent,
                            "fired": [{"name": n, "strength": strength}
                                      for n in names]}) + "\n")
    _mark(f"{agent.lower()}_ran")


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _mark(key: str) -> None:
    s = _state()
    s[key] = datetime.datetime.now().isoformat(timespec="seconds")
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


# ---------------- Scout ----------------
def run_scout(speak: bool = True) -> str:
    from skills_engine import SkillBox

    sb = SkillBox(BASE)
    parts = []
    for label, skill, args in (
        ("Weather", "weather", {"when": "now"}),
        ("Email", "email", {"action": "unread"}),
        ("Calendar", "calendar", {"action": "agenda", "when": "today"}),
        ("Timers", "timers", {"action": "list"}),
    ):
        try:
            parts.append(f"{label}: {sb.run(skill, args)}")
        except Exception:
            pass
    raw = "\n".join(parts)
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content":
                "You are Scout, TARS's briefing agent. Compress this into a "
                "morning briefing for Jacob — three or four short spoken "
                "sentences, most important first, plain text, no markdown:\n"
                + raw}],
            "options": {"num_predict": 180}}, timeout=120)
        brief = r.json()["message"]["content"].strip()
    except Exception:
        brief = raw[:400]

    now = datetime.datetime.now()
    journal = BASE / "vault" / "Journal"
    journal.mkdir(parents=True, exist_ok=True)
    with open(journal / f"Journal {now:%Y-%m-%d}.md", "a", encoding="utf-8") as f:
        f.write(f"- {now:%H:%M} Scout's briefing: {brief}\n")
    try:
        import neuro

        fired = neuro.get().stimulate(brief, source="Scout")
        log_touch("Scout", [x["name"] for x in fired] or ["Jacob basics"])
    except Exception:
        pass
    _mark("scout_ran")
    if speak:
        import announce

        announce.post(f"Morning briefing. {brief}")
    return brief


# ---------------- Librarian ----------------
def run_librarian() -> str:
    import numpy as np

    import neuro

    nb = neuro.get()
    nb.reindex()
    names = sorted(nb.neurons, key=lambda n: nb.neurons[n]["row"])
    vecs = nb.vectors
    added, touched = [], []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if nb.neurons[a]["folder"] != "Knowledge" or nb.neurons[b]["folder"] != "Knowledge":
                continue
            sim = float(vecs[nb.neurons[a]["row"]] @ vecs[nb.neurons[b]["row"]])
            if sim < 0.85:
                continue
            if b in nb._links_of(a) or a in nb._links_of(b):
                continue
            today = datetime.date.today().isoformat()
            with open(nb.neurons[a]["path"], "a", encoding="utf-8") as f:
                f.write(f"\n- Librarian: closely related to [[{b}]] *({today})*\n")
            added.append(f"{a} ↔ {b}")
            touched += [a, b]
    _mark("librarian_ran")
    if touched:
        log_touch("Librarian", list(dict.fromkeys(touched)))
    if not added:
        return "Librarian's done — the shelves are already tidy, nothing to cross-link."
    return ("Librarian's done — cross-linked " + "; ".join(added[:4]) +
            (f" and {len(added) - 4} more" if len(added) > 4 else "") + ".")


# ---------------- Curator ----------------
def run_curator(speak: bool = True) -> str:
    """Sort vault_quarantine: a note is genuine only if its content is
    grounded in what Jacob actually said (full transcript corpus)."""
    import re
    import shutil

    from brain import Brain

    quarantine = BASE / "vault_quarantine"
    notes = sorted(quarantine.glob("*.md")) if quarantine.exists() else []
    if not notes:
        return "Curator's done — quarantine is empty."

    corpus = []
    for conv in (BASE / "vault" / "Conversations").glob("*.md"):
        for line in conv.read_text(encoding="utf-8").splitlines():
            m = re.match(r"- \*\*\d\d:\d\d\*\* Jacob: (.+)", line)
            if m:
                corpus.append(m.group(1))
    corpus_low = " ".join(corpus).lower()

    rejected_dir = quarantine / "rejected"
    rejected_dir.mkdir(exist_ok=True)
    restored, rejected = [], []
    for note in notes:
        facts = [re.sub(r"\s*\*\([^)]*\)\*\s*$", "", l.strip()[2:])
                 for l in note.read_text(encoding="utf-8").splitlines()
                 if l.strip().startswith("- ")]
        if any(Brain._grounded(f, corpus_low) for f in facts if f):
            shutil.move(str(note), str(BASE / "vault" / "About Jacob" / note.name))
            restored.append(note.stem)
        else:
            shutil.move(str(note), str(rejected_dir / note.name))
            rejected.append(note.stem)

    _mark("curator_ran")
    if restored:
        log_touch("Curator", restored[:10])
    now = datetime.datetime.now()
    journal = BASE / "vault" / "Journal"
    journal.mkdir(parents=True, exist_ok=True)
    with open(journal / f"Journal {now:%Y-%m-%d}.md", "a", encoding="utf-8") as f:
        f.write(f"- {now:%H:%M} Curator: restored {len(restored)}, "
                f"rejected {len(rejected)} fabricated\n")
    verdict = (f"Curator's done — {len(restored)} memories checked out as real "
               f"and went back in the vault; {len(rejected)} were fabricated "
               f"and are binned in quarantine slash rejected.")
    if speak:
        import announce

        announce.post(verdict)
    return verdict


# ---------------- scheduler (called ~once a second from the standby loop) ----------------
def tick() -> None:
    now = datetime.datetime.now()
    s = _state()
    # Scout's AUTOMATIC morning briefing removed at Jacob's request
    # (2026-07-21) — "give me my morning briefing" still works on demand.

    # Curator sweeps whenever quarantine has contents, at most once a day
    quarantine = BASE / "vault_quarantine"
    if quarantine.exists() and any(quarantine.glob("*.md")):
        if not s.get("curator_ran", "").startswith(now.date().isoformat()):
            _mark("curator_ran")
            threading.Thread(target=run_curator, daemon=True).start()
