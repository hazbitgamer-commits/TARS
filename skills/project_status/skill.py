"""'Where did I leave off with Goal Mystro?' — TARS reads a project's git
history, newest files, and any plan/README notes, then says where it stands
and what the obvious next step looks like. the owner runs ~9 projects at once;
this is his re-entry ramp."""
import datetime
import subprocess
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parents[2]
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
from platform_caps import bg_model

MODEL = bg_model()
ROOTS = (Path.home() / "Projects", Path.home() / "Desktop")
SKIP = {"tools", "screenshots", "videos", "scripts", "node_modules"}

DESCRIPTION = ("Catch the owner up on one of his PROJECTS (also called repos or "
               "repositories) — 'where did I leave off with Goal Mystro', "
               "'what's the state of Undergrid', 'what was I doing on the "
               "solar app', 'what projects do I have', 'what repos are "
               "installed on this PC', 'list my repositories'. Reads the "
               "project's recent changes and notes. NOT for TARS's own "
               "upgrades (improve) and NOT for the day's recap (day_recap).")
ARGS = {"project": "the project name, or 'list' for all of them (also "
                    "triggered by 'repos'/'repositories'/'installed')"}


def _projects() -> dict:
    found = {}
    for root in ROOTS:
        if not root.exists():
            continue
        for p in root.iterdir():
            if p.is_dir() and not p.name.startswith(".") \
                    and p.name.lower() not in SKIP:
                found[p.name.lower()] = p
    return found


def _match(name: str, projects: dict) -> Path | None:
    import difflib

    name = name.strip().lower()
    if name in projects:
        return projects[name]
    loose = name.replace(" ", "").replace("_", "")
    for key, path in projects.items():
        k = key.replace(" ", "").replace("_", "")
        if loose and (loose in k or k in loose):
            return path
    close = difflib.get_close_matches(name, list(projects), n=1, cutoff=0.6)
    return projects[close[0]] if close else None


def _git(path: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(path), *args],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def run(args: dict) -> str:
    want = str(args.get("project") or "list").strip().lower()
    projects = _projects()
    if not projects:
        return "I can't find any project folders to look at."
    if want in ("list", "all", "", "everything", "repo", "repos",
                "repository", "repositories", "installed"):
        names = sorted(p.name for p in projects.values())
        return (f"You've got {len(names)} projects (repos) installed: "
                + ", ".join(names[:10])
                + ". Ask where you left off with any of them.")

    path = _match(want, projects)
    if path is None:
        return (f"I can't find a project called {want}. Say 'what projects "
                "do I have' for the list.")

    facts = [f"Project: {path.name} at {path}"]
    log = _git(path, "log", "-8", "--pretty=%ad %s", "--date=short")
    if log:
        facts.append("Recent commits:\n" + log)
        status = _git(path, "status", "--short")
        facts.append(f"Uncommitted changes: {status[:300] or 'none'}")
    files = [f for f in path.rglob("*")
             if f.is_file() and ".git" not in f.parts
             and "node_modules" not in f.parts and f.stat().st_size > 0]
    files.sort(key=lambda f: -f.stat().st_mtime)
    if files:
        newest = files[:6]
        facts.append("Recently changed files: " + ", ".join(
            f"{f.name} ({datetime.date.fromtimestamp(f.stat().st_mtime):%d %b})"
            for f in newest))
    for note in ("PLAN.md", "TODO.md", "README.md", "NOTES.md"):
        p = path / note
        if p.exists():
            facts.append(f"{note} says:\n"
                         + p.read_text(encoding="utf-8", errors="replace")[:1200])
            break
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL, "stream": False, "think": False,
            "messages": [{"role": "user", "content":
                "You are TARS catching the owner up on his own project. From "
                "these facts, say in THREE short spoken sentences: what the "
                "project is, where it stands right now, and the obvious next "
                "step. Plain text for text-to-speech, no markdown, nothing "
                "invented beyond the facts:\n\n" + "\n\n".join(facts)}]},
            timeout=120)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()[:600]
    except Exception:
        return (f"{path.name}: last touched "
                f"{datetime.date.fromtimestamp(files[0].stat().st_mtime):%d %B}"
                if files else f"{path.name} looks empty.")
