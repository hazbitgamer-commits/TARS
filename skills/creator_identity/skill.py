"""Answers questions about who made / built / created TARS.

This is a meta skill: purely informational, no files touched, nothing
installed, nothing sent anywhere. The fact itself (Jacob built TARS) lives
here as plain text rather than in the memory vault, so it's always available
even if the vault note gets edited or removed.
"""

DESCRIPTION = ("Answer questions about who made, built, or created TARS. "
               "E.g. 'Jacob made you', 'who made you', 'who created you', "
               "'who built you', 'did Jacob make you'. NOT for general "
               "identity chat like 'who are you' or 'what can you do' — "
               "this is specifically about TARS's creator/origin.")
ARGS = {"statement": "optional — the phrase Jacob said, e.g. 'Jacob made you' (not required to answer)"}

_ANSWER = ("That's right, Jacob — you built me. You put me together here on "
           "this PC, running on Claude, with my own skills folder so I can "
           "keep teaching myself new things.")


def run(args: dict) -> str:
    return _ANSWER
