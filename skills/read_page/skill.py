"""Summarize whatever's on screen — instantly, by READING the page's text
through the accessibility tree (same trick as the fast clicker), not by
staring at pixels with the slow vision model."""
import importlib.util
import json
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen2.5:7b"

DESCRIPTION = ("READ and summarize the page/article/document on screen — "
               "'summarize this article', 'what does this page say', 'give "
               "me the short version of this'. Reads the text directly "
               "(fast). NOT for describing images or video (that's "
               "look_at_screen) and NOT for clicking anything.")
ARGS = {"question": "optional — a specific question about the page instead "
                     "of a general summary"}


def _cs():
    spec = importlib.util.spec_from_file_location(
        "cs", BASE / "skills" / "click_screen" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _page_text() -> str:
    import time as _t

    import uiautomation as auto

    cs = _cs()
    win = cs._target_window(auto)
    if (win.ClassName or "").startswith("Chrome_WidgetWin"):
        try:  # knock: Chromium publishes page text only once poked
            doc = win.DocumentControl(searchDepth=20)
            if doc.Exists(2, 0.2):
                doc.GetChildren()
                _t.sleep(0.6)
        except Exception:
            pass
    chunks, state = [], {"count": 0, "chars": 0}

    def walk(c, depth=0):
        if depth > 28 or state["count"] > 4000 or state["chars"] > 7000:
            return
        for child in c.GetChildren():
            state["count"] += 1
            try:
                if child.ControlTypeName in ("TextControl", "DocumentControl"):
                    name = (child.Name or "").strip()
                    if len(name) > 25 and not child.IsOffscreen:
                        chunks.append(name)
                        state["chars"] += len(name)
            except Exception:
                pass
            walk(child, depth + 1)

    walk(win)
    # de-dupe (parents repeat children's text) keeping order
    seen, out = set(), []
    for c in chunks:
        if c[:60] not in seen:
            seen.add(c[:60])
            out.append(c)
    return "\n".join(out)[:7000]


def run(args: dict) -> str:
    question = str(args.get("question") or "").strip()
    try:
        text = _page_text()
    except Exception:
        return "I couldn't read that window's text."
    if len(text) < 120:
        return ("There's barely any readable text on this screen — if it's "
                "a video or image, ask me to look at the screen instead.")
    ask = (f"Answer this question about the page: {question!r}" if question
           else "Give a SPOKEN three-to-four sentence summary of this page")
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "keep_alive": "2h",
            "messages": [{"role": "user", "content":
                f"Text captured from a page on Jacob's screen:\n{text}\n\n"
                f"{ask} — plain conversational text for text-to-speech, no "
                "markdown, nothing invented beyond the text."}],
            "options": {"temperature": 0.2}}, timeout=120)
        r.raise_for_status()
        out = r.json()["message"]["content"].strip()
        return out[:700] if out else "I read it but came up empty summarizing it."
    except Exception:
        return "My reading brain isn't answering right now."
