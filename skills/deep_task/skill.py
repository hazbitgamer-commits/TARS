"""The big brain: hands complex/coding tasks to Claude (the owner's subscription,
via the official Agent SDK). Runs in the background; TARS announces the result.

Claude gets full hands INSIDE tars/workshop, with the hard-block rules from
the spec baked into every task prompt.
"""
import datetime
import json
import sys
import threading
from pathlib import Path

DESCRIPTION = ("Send a complex task to the heavy-lift Claude brain: writing code or scripts, "
               "building things, research that needs multiple steps, fixing files. Takes a "
               "minute or more; TARS reports back when done.")
ARGS = {"task": "the full task, in the owner's words"}

BASE = Path(__file__).resolve().parents[2]
WORKSHOP = BASE / "workshop"

import sys as _sys

_TARS_PY = (str(BASE / "runtime" / "python.exe") if _sys.platform == "win32"
            else (_sys.executable or "python3"))
RULES = (
    "Hard rules, no exceptions: never delete files outside the working folder; "
    "never spend money or make purchases; never send emails or messages; "
    "keep all new files inside the working folder unless the task explicitly "
    "names another location. the owner is a beginner — keep anything he'll see simple.\n"
    f"To run Python, always use TARS's own interpreter: {_TARS_PY}"
)


ACTIVE_FILE = BASE / "deep_task_active.json"


def _mark(delta: int) -> None:
    """Track running big-brain tasks by START TIME — the brain's honesty
    check reads this to know whether 'work is underway' is true or a chat
    bluff. Timestamps (not a bare count) so a worker that dies without
    decrementing can't leave the count stuck high forever, silently
    disabling the lie detector — which is exactly what happened."""
    import time as _t

    try:
        data = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        tasks = [t for t in data.get("tasks", []) if _t.time() - t < 1800]
    except (OSError, json.JSONDecodeError):
        tasks = []
    if delta > 0:
        tasks.append(_t.time())
    elif tasks:
        tasks.pop(0)
    ACTIVE_FILE.write_text(json.dumps({"tasks": tasks, "count": len(tasks)}),
                           encoding="utf-8")


def _worker(task: str) -> None:
    sys.path.insert(0, str(BASE))
    import announce

    _mark(+1)
    try:
        # Run in a clean session: inherited session credentials cause 401s, and
        # the global plugin config drowns the task in unrelated skill listings.
        # Auth comes from TARS's own token (claude setup-token) in .env.
        import os

        from dotenv import load_dotenv

        load_dotenv(BASE / ".env")
        token = (os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
        for key in [k for k in os.environ
                    if k.startswith(("ANTHROPIC", "CLAUDE"))]:
            os.environ.pop(key, None)
        if not token:
            announce.post("The big brain isn't connected yet — the owner needs to "
                          "set up my Claude token. It's in the readme.")
            return
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token

        import anyio
        import quiet_spawn
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        quiet_spawn.hide()  # no black console window over the owner's desktop

        WORKSHOP.mkdir(exist_ok=True)
        prompt = (
            f"You are TARS's heavy-lift brain, working for the owner on his Windows PC.\n"
            f"Working folder: {WORKSHOP}\n{RULES}\n\n"
            f"the owner's spoken request: {task!r}\n\n"
            "When finished, end your final message with a line starting exactly "
            "'SPOKEN: ' — one or two friendly sentences summarizing the outcome, "
            "suitable for text-to-speech. Always NAME any files you created "
            "(e.g. 'countdown.py') in that summary."
        )
        options = ClaudeAgentOptions(
            cwd=str(WORKSHOP),
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep",
                           "WebSearch", "WebFetch"],
            setting_sources=[],  # a clean session — no inherited configs/plugins
            # 50 wasn't enough for real jobs — the owner's dashboard-panel build
            # died on "Reached maximum number of turns (50)" after doing most
            # of the work. A wall mid-job wastes everything spent getting there.
            max_turns=120,
        )

        async def go() -> str:
            result_text = ""
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage) and message.result:
                    result_text = message.result
            return result_text

        try:
            result = anyio.run(go)
        except Exception as first_err:
            msg = str(first_err).lower()
            if "129" in msg or "message reader" in msg:
                # the claude CLI flakes with exit 129 sometimes — one retry
                import time as _t

                _t.sleep(10)
                result = anyio.run(go)
            else:
                raise
        spoken = ""
        for line in reversed(result.splitlines()):
            if line.strip().startswith("SPOKEN:"):
                spoken = line.strip()[7:].strip()
                break
        if not spoken:
            spoken = (result.strip()[-300:] or "It finished, but left no summary.")
        announce.post(f"Big brain's done. {spoken}")
        (BASE / "logs").mkdir(exist_ok=True)
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(BASE / "logs" / "deep_tasks.log", "a", encoding="utf-8") as f:
            f.write(f"\n=== {stamp} :: {task}\n{result}\n")
    except Exception as e:
        announce.post(f"The big brain hit a wall: {e}")
    finally:
        _mark(-1)


def run(args: dict) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return "What's the task, exactly?"
    threading.Thread(target=_worker, args=(task,), daemon=True).start()
    return "That needs the big brain. I've put it to work — I'll tell you when it's done."
