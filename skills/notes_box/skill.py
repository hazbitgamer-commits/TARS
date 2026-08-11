import os

DESCRIPTION = ("Open a small popup text box window on screen where the owner can type "
               "or paste text — handy since he can't paste directly into this "
               "terminal chat. Whatever he writes gets saved so TARS can read it "
               "back. E.g. 'open a notes box', 'give me somewhere to paste this', "
               "'let me write you something'. NOT for typing into another app "
               "(that's the type_text skill) — this opens its own little window.")
ARGS = {"text": ("optional — if given, skips the popup and directly saves this "
                  "text. Leave it out to open the popup box for typing/pasting.")}

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.normpath(os.path.join(_SKILL_DIR, "..", "..", "notes"))
LATEST_FILE = os.path.join(NOTES_DIR, "latest_note.txt")


def _save_note(text: str) -> str:
    os.makedirs(NOTES_DIR, exist_ok=True)
    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    return LATEST_FILE


def _open_popup() -> str:
    import tkinter as tk

    result = {"text": ""}
    root = tk.Tk()
    root.title("Notes for TARS")
    root.geometry("480x340")
    root.attributes("-topmost", True)

    tk.Label(root, text="Type or paste your text below, then click Save.").pack(pady=6)

    text_box = tk.Text(root, wrap="word")
    text_box.pack(fill="both", expand=True, padx=8, pady=4)
    text_box.focus_set()

    def save_and_close():
        result["text"] = text_box.get("1.0", "end-1c")
        root.destroy()

    tk.Button(root, text="Save & Close", command=save_and_close).pack(pady=6)
    root.protocol("WM_DELETE_WINDOW", save_and_close)
    root.bind("<Control-Return>", lambda e: save_and_close())

    root.mainloop()
    return result["text"]


def run(args: dict) -> str:
    text = args.get("text")
    if text:
        text = str(text).strip()
    else:
        text = _open_popup().strip()

    if not text:
        return "The notes box was closed but nothing was written."

    _save_note(text)
    preview = text if len(text) <= 60 else text[:57] + "..."
    return f"Got it, saved: {preview}"
