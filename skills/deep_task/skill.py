"""The big brain: hands complex/coding tasks to Claude (Jacob's subscription,
via the official Agent SDK). Runs in the background; TARS announces the result.

Claude gets full hands INSIDE tars/workshop, with the hard-block rules from
the spec baked into every task prompt.
"""
import datetime
import sys
import threading
from pathlib import Path

DESCRIPTION = ("Send a complex task to the heavy-lift Claude brain: writing code or scripts, "
               "building things, research that needs multiple steps, fixing files. Takes a "
               "minute or more; TARS reports back when done.")
ARGS = {"task": "the full task, in Jacob's words"}

BASE = Path(__file__).resolve().parents[2]
WORKSHOP = BASE / "workshop"

import sys as _sys

_TARS_PY = (str(BASE / "runtime" / "python.exe") if _sys.platform == "win32"
            else (_sys.executable or "python3"))
RULES = (
    "Hard rules, no exceptions: never delete files outside the working folder; "
    "never spend money or make purchases; never send emails or messages; "
    "keep all new files inside the working folder unless the task explicitly "
    "names another location. Jacob is a beginner — keep anything he'll see simple.\n"
    f"To run Python, always use TARS's own interpreter: {_TARS_PY}"
)


def _worker(task: str) -> None:
    sys.path.insert(0, str(BASE))
    import announce

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
            announce.post("The big brain isn't connected yet — Jacob needs to "
                          "set up my Claude token. It's in the readme.")
            return
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token

        import anyio
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        WORKSHOP.mkdir(exist_ok=True)
        prompt = (
            f"You are TARS's heavy-lift brain, working for Jacob on his Windows PC.\n"
            f"Working folder: {WORKSHOP}\n{RULES}\n\n"
            f"Jacob's spoken request: {task!r}\n\n"
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
            max_turns=50,
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


def run(args: dict) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return "What's the task, exactly?"
    threading.Thread(target=_worker, args=(task,), daemon=True).start()
    return "That needs the big brain. I've put it to work — I'll tell you when it's done."
