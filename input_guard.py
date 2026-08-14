"""What must never be typed into, and where the caret currently is.

Shared by the type_text skill and the remote-control stream, because they
are the same act by different routes: something that isn't him putting
keystrokes into a window. TARS has a hard rule that he never sends messages
to people on the owner's behalf, and remote control would be a way straight
round it — a phone in a pocket typing into WhatsApp is still TARS sending a
message to a person.

Keeping the list in one file means the rule can't hold in one place and
quietly not in the other.
"""

# Windows where pressing Enter means a person receives something. Matched
# loosely against the focused window's title, and erring towards refusing:
# a missed keystroke costs one retry, a sent message can't be recalled.
MESSAGING = (
    "whatsapp", "discord", "messenger", "facebook", "instagram", "snapchat",
    "telegram", "signal", "slack", "microsoft teams", "teams", "skype",
    "messages", "imessage", "text message", "sms", "outlook", "gmail",
    "mail", "twitter", "x.com", "reddit", "tiktok", "steam chat",
)


def focused_title() -> str:
    """The front window's title, on Windows or a Mac.

    uiautomation is Windows-only, so without the fallbacks this guard simply
    didn't exist on his mate's Mac — and a guard that silently isn't there
    is worse than no guard, because you think you have one.
    """
    import sys

    if sys.platform == "win32":
        try:
            import uiautomation as auto

            return (auto.GetForegroundControl().GetTopLevelControl().Name
                    or "").lower()
        except Exception:
            pass
    if sys.platform == "darwin":
        try:
            import subprocess

            script = ('tell application "System Events" to get name of '
                      'first application process whose frontmost is true')
            out = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, timeout=5)
            return (out.stdout or "").strip().lower()
        except Exception:
            pass
    try:
        import pygetwindow

        return (pygetwindow.getActiveWindowTitle() or "").lower()
    except Exception:
        return ""


def is_messaging(title: str = None) -> bool:
    title = focused_title() if title is None else (title or "").lower()
    return any(app in title for app in MESSAGING)


def caret_in_textbox() -> bool:
    """Is the thing with focus a box you'd type into?

    Used to raise the phone's keyboard automatically when he taps a text
    field on the remote screen — the alternative is him hunting for a
    keyboard button every time.
    """
    try:
        import uiautomation as auto

        focused = auto.GetFocusedControl()
        if focused is None:
            return False
        kind = (focused.ControlTypeName or "")
        if kind in ("EditControl", "DocumentControl", "ComboBoxControl"):
            return True
        # web pages often expose the caret on a generic element instead
        try:
            pattern = focused.GetTextPattern()
            return pattern is not None
        except Exception:
            return False
    except Exception:
        return False
