"""Type into the focused window, and — when asked — press Enter to send it.

Sending is separate from typing on purpose. TARS has a hard rule that he
never sends messages to people on the owner's behalf, and "press Enter in
whatever happens to be focused" would drive straight through it: the same
keystroke that submits a prompt to Claude sends a WhatsApp message to a
human being.

So Enter is refused outright when the focused window is a messaging app.
Not a warning, not a confirmation he could tire of and wave through — a
refusal, checked against the window in front at the moment it would happen.
"""
import time

import pyautogui

DESCRIPTION = ("Type text into whatever window is focused, and optionally "
               "press Enter to submit it. E.g. 'type hello there', 'ask "
               "Claude what a for loop is', 'type that in and send it', "
               "'put this in the chat box and hit enter'. Submits to apps "
               "like Claude, ChatGPT, a search box or a terminal — but NEVER "
               "sends a message to a person in WhatsApp, Discord, Messenger "
               "or similar.")
ARGS = {"text": "the exact text to type",
        "send": "'true' to press Enter afterwards (submit it), otherwise it "
                "just types and leaves the cursor there"}

# Windows where pressing Enter means "a person receives this". The list is
# matched loosely against the focused window's title, and errs towards
# refusing: a missed submission costs one keypress, a wrong one can't be
# taken back.
MESSAGING = (
    "whatsapp", "discord", "messenger", "facebook", "instagram", "snapchat",
    "telegram", "signal", "slack", "microsoft teams", "teams", "skype",
    "messages", "imessage", "text message", "sms", "outlook", "gmail",
    "mail", "twitter", "x.com", "reddit", "tiktok", "steam chat",
)


def _focused_window() -> str:
    try:
        import uiautomation as auto

        return (auto.GetForegroundControl().GetTopLevelControl().Name
                or "").lower()
    except Exception:
        try:
            return (pyautogui.getActiveWindowTitle() or "").lower()
        except Exception:
            return ""


def _is_messaging(title: str) -> bool:
    return any(app in title for app in MESSAGING)


def run(args: dict) -> str:
    text = args.get("text") or ""
    if not text:
        return "Type what, exactly?"
    send = str(args.get("send", "")).strip().lower() in ("true", "yes", "1",
                                                         "send", "enter")
    time.sleep(0.6)  # give focus a beat to settle after the voice command

    if send:
        window = _focused_window()
        if _is_messaging(window):
            # type it, but do NOT press enter — he can send it himself if
            # that's really what he wants
            pyautogui.write(text, interval=0.02)
            return ("Typed it, but I won't press enter in a messaging app — "
                    "I don't send messages to people for you. Hit enter "
                    "yourself if that's what you want.")

    pyautogui.write(text, interval=0.02)
    if not send:
        return "Typed."
    pyautogui.press("enter")
    return "Typed and sent."
