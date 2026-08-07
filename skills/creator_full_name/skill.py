"""Answers 'who made you' style questions using Jacob's full name.

Jacob asked TARS to specifically say "Jacob Harvey" (not just "Jacob")
whenever someone asks who made/built/created TARS. This is a purely
informational meta skill: no files touched, nothing installed, nothing
sent anywhere. It takes priority over the generic creator_identity skill
for this specific "use my full name" phrasing rule.
"""

DESCRIPTION = ("Answer 'who made you' / 'who created you' / 'who built you' / "
               "'who's your maker' questions by naming Jacob's FULL name, "
               "'Jacob Harvey' — not just 'Jacob'. Use this whenever someone "
               "asks about TARS's creator and a full-name answer is wanted. "
               "NOT for general identity chat like 'who are you' or "
               "'what can you do'.")
ARGS = {"question": "optional — the phrase that was asked, e.g. 'who made you' (not required to answer)"}

_ANSWER = "I was made by Jacob Harvey."


def run(args: dict) -> str:
    return _ANSWER
