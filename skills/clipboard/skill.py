import pyperclip

DESCRIPTION = ("Copy given text directly onto the owner's clipboard so he can paste it anywhere, "
               "or read back whatever is currently on the clipboard. "
               "E.g. 'copy my email address to the clipboard', "
               "'copy this to the clipboard: hello world', 'what's on my clipboard'. "
               "NOT for pressing a copy/paste keyboard shortcut on text already selected on "
               "screen — that's the keyboard skill.")
ARGS = {"text": "the text to place on the clipboard; or 'get'/'read' to read back what's "
                "currently on the clipboard"}


def run(args: dict) -> str:
    text = str(args.get("text", "")).strip()

    if not text or text.lower() in ("get", "read", "show", "what's on my clipboard"):
        try:
            current = pyperclip.paste()
        except Exception:
            return "I couldn't read the clipboard."
        if not current:
            return "Your clipboard is empty."
        preview = current if len(current) <= 60 else current[:57] + "..."
        return f"Your clipboard has: {preview}"

    try:
        pyperclip.copy(text)
    except Exception:
        return "I couldn't copy that to the clipboard."

    preview = text if len(text) <= 40 else text[:37] + "..."
    return f"Copied \"{preview}\" to your clipboard."
