"""Jacob's overnight work queue — hand TARS jobs before bed ("add to your
overnight queue: give the CAD app a save button"), he works through them
between 10pm and 7am and announces the results in the morning."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("TARS's OVERNIGHT WORK QUEUE — 'add to your overnight queue: "
               "<job>', 'work on this tonight: <job>', 'what's in your "
               "queue', 'clear the queue'. Jobs are built overnight (10pm "
               "to 7am) and announced in the morning. NOT for immediate "
               "work (say it as a normal command) and NOT for shopping/"
               "to-do lists (lists).")
ARGS = {"action": "'add' (default), 'list', or 'clear'",
        "task": "the job to do overnight"}


def run(args: dict) -> str:
    import improve

    action = str(args.get("action") or "add").strip().lower()
    task = str(args.get("task") or "").strip()

    if action in ("list", "read", "status"):
        items = improve.queue_load()
        waiting = [i for i in items if i["status"] == "waiting"]
        done = [i for i in items if i["status"] == "done"]
        if not items:
            return "The overnight queue is empty."
        parts = []
        if waiting:
            parts.append(f"{len(waiting)} waiting: "
                         + "; ".join(i["task"][:60] for i in waiting[:4]))
        if done:
            parts.append(f"{len(done)} finished")
        return ". ".join(parts) + "."

    if action in ("clear", "empty", "cancel"):
        improve.queue_save([])
        return "Overnight queue cleared."

    if not task:
        return "What should I work on overnight?"
    n = improve.queue_add(task)
    return (f"Added to tonight's queue — {n} job{'s' if n != 1 else ''} "
            f"waiting. I'll work through them after 10 and tell you in the "
            f"morning.")
