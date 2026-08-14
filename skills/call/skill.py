"""Phone calls — 'call the barber', 'ring mum', 'call me'.

Never dials on its own say-so: every call comes back for confirmation
first, using TARS's existing yes/no flow. See phone_call.py for the rules
that are enforced in code.
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

DESCRIPTION = ("Make a PHONE CALL — 'call mum', 'ring the barber on 9316 "
               "4444', 'call me', 'have you called anyone'. Rings a number "
               "and either connects it to your phone or passes on a "
               "message. ALWAYS asks you to confirm before dialling. NOT "
               "for texting (TARS never messages people) and NOT for the "
               "Telegram phone bridge (phone).")
ARGS = {"number": "the phone number, or a name from your contacts",
        "mode": "'bridge' to connect it to your phone (default), or "
                "'speak' to pass on a message",
        "message": "for 'speak' — what to say",
        "action": "'history' to hear recent calls"}


# ways he refers to his own phone. An exact list, not "anything starting
# with my" — "my barber" is somebody else. The bare words are here because
# the router strips the possessive: "call my mobile" arrives as "mobile".
SELF = {"me", "myself", "mobile", "phone", "cell", "number",
        "my mobile", "my phone", "my number", "my cell", "my mobile phone",
        "my own phone", "my own number", "this phone", "my mobile number",
        "your owner", "the owner"}


def _contacts() -> dict:
    """Names he's told TARS, e.g. 'mum'. Lives with the profile, never
    published."""
    import json

    try:
        return json.loads((BASE / "contacts.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def run(args: dict) -> str:
    import phone_call

    # the confirmed leg: the brain sends this back only after he said yes
    if str(args.get("confirmed", "")).lower() == "true":
        return phone_call.place(str(args.get("number", "")),
                                mode=str(args.get("mode") or "bridge"),
                                message=str(args.get("message") or ""))

    action = str(args.get("action") or "").strip().lower()
    if action in ("history", "recent", "log"):
        return phone_call.history()

    raw = str(args.get("number") or "").strip()
    if not raw:
        return "Call who?"

    # emergency check happens on the RAW words too, before any lookup
    if phone_call.is_emergency(raw):
        return ("I won't dial emergency services — that's blocked in me for "
                "good. If it's an emergency, call 000 yourself right now.")

    mode = str(args.get("mode") or "bridge").strip().lower()
    message = str(args.get("message") or "").strip()

    name = ""
    if not re.search(r"\d", raw):
        # "call me" / "call my mobile" — his own number is already in the
        # profile, and looking for it in the CONTACTS book was never going
        # to find it. This is the first thing anyone tries.
        plain = " ".join(re.sub(r"[^a-z ]", " ", raw.lower()).split())
        book = _contacts()
        # a real contact always wins — if he's saved someone as "Mobile",
        # that's who he means, not himself
        match = next((k for k in book if k.lower() in raw.lower()), "")
        if match:
            name, raw = match, str(book[match])
        elif plain in SELF:
            import profile

            mine = profile.get("mobile")
            if not mine:
                return ("I don't know your mobile number — add it on the "
                        "setup page and I'll ring you.")
            name, raw = "your mobile", mine
            if mode == "bridge":
                # bridging him to himself would ring his phone and then dial
                # the same phone, which is engaged by definition. Ringing him
                # and speaking is what "call me" actually means.
                mode = "speak"
                message = message or ("This is a test call. Everything's "
                                      "working.")
        else:
            return (f"I don't have a number for {raw}. Say it with the "
                    f"number and I'll remember it.")

    ok, why = phone_call.configured()
    if not ok:
        return why

    number = phone_call.normalise(raw)
    if mode == "speak" and not message:
        return "What should I tell them?"

    who = name or number
    # __CONFIRM__ hands this to the brain's existing yes/no flow, so
    # nothing is ever dialled off a single misheard sentence
    what = (f"connect you to {who}" if mode == "bridge"
            else f"call {who} and say: {message[:80]}")
    return (f"__CONFIRM__call:{number}|{mode}|{message}__"
            f"Shall I {what}? Say yes and I'll dial.")
