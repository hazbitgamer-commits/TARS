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
import re
import secrets as _random
import string
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
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

# what each box is, in the order we try to match. Longest/most specific
# first: "confirm password" must beat "password".
KINDS = [
    ("confirm", ("confirm password", "repeat password", "re-enter password",
                 "retype password", "password again", "confirm your password")),
    ("password", ("password", "passphrase", "choose a password")),
    ("email", ("email", "e-mail", "email address")),
    ("first", ("first name", "given name", "forename")),
    ("last", ("last name", "surname", "family name")),
    ("username", ("username", "user name", "display name", "nickname",
                  "handle", "screen name")),
    ("full", ("full name", "your name", "name")),
]

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


def _label(control) -> str:
    """What a box calls itself. Falls back through the properties websites
    actually populate — many leave Name empty and only set the placeholder
    or the help text."""
    for attr in ("Name", "AutomationId", "HelpText"):
        try:
            value = (getattr(control, attr, "") or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return ""


def _flatten(text: str) -> str:
    """Punctuation out, single spaces in. Applied to the LABEL and to the
    patterns alike — matching a hyphenated pattern against de-hyphenated
    text is how "re-enter password" got treated as the first password box."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


_KINDS_FLAT = [(kind, tuple(_flatten(w) for w in words)) for kind, words in KINDS]


def _classify(label: str) -> str:
    low = _flatten(label)
    for kind, words in _KINDS_FLAT:
        if any(w in low for w in words):
            return kind
    return ""


def _domain() -> str:
    """Which site this is, from the browser's address bar."""
    try:
        import uiautomation as auto

        win = auto.GetForegroundControl().GetTopLevelControl()
        for name in ("Address and search bar", "Address bar", "Search or enter address"):
            bar = win.EditControl(Name=name)
            if bar.Exists(1, 0.1):
                url = (bar.GetValuePattern().Value or "").strip()
                m = re.search(r"https?://([^/]+)", url) or re.match(r"([\w.-]+\.\w+)", url)
                if m:
                    return m.group(1).lower().replace("www.", "")
    except Exception:
        pass
    try:
        import uiautomation as auto

        title = (auto.GetForegroundControl().GetTopLevelControl().Name or "")
        return (title.split(" - ")[-1] or "this site").strip().lower()[:40]
    except Exception:
        return "this site"


def _boxes():
    """Every text box on the page, in reading order."""
    import time

    import uiautomation as auto

    win = auto.GetForegroundControl().GetTopLevelControl()
    # Chromium hides the page's elements until an accessibility client pokes
    # the document — same wake-up the clicker needs
    try:
        doc = win.DocumentControl(searchDepth=20)
        if doc.Exists(2, 0.2):
            doc.GetChildren()
            time.sleep(0.6)
            win = doc
    except Exception:
        pass

    found = []

    def walk(node, depth=0):
        if depth > 25 or len(found) > 60:
            return
        try:
            children = node.GetChildren()
        except Exception:
            return
        for child in children:
            try:
                if child.ControlTypeName == "EditControl":
                    rect = child.BoundingRectangle
                    if rect.width() > 20 and rect.height() > 8:
                        found.append(child)
                walk(child, depth + 1)
            except Exception:
                continue

    walk(win)
    return found


def _type_into(control, text: str) -> bool:
    import uiautomation as auto

    try:
        control.SetFocus()
        auto.SendKeys("{Ctrl}a", waitTime=0)      # replace, don't append
        auto.SendKeys(text, waitTime=0)
        return True
    except Exception:
        return False


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

    boxes = _boxes()
    if not boxes:
        return ("I can't see any boxes to fill in. Is the signup page open "
                "and in front?")

    labels = [_label(b) for b in boxes]

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
    domain = _domain()
    password = _make_password()

    values = {"email": email, "username": email.split("@")[0] if email else "",
              "first": first, "last": last or "", "full": name,
              "password": password, "confirm": password}

    filled, skipped, used_password = [], [], False
    for box, label in zip(boxes, labels):
        kind = _classify(label)
        if not kind:
            if label:
                skipped.append(label[:24])
            continue
        value = values.get(kind, "")
        if not value:
            skipped.append(label[:24])
            continue
        if _type_into(box, value):
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
