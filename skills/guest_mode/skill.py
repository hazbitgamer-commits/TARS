"""Guest mode: when Sophie or mates are around, TARS keeps Jacob's
personal facts to himself and stays politely generic. Voice on/off."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
FILE = BASE / "guest_mode.json"

DESCRIPTION = ("GUEST MODE on/off — 'guest mode on' when someone's around "
               "(TARS hides Jacob's personal facts and keeps it generic and "
               "polite), 'guest mode off' when they leave, 'is guest mode "
               "on'. NOT the same as sleep mode.")
ARGS = {"state": "'on', 'off', or 'status'"}


def active() -> bool:
    try:
        return bool(json.loads(FILE.read_text(encoding="utf-8")).get("on"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def run(args: dict) -> str:
    state = str(args.get("state", "status")).strip().lower()
    if state in ("on", "true", "enable"):
        FILE.write_text(json.dumps({"on": True}), encoding="utf-8")
        return "Guest mode on. Your business stays ours."
    if state in ("off", "false", "disable"):
        FILE.write_text(json.dumps({"on": False}), encoding="utf-8")
        return "Guest mode off. Back to normal."
    return ("Guest mode is on right now." if active()
            else "Guest mode is off.")
