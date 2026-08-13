"""Take a screenshot and SEND it to the owner's phone as a photo.

Two things TARS could already do separately, just never wired together:
- the `screenshot` skill grabs the screen (mss) but only ever saves it
  locally to Pictures\\TARS — nothing leaves the PC.
- the `phone` skill can push a photo to the owner's Telegram-paired phone
  (tars_phone.send_photo) but only ever the newest design preview.

This skill is the missing link: capture a specific monitor (or all of
them) and push that exact image over the phone bridge. No new library —
mss and tars_phone are both already dependencies TARS runs today.
"""
import datetime
import sys
from pathlib import Path

from mss import mss

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("Take a screenshot of the screen (optionally a specific "
               "monitor — 'left', 'right', or 'main') and SEND it to the "
               "owner's phone as a photo, over the Telegram bridge. E.g. "
               "'take a screenshot of my left screen and show me it', "
               "'send me a screenshot', 'show me what's on my screen right "
               "now', 'send a photo of both my screens to my phone'. NOT for "
               "saving a screenshot with nothing sent anywhere (screenshot) "
               "and NOT for texting plain words (phone).")
ARGS = {"which": ("'left', 'right', 'main'/'primary' (default), or 'all' "
                  "for every monitor combined into one image")}

SETUP = ("To put me on your phone: in Telegram, message BotFather, send "
         "slash new bot, pick a name, and he'll give you a token. Tell "
         "Claude that token and he'll wire it up. Then text me: hey TARS "
         "it's the owner.")


def _pick_monitor(sct, which: str) -> int:
    """mss numbers monitors 1..N; index 0 is a virtual rect spanning all of
    them. Sort the real ones left-to-right by their actual desktop position
    so 'left screen' / 'right screen' match physical reality, not whatever
    order Windows happened to enumerate them in."""
    mons = list(enumerate(sct.monitors))[1:]
    if not mons:
        return 0
    if len(mons) == 1:
        return mons[0][0]
    if which in ("all", "both", "every", "everything", "full", "combined"):
        return 0
    by_left = sorted(mons, key=lambda t: t[1]["left"])
    if which == "left":
        return by_left[0][0]
    if which == "right":
        return by_left[-1][0]
    # main / primary / default
    for idx, rect in mons:
        if rect.get("is_primary") or (rect["left"] == 0 and rect["top"] == 0):
            return idx
    return by_left[0][0]


def run(args: dict) -> str:
    which = str(args.get("which", "") or "").strip().lower()

    out_dir = Path.home() / "Pictures" / "TARS"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"screenshot-{stamp}.png"

    with mss() as sct:
        mon = _pick_monitor(sct, which)
        sct.shot(mon=mon, output=str(path))

    token = ""
    try:
        import os

        from dotenv import load_dotenv

        load_dotenv(BASE / ".env")
        token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    except Exception:
        token = ""

    if not token:
        return ("I took the screenshot and saved it to your Pictures "
                "folder, but your phone isn't linked up yet, so I can't "
                "send it over. " + SETUP)

    import tars_phone

    if not tars_phone.paired():
        return ("I took the screenshot and saved it to your Pictures "
                "folder, but no phone is paired yet — text the bot: hey "
                "TARS it's the owner.")

    label = {"left": "left screen", "right": "right screen"}.get(
        which, "both screens" if which in
        ("all", "both", "every", "everything", "full", "combined")
        else "your screen")
    ok = tars_phone.send_photo(path, label)
    if ok:
        return f"Sent a screenshot of {label} to your phone."
    return ("I took the screenshot and saved it to your Pictures folder, "
            "but it wouldn't send to your phone — worth checking the "
            "connection.")
