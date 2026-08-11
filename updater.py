"""Pull improvements down, so a copy of TARS doesn't rot.

Why this exists: the owner published fixes, then found an install without
them — because it had been cloned before the push, and nothing told it to
update. An assistant nobody updates is an assistant that stays broken.

Only ever runs on installs that came from git. Never touches profile.json,
.env, the vault or anything else personal — a pull only changes tracked
code, and none of those are tracked.
"""
import json
import subprocess
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "update_state.json"
CHECK_EVERY = 6 * 3600      # look for updates a few times a day
GIT_TIMEOUT = 60

_last_check = 0.0


def _git(*args, timeout: int = GIT_TIMEOUT):
    return subprocess.run(["git", "-C", str(BASE), *args],
                          capture_output=True, text=True, timeout=timeout)


def is_git_install() -> bool:
    return (BASE / ".git").is_dir()


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


def check(apply: bool = False) -> str:
    """What's waiting, and optionally take it."""
    if not is_git_install():
        return ("This copy wasn't installed from GitHub, so there's nothing "
                "to update from.")
    try:
        fetched = _git("fetch", "--quiet")
        if fetched.returncode != 0:
            return "I couldn't reach GitHub to check for updates."
        behind = _git("rev-list", "--count", "HEAD..@{u}").stdout.strip()
        count = int(behind or 0)
    except Exception:
        return "I couldn't work out whether there's an update."
    if not count:
        return "Already up to date."
    if not apply:
        return f"There {'is' if count == 1 else 'are'} {count} update{'' if count == 1 else 's'} waiting. Say update yourself to take them."

    # local edits (a self-taught skill, say) must not be destroyed
    dirty = _git("status", "--porcelain").stdout.strip()
    if dirty:
        _git("stash", "push", "-u", "-m", "tars-auto-update")
    pulled = _git("pull", "--ff-only", "--quiet")
    if dirty:
        _git("stash", "pop")
    if pulled.returncode != 0:
        return ("The update wouldn't apply cleanly, so I've left this copy "
                "as it is rather than break it.")
    _save({"at": time.time(), "took": count})
    return (f"Updated — {count} change{'' if count == 1 else 's'} pulled in. "
            f"Restart me and they'll be live.")


def tick() -> None:
    """From the standby loop: check a few times a day, tell him only when
    something is actually there. Never auto-applies — code that changes
    itself while running is how a working assistant becomes a broken one."""
    global _last_check
    now = time.time()
    if now - _last_check < CHECK_EVERY or not is_git_install():
        return
    _last_check = now
    try:
        if not _enabled():
            return
        outcome = check(apply=False)
        if outcome.startswith("There"):
            state = _state()
            if now - state.get("told", 0) < 86400:
                return  # mentioned it today already
            state["told"] = now
            _save(state)
            import announce

            announce.post("There's an update for me waiting on GitHub — say "
                          "update yourself when you want it.",
                          hold_during_quiet=True)
    except Exception:
        pass


def _enabled() -> bool:
    try:
        return json.loads((BASE / "settings.json").read_text(
            encoding="utf-8")).get("auto_update_check", True)
    except (OSError, json.JSONDecodeError):
        return True
