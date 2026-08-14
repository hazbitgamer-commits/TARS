"""Fill in the boring parts of a signup form — and stop before the part
that's the owner's to do.

What it does: reads the form on screen through Windows' accessibility tree
(the same fast path the clicker uses), works out which box is which, types
in his name and email, invents a strong password, and saves that password
to the vault so he never has to know it.

What it deliberately does NOT do, enforced here in code rather than asked
of a model:

  - never CLICKS anything. Not Submit, not Sign up, not Continue.
  - never ticks a checkbox. "I agree to the terms" is a legal agreement in
    his name; a program shouldn't be able to make it on his behalf.
  - never touches a payment field. If it sees one it stops the whole thing
    and says so — a signup form asking for a card is a different animal.
  - never fills a date of birth. He can type his own; a program filling age
    boxes is how age gates get walked past.

So he ends up at a filled-in form with the cursor on the tickbox, having
typed nothing. That's the intended finish line, not a limitation.

The password it makes goes straight into Windows Credential Manager, which
means the redaction filter picks it up automatically — from that moment
TARS physically cannot say it out loud or text it.
"""
import json
import secrets as _random
import string
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LOGINS = BASE / "logins.json"     # usernames only — never passwords

DESCRIPTION = ("FILL IN a signup / registration form that's already open on "
               "screen: types the owner's name, email and a strong invented "
               "password, saves that password, and stops before the terms "
               "tickbox and the submit button so he agrees himself. E.g. "
               "'fill in this signup', 'make me an account here', 'sign me "
               "up for this'. NOT for logging into an account that already "
               "exists, and it never submits anything.")
ARGS = {"email": "optional — use this address instead of his usual one"}

# If any of these appear, the whole thing stops. A registration form asking
# for card details is either a paid signup or something worse; either way a
# program should not be typing into it.
PAYMENT = ("card number", "cardnumber", "cvv", "cvc", "security code",
           "expiry", "expiration", "card holder", "cardholder", "iban",
           "bsb", "sort code", "routing number", "account number",
           "credit card", "debit card")

# (which box is which now lives in webforms.py, shared with the login filler)

# generated passwords avoid characters that uiautomation's SendKeys treats
# as commands — a stray "+" or "{" would type something else entirely and
# he'd have a password that doesn't match what was saved
SAFE = string.ascii_letters + string.digits + "-_.!?"


def _make_password(length: int = 20) -> str:
    while True:
        pw = "".join(_random.choice(SAFE) for _ in range(length))
        # make sure it satisfies the usual "must contain" rules first time
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)
                and any(c in "-_.!?" for c in pw)):
            return pw


def _remember_username(domain: str, username: str) -> None:
    """Usernames are not secrets and must NOT go in the vault — everything
    in there gets blanked out of TARS's speech, and having his own email
    replaced with [password hidden] in every sentence would be daft."""
    try:
        data = json.loads(LOGINS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data[domain] = username
    try:
        LOGINS.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def run(args: dict) -> str:
    try:
        import uiautomation  # noqa: F401
    except ImportError:
        return "I can't read forms on this computer — uiautomation isn't installed."

    import profile
    import webforms

    boxes = webforms.boxes()
    if not boxes:
        return ("I can't see any boxes to fill in. Is the signup page open "
                "and in front?")

    labels = [webforms.label(b) for b in boxes]

    # HARD STOP: a card field means this isn't a plain signup
    hit = next((lab for lab in labels
                if any(p in lab.lower() for p in PAYMENT)), "")
    if hit:
        return (f"I've stopped — that form asks for payment details "
                f"(\"{hit[:40]}\"). I don't type card numbers, so this one's "
                f"yours to fill in.")

    email = str(args.get("email") or "").strip() or profile.get("email")
    name = profile.owner()
    first, _, last = name.partition(" ")
    domain = webforms.domain() or 'this site'
    password = _make_password()

    values = {"email": email, "username": email.split("@")[0] if email else "",
              "first": first, "last": last or "", "full": name,
              "password": password, "confirm": password}

    filled, skipped, used_password = [], [], False
    for box, label in zip(boxes, labels):
        kind = webforms.classify(label)
        if not kind:
            if label:
                skipped.append(label[:24])
            continue
        value = values.get(kind, "")
        if not value:
            skipped.append(label[:24])
            continue
        if webforms.type_into(box, value):
            filled.append(kind)
            if kind in ("password", "confirm"):
                used_password = True

    if not filled:
        return ("I found boxes but couldn't tell what any of them were for. "
                "Fill this one in yourself — the page isn't labelling them.")

    if used_password:
        try:
            import secrets_store

            secrets_store.put(f"site:{domain}", password)
        except Exception:
            return ("I filled the form in but COULDN'T save the password — "
                    "don't submit it, or you'll be locked out. Change the "
                    "password box to something you know first.")
        if email:
            _remember_username(domain, email)

    parts = [f"Filled in: {', '.join(sorted(set(filled)))}."]
    if used_password:
        parts.append(f"I made a strong password and saved it under "
                     f"'{domain}' — you don't need to know it, I'll type it "
                     f"when you come back.")
    if skipped:
        parts.append(f"Left for you: {', '.join(sorted(set(skipped))[:4])}.")
    parts.append("I haven't ticked the terms box or pressed anything — "
                 "read it and finish it off yourself.")
    return " ".join(parts)
