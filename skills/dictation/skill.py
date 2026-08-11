"""Dictation mode: hands-free continuous typing. The skill itself just
returns a sentinel — main.py sees __DICTATE__ and switches the voice loop
into type-everything-the owner-says mode until he says 'stop dictation'."""

DESCRIPTION = ("Start DICTATION mode: TARS types everything the owner says into "
               "whatever window is focused, sentence after sentence, until "
               "he says 'stop dictation'. E.g. 'type what I say', 'take "
               "dictation', 'dictation mode'. NOT for typing one short "
               "given phrase (that's type_text).")
ARGS = {}


def run(args: dict) -> str:
    return "__DICTATE__"
