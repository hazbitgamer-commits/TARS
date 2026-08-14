"""Reading and filling the form that's on screen.

Shared by the signup filler and the login filler, because they need exactly
the same three things: find the boxes, work out what each one is for, and
type into it. Written once so that when a browser update breaks the way
pages expose their fields, there's one place to fix.

Nothing here presses, ticks or submits anything. There is deliberately no
function in this file that can — the two skills that use it stop at typing,
and keeping the capability absent is stronger than remembering not to call
it.
"""
import re
import time

# What each box is, most specific first: "confirm password" has to beat
# "password", or the second box gets treated as the first.
KINDS = [
    ("confirm", ("confirm password", "repeat password", "re enter password",
                 "retype password", "password again", "confirm your password")),
    ("password", ("password", "passphrase", "choose a password")),
    ("email", ("email", "e mail", "email address")),
    ("first", ("first name", "given name", "forename")),
    ("last", ("last name", "surname", "family name")),
    ("username", ("username", "user name", "display name", "nickname",
                  "handle", "screen name", "user id", "login")),
    ("full", ("full name", "your name", "name")),
]


def flatten(text: str) -> str:
    """Punctuation out, single spaces in — applied to labels AND patterns
    alike. Matching a hyphenated pattern against de-hyphenated text is how
    "re-enter password" got mistaken for the first password box."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split())


_KINDS_FLAT = [(kind, tuple(flatten(w) for w in words)) for kind, words in KINDS]


def classify(label: str) -> str:
    low = flatten(label)
    for kind, words in _KINDS_FLAT:
        if any(w in low for w in words):
            return kind
    return ""


def label(control) -> str:
    """What a box calls itself. Falls through the properties websites
    actually populate — plenty leave Name empty and only set a placeholder
    or the help text."""
    for attr in ("Name", "AutomationId", "HelpText"):
        try:
            value = (getattr(control, attr, "") or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return ""


def domain() -> str:
    """Which site is on screen, from the browser's address bar. This is what
    a stored password is filed under, so it's also what stops a password
    ever being typed into the wrong site."""
    try:
        import uiautomation as auto

        win = auto.GetForegroundControl().GetTopLevelControl()
        for name in ("Address and search bar", "Address bar",
                     "Search or enter address"):
            bar = win.EditControl(Name=name)
            if bar.Exists(1, 0.1):
                url = (bar.GetValuePattern().Value or "").strip()
                m = (re.search(r"https?://([^/]+)", url)
                     or re.match(r"([\w.-]+\.\w+)", url))
                if m:
                    return m.group(1).lower().replace("www.", "")
    except Exception:
        pass
    return ""


def boxes():
    """Every text box on the page, in reading order."""
    try:
        import uiautomation as auto
    except ImportError:
        return []

    win = auto.GetForegroundControl().GetTopLevelControl()
    # Chromium hides the page's elements until an accessibility client pokes
    # the document — the same wake-up the fast clicker needs
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


def type_into(control, text: str) -> bool:
    try:
        import uiautomation as auto

        control.SetFocus()
        auto.SendKeys("{Ctrl}a", waitTime=0)      # replace, don't append
        auto.SendKeys(text, waitTime=0)
        return True
    except Exception:
        return False
