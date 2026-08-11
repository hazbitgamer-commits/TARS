"""Guarded deletion: finds the folder/files the owner means, requires his spoken
'yes' (managed by the brain), and always uses the Recycle Bin — never permanent.
"""
from pathlib import Path

from send2trash import send2trash

DESCRIPTION = ("Delete files or a folder's contents — ALWAYS requires the owner's spoken "
               "confirmation first, and everything goes to the Recycle Bin. "
               "E.g. 'delete all screenshots in the TARS folder'.")
ARGS = {"target": "which folder or files to delete, in the owner's words",
        "confirmed": "leave empty — the brain sets 'true' only after the owner says yes"}

BASE = Path(__file__).resolve().parents[2]
ROOTS = [BASE / "workshop"] + [Path.home() / r for r in
         ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
FILLER = {"the", "a", "my", "all", "everything", "in", "inside", "folder", "file",
          "files", "screenshots", "screenshot", "that", "contents", "of",
          "pictures", "desktop", "documents", "downloads", "videos", "music"}


def _norm(s: str) -> str:
    return s.lower().replace("_", " ").replace("-", " ")


def _find_folder(target: str) -> Path | None:
    words = [w for w in _norm(target).split() if w not in FILLER]
    if not words:
        words = _norm(target).split()
    if not words:
        return None
    for root in ROOTS:
        if not root.exists():
            continue
        if all(w in _norm(root.name) for w in words):
            return root
        for p in root.rglob("*"):
            if p.is_dir() and all(w in _norm(p.name) for w in words):
                return p
    return None


def run(args: dict) -> str:
    target = (args.get("target") or "").strip()
    if not target:
        return "Delete what, exactly?"
    as_path = Path(target)
    if as_path.is_absolute() and as_path.is_dir():
        folder = as_path  # the confirmed round-trip passes the exact path
    else:
        folder = _find_folder(target)
    if folder is None:
        return f"I can't find a folder matching {target}."
    items = list(folder.iterdir())
    if not items:
        return f"{folder.name} is already empty."

    if str(args.get("confirmed", "")).lower() != "true":
        # the brain turns this into a pending confirmation
        return (f"__CONFIRM__{folder}__That's {len(items)} item"
                f"{'s' if len(items) != 1 else ''} in {folder.name}. "
                "Deleting is on my hard-block list — say yes if you're sure, "
                "and they go to the Recycle Bin.")

    failed = 0
    for item in items:
        try:
            send2trash(str(item))
        except Exception:
            failed += 1
    done = len(items) - failed
    note = f" {failed} wouldn't budge." if failed else ""
    return f"Done — {done} item{'s' if done != 1 else ''} moved to the Recycle Bin.{note}"
