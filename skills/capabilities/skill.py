"""'What can you do?' — an honest tour of TARS's own abilities.

With 90-odd skills, the owner can't be expected to remember what exists (he has
asked for things TARS already had, and gone without things he never knew
about). This reads the real catalog, groups it, and answers in plain speech
— including 'what's new this week' and 'what can you do with the camera'.
"""
import datetime
import json
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model

MODEL = bg_model()

DESCRIPTION = ("Explain what TARS CAN DO — 'what can you do', 'what are "
               "your abilities', 'what's new', 'what can you do with the "
               "camera/vacuum/designs', 'how many skills do you have'. "
               "Reads his real skill list, so it's never invented. NOT for "
               "how he learns (how_i_learn) and NOT for his self-upgrades "
               "(improve).")
ARGS = {"topic": "optional area — camera, design, house, memory, computer, "
                 "music, phone — or 'new' for recent additions"}

GROUPS = {
    "house": ("vacuum", "speakers", "quiet_hours", "routines", "recurring",
              "timers", "solar", "weather"),
    "designs": ("design", "cad", "map_view"),
    "computer": ("open_app", "click_screen", "screen_task", "agent", "tabs",
                 "read_page", "dictation", "screen_watch", "manage_window",
                 "volume", "brightness", "steam", "music", "media",
                 "pc_health", "pc_specs", "organize", "search_files"),
    "memory": ("remember", "recall", "lists", "ideas", "project_status",
               "day_recap", "nightly_wrap", "correct_name", "life_events"),
    "senses": ("camera", "camera_feed", "face_learn", "face_who",
               "object_detection", "look_at_screen", "voice_id"),
    "himself": ("improve", "self_check", "work_queue", "find_tool",
                "github_publish", "voice_settings", "voice_output",
                "list_voices", "personality", "agents"),
    "out in the world": ("web_search", "browser_search", "email", "calendar",
                         "phone", "navigate_to"),
}


def _catalog() -> list[dict]:
    from skills_engine import SkillBox

    return SkillBox(BASE).catalog()


def _recent(days: int = 7) -> list[str]:
    cutoff = datetime.datetime.now().timestamp() - days * 86400
    out = []
    for s in _catalog():
        p = BASE / "skills" / s["skill"] / "skill.py"
        try:
            if p.stat().st_mtime > cutoff:
                out.append(s["skill"])
        except OSError:
            continue
    return out


def run(args: dict) -> str:
    topic = str(args.get("topic") or "").strip().lower()
    catalog = _catalog()
    names = {s["skill"] for s in catalog}

    if topic in ("new", "recent", "latest"):
        fresh = _recent()
        if not fresh:
            return "Nothing new this week — same abilities as before."
        return (f"New this week: "
                + ", ".join(n.replace("_", " ") for n in fresh[:10])
                + f". That's {len(fresh)} additions, {len(names)} skills in "
                f"total.")

    if topic in ("count", "how many"):
        return f"I've got {len(names)} skills right now."

    # a specific area
    for group, members in GROUPS.items():
        if topic and (topic in group or any(topic in m for m in members)):
            have = [m for m in members if m in names]
            descs = [s["description"][:90] for s in catalog
                     if s["skill"] in have][:6]
            try:
                r = requests.post(OLLAMA_URL, json={
                    "model": MODEL, "stream": False, "think": False,
                    "messages": [{"role": "user", "content":
                        f"TARS's {group} abilities:\n" + "\n".join(descs)
                        + "\n\nTell the owner in TWO short spoken sentences what "
                        "he can ask for here, with one concrete example "
                        "phrase. Plain text, no markdown, nothing invented."}]},
                    timeout=90)
                r.raise_for_status()
                return r.json()["message"]["content"].strip()[:400]
            except Exception:
                return (f"My {group} skills: "
                        + ", ".join(h.replace("_", " ") for h in have) + ".")

    # the whole tour
    lines = []
    for group, members in GROUPS.items():
        have = [m for m in members if m in names]
        if have:
            lines.append(f"{group}: " + ", ".join(
                h.replace("_", " ") for h in have[:5])
                + (" and more" if len(have) > 5 else ""))
    return (f"I've got {len(names)} skills. Roughly: " + "; ".join(lines)
            + ". Ask what I can do with any one of those — the camera, the "
            "house, designs — and I'll go deeper.")
