"""Voice control of the eufy robot vacuum. Respects quiet hours."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

_NICK_FILE = BASE / "vacuum_nickname.txt"
try:
    _NICKNAME = _NICK_FILE.read_text(encoding="utf-8").strip() or "the vacuum"
except FileNotFoundError:
    _NICKNAME = "the vacuum"

DESCRIPTION = (f"Control the eufy robot vacuum, which the owner has nicknamed {_NICKNAME} and "
               "also refers to as 'he'/'him' (not to be confused with any other skill): "
               "start a WHOLE-HOME clean (per-room cleaning not supported yet), pause, "
               "resume, send it home to the dock, or check the connection. E.g. 'start the "
               f"vacuum', 'send the vacuum home', 'send him home', 'is {_NICKNAME} charging'.")
ARGS = {"action": "'clean', 'pause', 'resume', 'dock', or 'status'",
        "override": "'true' ONLY if the owner explicitly says to override quiet hours"}

COMMANDS = {"clean": "start_auto", "start": "start_auto", "vacuum": "start_auto",
            "resume": "play", "pause": "pause", "stop": "pause",
            "dock": "return_to_base", "home": "return_to_base"}

REPLIES = {"start_auto": ("{name} is on the job — full clean, though it may spend a "
                          "minute prepping at the dock before it rolls out. "
                          "I can't target single rooms yet."),
           "play": "{name} is back at it.",
           "pause": "{name} is paused.",
           "return_to_base": "{name} is heading home to the dock."}


def run(args: dict) -> str:
    import eufy_vac

    action = (args.get("action") or "status").strip().lower()

    if action == "status":
        try:
            return eufy_vac.run_sync(eufy_vac.info())
        except Exception as e:
            return str(e) if isinstance(e, RuntimeError) else f"The vacuum link failed: {e}"

    cmd = COMMANDS.get(action)
    if cmd is None:
        return "With the vacuum I can clean, pause, resume, dock it, or check status."

    # a robot roaming the house at 2 am violates quiet hours
    if cmd in ("start_auto", "play"):
        import quiet

        active, span = quiet.is_active()
        if active and str(args.get("override", "")).lower() != "true":
            return (f"Quiet hours ({span}) — the vacuum stays docked. "
                    "Say 'override quiet hours' if the mess can't wait.")

    try:
        name = eufy_vac.run_sync(eufy_vac.command(cmd))
        return REPLIES[cmd].format(name=name)
    except Exception as e:
        return str(e) if isinstance(e, RuntimeError) else f"The vacuum didn't answer: {e}"
