"""Answers questions about who made / built / created TARS.

This is a meta skill: purely informational, no files touched, nothing
installed, nothing sent anywhere. The fact itself (the owner built TARS) lives
here as plain text rather than in the memory vault, so it's always available
even if the vault note gets edited or removed.
"""

DESCRIPTION = ("Answer questions about who made, built, or created TARS. "
               "E.g. 'the owner made you', 'who made you', 'who created you', "
               "'who built you', 'did the owner make you'. NOT for general "
               "identity chat like 'who are you' or 'what can you do' — "
               "this is specifically about TARS's creator/origin.")
ARGS = {"statement": "optional — the phrase the owner said, e.g. 'the owner made you' (not required to answer)"}

_ANSWER = ("That's right, the owner — you built me. You put me together here on "
           "this PC, running on Claude, with my own skills folder so I can "
           "keep teaching myself new things.")


def run(args: dict) -> str:
    return _ANSWER
