"""'TARS, remember that...' — writes a note into the Obsidian vault (vault/)."""
import datetime
import json
import re
from pathlib import Path

import requests

VAULT = Path(__file__).resolve().parents[2] / "vault"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model
MODEL = bg_model()

DESCRIPTION = ("Save a fact to TARS's permanent memory vault. E.g. 'remember that I like "
               "short answers in the morning', 'remember my wifi password is on the fridge'.")
ARGS = {"fact": "the fact to remember, in Jacob's words"}

FOLDERS = ("About Jacob", "Knowledge", "Projects")


def _classify(fact: str) -> dict:
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False, "format": "json",
            "messages": [{"role": "user", "content":
                f"Classify this memory for a personal assistant's vault: {fact!r}\n"
                f'Reply as JSON: {{"folder": "About Jacob" (facts/preferences about '
                f'Jacob) | "Knowledge" (facts about the world/things) | "Projects" '
                f'(ongoing work), "title": "<3-6 word note title>", '
                f'"tags": ["<one-word-tag>", ...max 3]}}'}],
            "options": {"temperature": 0}}, timeout=60)
        data = json.loads(r.json()["message"]["content"])
        if data.get("folder") not in FOLDERS:
            data["folder"] = "Knowledge"
        return data
    except Exception:
        return {"folder": "Knowledge", "title": fact[:40], "tags": []}


def run(args: dict) -> str:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return "Remember what, exactly?"
    meta = _classify(fact)
    title = re.sub(r'[<>:"/\\|?*]', "", meta.get("title") or fact[:40]).strip() or "Note"
    folder = VAULT / meta["folder"]
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    path = folder / f"{title}.md"
    tags = "".join(f"\n  - {t}" for t in meta.get("tags", []))
    if path.exists():  # append, don't clobber
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n- {fact} *({now:%Y-%m-%d})*\n")
    else:
        path.write_text(
            f"---\ncreated: {now:%Y-%m-%d}\ntags:{tags or ' []'}\n---\n\n"
            f"- {fact} *({now:%Y-%m-%d})*\n",
            encoding="utf-8",
        )

    journal = VAULT / "Journal"
    journal.mkdir(exist_ok=True)
    with open(journal / f"Journal {now:%Y-%m-%d}.md", "a", encoding="utf-8") as f:
        f.write(f"- {now:%H:%M} remembered [[{title}]]\n")
    return "Noted. It's in the vault."
