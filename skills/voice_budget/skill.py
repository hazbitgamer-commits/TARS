"""How much of the good voice is left this month.

Worth being able to ask, because the alternative is finding out by noticing
he suddenly sounds different mid-sentence and wondering what broke.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DESCRIPTION = ("How much PAID VOICE (ElevenLabs) is left this month — "
               "'how much voice have I got left', 'how many credits are "
               "left', 'am I running out of the good voice', 'voice "
               "budget'. NOT for changing which voice he uses (that's "
               "voice_settings) and NOT about phone call costs.")
ARGS = {}


def run(args: dict) -> str:
    try:
        import eleven_budget

        return eleven_budget.status()
    except Exception as e:
        return f"I couldn't check the voice budget ({type(e).__name__})."
