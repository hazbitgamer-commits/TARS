import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("TARS's agent staff. Run the morning briefing (Scout), tidy the brain "
               "(Librarian), or list the agents. E.g. 'give me my briefing', "
               "'run the librarian', 'who are your agents'.")
ARGS = {"action": "'briefing', 'librarian', or 'status'"}


def run(args: dict) -> str:
    import agents

    action = (args.get("action") or "status").strip().lower()
    if action == "briefing":
        return agents.run_scout(speak=False)
    if action == "librarian":
        return agents.run_librarian()
    state = agents._state()
    parts = []
    for name, desc in agents.AGENTS.items():
        key = f"{name.lower()}_ran"
        last = state.get(key, "")
        when = f", last ran {last[:16].replace('T', ' at ')}" if last else ", hasn't run yet"
        parts.append(f"{name} {desc}{when}")
    return "My staff: " + ". ".join(parts) + "."
