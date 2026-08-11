"""Voice profiles — 'learn my voice', 'whose voice is this', 'forget
Sophie's voice'. Unknown speakers automatically get the guest treatment
(no personal facts), so the owner never has to toggle guest mode by hand."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("VOICE profiles — 'learn my voice' / 'remember my voice as "
               "the owner' (TARS fingerprints the speaker), 'whose voice do you "
               "know', 'forget Sophie's voice'. Different from face "
               "recognition (face_learn), which uses the camera.")
ARGS = {"action": "'learn' (default), 'list', or 'forget'",
        "name": "whose voice — defaults to the owner for 'learn my voice'"}


def run(args: dict) -> str:
    import main
    import speaker

    action = str(args.get("action") or "learn").strip().lower()
    name = str(args.get("name") or "").strip().title()

    if action in ("list", "who", "known"):
        names = speaker.known()
        return ("I know the voice of " + " and ".join(names) + "."
                if names else "I haven't learned anyone's voice yet — say "
                              "'learn my voice'.")
    if action in ("forget", "remove", "delete"):
        return speaker.forget(name or "")

    audio = getattr(main, "LAST_AUDIO", None)
    if audio is None:
        return "I don't have your last recording to learn from — say it again."
    return speaker.enroll(name or "the owner", audio)
