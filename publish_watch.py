"""Keep GitHub in step automatically, so improvements reach other people
without anyone remembering to publish.

The owner: "i dont want to do the github thing everytime i make a change."

Rules it follows on its own:
  - only when something actually changed since the last push
  - NEVER without passing the personal-data scan first: one hit and it
    refuses and says so, rather than publishing someone's details
  - quietly, at most once an hour, and not while he's mid-conversation
"""
import hashlib
import json
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "publish_state.json"
CHECK_EVERY = 3600          # at most hourly
SETTLE = 300                # nothing published until it's been stable 5 min

# what must never appear in published files. Deliberately broad: a false
# alarm costs a skipped publish, a miss costs someone's privacy.
# Tuned against real false alarms: "python@3.12" (brew), "leaflet@1.9.4"
# (a CDN version) and "SEQTA_PASS=your password" (documentation) all looked
# like secrets on the first run and blocked a perfectly clean publish. A
# gate that cries wolf gets switched off, so it has to be accurate.
PLACEHOLDERS = ("your", "yours", "xxx", "changeme", "password", "secret",
                "token", "here", "none", "example", "abc123")
PERSONAL = [
    (r"\bjacob\b", "a name"),
    # an email needs an ALPHABETIC top-level domain — package@version isn't one
    (r"[\w.+-]+@(?!users\.noreply|example\.)[\w-]+\.[A-Za-z]{2,}\b",
     "an email address"),
    (r"\d{9,10}:AA[\w-]{20,}", "a Telegram token"),
    (r"sk-ant-[\w-]{20,}", "a Claude key"),
    (r"sk-[A-Za-z0-9]{32,}", "an API key"),
    (r"C:\\Users\\[a-z]", "a personal file path"),
]
# checked separately, because the value decides whether it's real
SECRET_ASSIGNMENTS = [
    (r"SEQTA_PASS\s*=\s*(\S+)", "a school password"),
    (r"SEQTA_USER\s*=\s*(\S+)", "a school username"),
    (r"TELEGRAM_BOT_TOKEN\s*=\s*(\S+)", "a Telegram token"),
]
NEVER_SHIP = {"profile.json", ".env", "telegram_owner.txt", "seqta_cache.json",
              "school.json", "misfires.json", "study_progress.json",
              # everything that has been on his screen — the single most
              # personal file in the project now that Rewind exists
              "index.jsonl", "rewind_state.json", "livestream_last_input.json", "presence_state.json"}

_last_check = 0.0


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    try:
        STATE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def _sources() -> list[Path]:
    return (sorted(BASE.glob("*.py")) + sorted(BASE.glob("skills/*/skill.py"))
            + sorted(BASE.glob("skills/*/skill.md"))
            + sorted(BASE.glob("dashboard/*.html"))
            + sorted(BASE.glob("*.sh")) + sorted(BASE.glob("*.md")))


def fingerprint() -> tuple[str, float]:
    """(hash of everything publishable, newest modification time)."""
    digest = hashlib.md5()
    newest = 0.0
    for path in _sources():
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(f"{path.name}{stat.st_size}{int(stat.st_mtime)}".encode())
        newest = max(newest, stat.st_mtime)
    return digest.hexdigest(), newest


def scan(folder: Path) -> list[str]:
    """Everything personal found in what's about to be published."""
    problems = []
    for path in folder.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name in NEVER_SHIP:
            problems.append(f"{path.name} should never be published")
            continue
        # ".env" and extension-less files get read too — a secret doesn't
        # stop being a secret because the file has an unusual name
        if path.suffix not in (".py", ".md", ".html", ".js", ".css", ".sh",
                               ".txt", ".json", ".env", ".cfg", ".ini", ""):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        flagged = False
        for pattern, what in PERSONAL:
            if re.search(pattern, text, re.I):
                problems.append(f"{what} in {path.relative_to(folder)}")
                flagged = True
                break
        if flagged:
            continue
        for pattern, what in SECRET_ASSIGNMENTS:
            for match in re.finditer(pattern, text):
                value = match.group(1).strip("\"'<>`")
                low = value.lower()
                # documentation, not a credential: "your password",
                # "your.username", "<token>", "$SEQTA_PASS"
                if (len(value) < 6 or low in PLACEHOLDERS
                        or any(p in low for p in ("your", "example", "..."))
                        or value[0] in "<$%{"):
                    continue
                problems.append(f"{what} in {path.relative_to(folder)}")
                flagged = True
                break
            if flagged:
                break
    return problems


def publish_now(force: bool = False) -> str:
    """Package, scan, and push. The scan is a hard gate."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gh_publish", BASE / "skills" / "github_publish" / "skill.py")
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)

    mark, _ = fingerprint()
    state = _state()
    if not force and state.get("hash") == mark:
        return "Nothing's changed since the last publish."

    publisher._export()
    problems = scan(publisher.EXPORT_DIR)
    if problems:
        state["blocked"] = problems[:5]
        _save(state)
        return ("I did NOT publish — the check found " + problems[0]
                + (f" and {len(problems) - 1} more." if len(problems) > 1
                   else "."))

    result = publisher.run({})
    state.update(hash=mark, at=time.time(), blocked=[])
    _save(state)
    return result


def tick() -> None:
    """From the standby loop. Publishes at most hourly, and only once the
    files have stopped changing — mid-edit code must never go public."""
    global _last_check
    now = time.time()
    if now - _last_check < CHECK_EVERY:
        return
    _last_check = now
    try:
        if not _enabled():
            return
        mark, newest = fingerprint()
        if _state().get("hash") == mark or now - newest < SETTLE:
            return
        outcome = publish_now()
        if outcome.startswith("I did NOT publish"):
            import announce

            announce.post("Heads up — " + outcome, hold_during_quiet=True)
    except Exception:
        pass


def _enabled() -> bool:
    try:
        return json.loads((BASE / "settings.json").read_text(
            encoding="utf-8")).get("auto_publish", True)
    except (OSError, json.JSONDecodeError):
        return True
