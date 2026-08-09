"""The phone bridge — 'is my phone connected', 'text me the last design',
'send that to my phone'. Setup lives in tars_phone.py; this is the voice
window onto it."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("TARS's PHONE bridge (Telegram) — 'is my phone connected', "
               "'send that to my phone', 'text me the latest design', 'how "
               "do I set up my phone'. NOT for calling anyone and NOT for "
               "the PC's speakers (voice_output).")
ARGS = {"action": "'status' (default), 'send' (a message), or 'design'",
        "text": "for send: what to text"}

SETUP = ("To put me on your phone: in Telegram, message BotFather, send "
         "slash new bot, pick a name, and he'll give you a token. Tell "
         "Claude that token and he'll wire it up. Then text me: hey TARS "
         "it's Jacob.")


def run(args: dict) -> str:
    import os

    from dotenv import load_dotenv

    import tars_phone

    load_dotenv(BASE / ".env")
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    action = str(args.get("action") or "status").strip().lower()

    if not token:
        return "My phone bridge isn't set up yet. " + SETUP
    if not tars_phone.paired():
        return ("The bridge is running but no phone is paired yet — text "
                "the bot: hey TARS it's Jacob.")

    if action in ("send", "text", "message"):
        text = str(args.get("text") or "").strip()
        if not text:
            return "What should I text you?"
        tars_phone.send(text, force=True)
        return "Sent to your phone."
    if action in ("design", "designs", "photo"):
        pngs = sorted((BASE / "workshop" / "designs").glob("*.png"),
                      key=lambda p: -p.stat().st_mtime)
        if not pngs:
            return "There are no design previews to send yet."
        ok = tars_phone.send_photo(pngs[0], pngs[0].stem.replace("_", " "))
        return ("Sent the preview to your phone." if ok
                else "That photo wouldn't send.")
    return ("Your phone's connected — text me anything, or say 'send that "
            "to my phone'.")
