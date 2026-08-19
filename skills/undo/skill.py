"""Undo the last change TARS itself made."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("Undo the last change TARS MADE — the volume or brightness it just "
               "set, a personality/voice/quiet-hours change, or files it deleted "
               "('undo that', 'put that back', 'undo the last thing you did'). "
               "NOT the undo keystroke inside an app like a document or game "
               "(that's the keyboard skill: 'press undo').")
ARGS = {}


def run(args: dict) -> str:
    import undo as undo_mod

    return undo_mod.undo()
