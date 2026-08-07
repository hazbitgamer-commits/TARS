"""Voice file organizer: "move the screenshots from downloads into a
folder called Basel." MOVES only — never deletes, never overwrites
(collisions get a numbered suffix), and only inside Jacob's own user
folders. Big moves (>20 files) require a spoken yes via the same confirm
flow as deletion."""
import shutil
from pathlib import Path

HOME = Path.home()
ROOTS = {"downloads": HOME / "Downloads", "desktop": HOME / "Desktop",
         "documents": HOME / "Documents", "pictures": HOME / "Pictures",
         "videos": HOME / "Videos", "music": HOME / "Music"}
KINDS = {"screenshot": ("*.png", "*.jpg"), "picture": ("*.png", "*.jpg",
         "*.jpeg", "*.gif"), "photo": ("*.png", "*.jpg", "*.jpeg"),
         "video": ("*.mp4", "*.mkv", "*.mov"), "document": ("*.pdf",
         "*.docx", "*.txt"), "pdf": ("*.pdf",), "installer": ("*.exe",
         "*.msi"), "zip": ("*.zip", "*.7z", "*.rar")}

DESCRIPTION = ("ORGANIZE files by voice — move files matching a "
               "description from one of Jacob's folders into a (new or "
               "existing) folder: 'move the screenshots from downloads "
               "into a folder called Setup', 'put the PDFs on my desktop "
               "into Documents'. Only MOVES within Jacob's own folders — "
               "never deletes. NOT for finding/opening files "
               "(search_files) and NOT for deleting (delete_files).")
ARGS = {"what": "which files: 'screenshots', 'pdfs', 'videos', or a "
                 "name fragment like 'basel'",
        "source": "folder to take them from: downloads/desktop/documents/"
                  "pictures/videos",
        "dest": "destination folder name (created if needed), e.g. "
                "'a folder called Setup' -> 'Setup'",
        "confirmed": "'true' only when Jacob already said yes to a big move"}


def _match(src: Path, what: str) -> list[Path]:
    what_l = what.lower().rstrip("s")
    patterns = None
    for kind, pats in KINDS.items():
        if kind in what_l:
            patterns = pats
            break
    files = []
    if patterns:
        for p in patterns:
            files += [f for f in src.glob(p) if f.is_file()]
        if "screenshot" in what_l:
            files = [f for f in files if "screen" in f.name.lower()]
    else:
        files = [f for f in src.iterdir()
                 if f.is_file() and what_l in f.name.lower()]
    return sorted(set(files))[:200]


def run(args: dict) -> str:
    what = str(args.get("what", "")).strip()
    source = str(args.get("source", "downloads")).strip().lower()
    dest_name = str(args.get("dest", "")).strip().strip('"')
    if not what or not dest_name:
        return "Tell me what to move and what to call the folder."

    src = next((v for k, v in ROOTS.items() if k in source), None)
    if src is None or not src.exists():
        return f"I only organize inside your own folders — {source} isn't one I know."

    files = _match(src, what)
    if not files:
        return f"No files matching {what} in {src.name}."

    if len(files) > 20 and str(args.get("confirmed", "")).lower() != "true":
        return (f"__CONFIRM__organize:{what}|{source}|{dest_name}__That's "
                f"{len(files)} files from {src.name} into {dest_name} — "
                f"say yes to move them.")

    dest = src / dest_name
    dest.mkdir(exist_ok=True)
    moved = 0
    for f in files:
        target = dest / f.name
        n = 1
        while target.exists():  # never overwrite — number the copy instead
            target = dest / f"{f.stem} ({n}){f.suffix}"
            n += 1
        try:
            shutil.move(str(f), str(target))
            moved += 1
        except OSError:
            continue
    return (f"Moved {moved} file{'s' if moved != 1 else ''} into "
            f"{src.name}\\{dest_name}. Nothing deleted, nothing overwritten.")
