"""Voice controls for Kipp, TARS's always-on self-improvement agent
(improve.py). Kipp reflects on the day's transcripts whenever TARS is idle
and automatically upgrades TARS's own code — this skill is Jacob's window
into that, and his off-switch.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Control or report on Kipp, TARS's self-improvement agent. "
               "E.g. 'pause self-improvement' / 'resume self-improvement', "
               "'what have you improved today', 'how is your self-improvement "
               "going', 'improve yourself now'. NOT for teaching one specific "
               "new skill (that's the normal learning flow) and NOT for the "
               "morning briefing (that's agents).")
ARGS = {"action": "'status', 'recent' (list latest upgrades), 'pause', "
                  "'resume', or 'now' (reflect and upgrade immediately)"}


def run(args: dict) -> str:
    import improve

    action = str(args.get("action", "status")).strip().lower()

    if action in ("pause", "stop", "off"):
        improve.set_paused(True)
        return ("Self-improvement paused. I'll stop rewriting myself until "
                "you say resume self-improvement.")
    if action in ("resume", "start", "on"):
        improve.set_paused(False)
        return "Self-improvement is back on. I'll keep getting smarter."
    if action == "now":
        return improve.force_now()
    if action == "recent":
        log = BASE / "improvements.log"
        if not log.exists():
            return "No self-upgrades yet — Kipp hasn't found anything to fix."
        done = [l.split("DONE: ", 1)[1] for l in
                log.read_text(encoding="utf-8").splitlines() if "DONE: " in l]
        if not done:
            return ("Kipp has proposals brewing but hasn't landed an upgrade "
                    "yet.")
        recent = done[-3:]
        return "My latest upgrades: " + " Next: ".join(
            d.split(" — ")[0] for d in recent) + "."

    s = improve._state()
    if s.get("paused"):
        return "Self-improvement is paused right now."
    count = s.get("count", 0) if s.get("day") else 0
    pending = len(s.get("pending", []))
    return (f"Kipp's on duty. {count} upgrade"
            f"{'' if count == 1 else 's'} implemented today, "
            f"{pending} idea{'' if pending == 1 else 's'} waiting. I work on "
            f"myself whenever you leave me idle.")
