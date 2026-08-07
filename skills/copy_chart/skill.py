import io
import os

import win32clipboard
from PIL import Image

DESCRIPTION = ("Copy our most recent CHART/graph image straight onto the clipboard as a picture, "
               "ready to paste into an email, Word, or chat. E.g. 'copy our most recent chart "
               "into the clipboard', 'copy the latest chart', 'put that graph on my clipboard'. "
               "NOT for copying plain text — that's the clipboard skill.")
ARGS = {}

# Working folder first (recursive) — this is where charts TARS makes get saved.
# The rest are shallow fallbacks in case Jacob saved one himself.
_SEARCH_DIRS = [
    (r"C:\Users\hazbi\Projects\tars\workshop", True),
    (r"C:\Users\hazbi\Pictures", False),
    (r"C:\Users\hazbi\Desktop", False),
    (r"C:\Users\hazbi\Downloads", False),
    (r"C:\Users\hazbi\Documents", False),
]

_CHART_KEYWORDS = ("chart", "graph", "plot", "dashboard")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
_SKIP_DIR_NAMES = {"node_modules", ".git", "__pycache__", "github_export"}


def _iter_images(root, recursive):
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
            for name in filenames:
                if name.lower().endswith(_IMAGE_EXTS):
                    yield os.path.join(dirpath, name)
    else:
        try:
            for name in os.listdir(root):
                full = os.path.join(root, name)
                if os.path.isfile(full) and name.lower().endswith(_IMAGE_EXTS):
                    yield full
        except (FileNotFoundError, NotADirectoryError):
            return


def _find_chart():
    # Pass 1: anything whose filename hints it's a chart, newest first.
    hinted = []
    for root, recursive in _SEARCH_DIRS:
        for path in _iter_images(root, recursive):
            if any(k in os.path.basename(path).lower() for k in _CHART_KEYWORDS):
                hinted.append(path)
    if hinted:
        return max(hinted, key=os.path.getmtime)

    # Pass 2: fall back to the newest image anywhere in the working folder.
    workshop_root, _ = _SEARCH_DIRS[0]
    workshop_images = list(_iter_images(workshop_root, True))
    if workshop_images:
        return max(workshop_images, key=os.path.getmtime)

    return None


def run(args: dict) -> str:
    path = _find_chart()
    if not path:
        return "I couldn't find any chart image to copy — make one first."

    try:
        image = Image.open(path).convert("RGB")
        buf = io.BytesIO()
        image.save(buf, "BMP")
        dib = buf.getvalue()[14:]  # strip the 14-byte BMP file header, clipboard wants raw DIB
        buf.close()

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return f"I found {os.path.basename(path)} but couldn't copy it to the clipboard."

    return f"Copied the chart \"{os.path.basename(path)}\" to your clipboard — ready to paste."
