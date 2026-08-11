"""Stages a WhatsApp message WITHOUT sending it. the owner's hard rule is that
TARS never sends messages on his behalf — this is the "yes" path off the
back of that offer: copy the text to his clipboard, open WhatsApp, and let
him paste it in and hit send himself."""
import os

import pyperclip

DESCRIPTION = ("Prepares a WhatsApp message for the owner to send HIMSELF — copies "
               "text onto his clipboard and opens WhatsApp so he can paste it "
               "in and hit send. This never sends anything on its own.")
ARGS = {"text": "the message to put on the clipboard, if any; leave blank to "
                "just open WhatsApp with whatever's already on the clipboard"}


def run(args: dict) -> str:
    text = str(args.get("text", "")).strip()

    if text:
        try:
            pyperclip.copy(text)
        except Exception:
            return "I couldn't copy that to your clipboard."

    try:
        os.startfile("https://web.whatsapp.com")
    except OSError:
        return "I couldn't open WhatsApp."

    if text:
        return ("Opened WhatsApp and put that message on your clipboard — "
                "paste it in and hit send yourself.")
    return "Opened WhatsApp — paste what's on your clipboard and hit send yourself."
