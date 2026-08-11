"""Voice control of the eufy robot vacuum, targeted at a single named room."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Send the eufy robot vacuum to clean ONE specific room by name, "
               "e.g. 'clean the kitchen', 'vacuum the living room', 'do the owner's "
               "room'. Say 'list rooms' or 'what rooms do you know' to hear the "
               "known room names. For a whole-house clean, pause/resume, or "
               "docking, use the vacuum skill instead.")
ARGS = {"room": "the room name to clean, e.g. 'kitchen' or 'living room'; "
                "or 'list' to just hear the known room names",
        "override": "'true' ONLY if the owner explicitly says to override quiet hours"}


def run(args: dict) -> str:
    import eufy_vac

    room = str(args.get("room", "")).strip()

    if room.lower() in ("", "list", "get", "rooms"):
        try:
            rooms, _map_id = eufy_vac.run_sync(eufy_vac.get_rooms())
        except Exception as e:
            return str(e) if isinstance(e, RuntimeError) else f"The vacuum link failed: {e}"
        if not rooms:
            return ("I don't know this home's rooms yet — run a full clean once "
                     "so the vacuum can map the place.")
        return "Rooms I can target: " + ", ".join(r["name"] for r in rooms) + "."

    # a robot roaming a room at 2 am violates quiet hours same as a full clean
    import quiet

    active, span = quiet.is_active()
    if active and str(args.get("override", "")).lower() != "true":
        return (f"Quiet hours ({span}) — the vacuum stays docked. "
                "Say 'override quiet hours' if the mess can't wait.")

    try:
        return eufy_vac.run_sync(eufy_vac.clean_room(room))
    except Exception as e:
        return str(e) if isinstance(e, RuntimeError) else f"The vacuum didn't answer: {e}"
