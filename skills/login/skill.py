"""Type the owner's username and password into the login form on screen.

The password comes out of Windows Credential Manager, filed under the site's
domain — which is also the safety mechanism. TARS looks up the credential by
the domain currently in the address bar, so a password saved for one site
physically cannot be typed into another. A convincing fake login page gets
nothing, because nothing is stored against that fake domain.

It fills the boxes and stops. It does not press Sign In — that's one keypress
for him and it means a mis-read page can never actually submit his password
somewhere. Password managers work the same way for the same reason.

Logins get saved either by the signup skill (when TARS invented the password
itself) or by hand on the setup page.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LOGINS = BASE / "logins.json"     # usernames only — passwords are in the vault

DESCRIPTION = ("LOG IN to the website that's open on screen — types the "
               "saved username and password into the login form. E.g. 'log "
               "me in', 'sign me in here', 'fill in my login'. Also 'what "
               "logins do you have' to list the sites he knows. He never "
               "presses the sign-in button himself, and he can only fill a "
               "password into the site it was saved for. NOT for creating a "
               "new account (that's signup).")
ARGS = {"action": "'list' to hear which sites he has logins for"}


def _usernames() -> dict:
    try:
        return json.loads(LOGINS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _known_sites() -> list:
    """Sites with a stored password. Names only — never values."""
    try:
        import secrets_store

        return sorted(n[len("site:"):] for n in secrets_store.names()
                      if n.startswith("site:"))
    except Exception:
        return []


def run(args: dict) -> str:
    if str(args.get("action") or "").strip().lower() in ("list", "which", "what"):
        sites = _known_sites()
        if not sites:
            return ("I haven't got any logins saved yet. Add them on the "
                    "setup page and I'll fill them in for you.")
        return f"I've got logins for: {', '.join(sites)}."

    try:
        import uiautomation  # noqa: F401
    except ImportError:
        return "I can't read forms on this computer — uiautomation isn't installed."

    import secrets_store
    import webforms

    site = webforms.domain()
    if not site:
        return ("I can't tell which site that is — I need the browser in "
                "front with the address bar visible.")

    password = secrets_store.use(f"site:{site}")
    if not password:
        known = _known_sites()
        extra = f" I do have: {', '.join(known)}." if known else ""
        return (f"I haven't got a login saved for {site}.{extra} Add it on "
                f"the setup page and I'll fill it in next time.")

    fields = webforms.boxes()
    if not fields:
        return "I can't see any boxes to fill in. Is the login form on screen?"

    username = _usernames().get(site, "")
    filled = []
    for box in fields:
        kind = webforms.classify(webforms.label(box))
        if kind == "password":
            if webforms.type_into(box, password):
                filled.append("password")
        elif kind in ("username", "email") and username:
            if webforms.type_into(box, username):
                filled.append("username")

    if "password" not in filled:
        return (f"I found the page for {site} but couldn't find the password "
                f"box — it isn't labelling it in a way I can read.")

    who = "username and password" if "username" in filled else "password"
    return (f"Filled in your {who} for {site}. I haven't pressed sign in — "
            f"check it and hit enter yourself.")
