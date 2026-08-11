"""Keeps the Downloads folder from turning into a landfill: files that have
finished downloading get moved into a folder for their type. MOVES ONLY —
nothing is ever deleted or overwritten, every move is written down, and
"undo the filing" puts the whole lot back exactly where it was.

Ticked from main's standby loop. Deliberately quiet: it doesn't announce
anything, it just tidies, and tells the owner what it did when he asks."""
import json
import shutil
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "downloads_moves.json"
DOWNLOADS = Path.home() / "Downloads"

# a file is only touched once it's been still for this long — a part-written
# download must never be moved out from under the browser
SETTLE = 180        # seconds since last modification
CHECK_EVERY = 900   # 15 minutes

FOLDERS = {
    "Installers": {".exe", ".msi", ".msix", ".appx"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
               ".heic", ".ico"},
    "Documents": {".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".pptx",
                  ".xlsx", ".xls", ".csv", ".epub"},
    "Video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"},
    "Music": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".sh", ".bat",
             ".ps1", ".lua", ".java", ".c", ".cpp", ".rs", ".go"},
    "3D Prints": {".stl", ".3mf", ".scad", ".obj", ".gcode"},
}
# never touched: still downloading, or Windows' own business
SKIP_SUFFIX = {".crdownload", ".part", ".partial", ".tmp", ".ini"}

_last_check = 0.0


def _folder_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in SKIP_SUFFIX or not suffix:
        return None
    for folder, suffixes in FOLDERS.items():
        if suffix in suffixes:
            return folder
    return None  # unknown type — leave it alone rather than guess


def _log(moves: list[dict]) -> None:
    try:
        data = json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"moves": []}
    data["moves"] = (data.get("moves", []) + moves)[-500:]
    try:
        LOG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _unique(dest: Path) -> Path:
    """Never overwrite. 'setup.exe' meeting another 'setup.exe' becomes
    'setup (2).exe' — the same thing Windows itself does."""
    if not dest.exists():
        return dest
    stem, suffix, n = dest.stem, dest.suffix, 2
    while True:
        candidate = dest.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def file_now(dry_run: bool = False) -> list[dict]:
    """Do one pass. Returns the moves made (or that would be made)."""
    if not DOWNLOADS.is_dir():
        return []
    moves = []
    now = time.time()
    for item in DOWNLOADS.iterdir():
        if not item.is_file() or item.name.startswith("."):
            continue
        folder = _folder_for(item)
        if not folder:
            continue
        try:
            if now - item.stat().st_mtime < SETTLE:
                continue  # still arriving, or he's just saved it
        except OSError:
            continue
        target_dir = DOWNLOADS / folder
        dest = _unique(target_dir / item.name)
        if dry_run:
            moves.append({"from": str(item), "to": str(dest)})
            continue
        try:
            target_dir.mkdir(exist_ok=True)
            shutil.move(str(item), str(dest))
        except OSError:
            continue  # in use by another program — try again next tick
        moves.append({"from": str(item), "to": str(dest), "t": now})
    if moves and not dry_run:
        _log(moves)
    return moves


def undo(hours: float = 24) -> str:
    """Put everything filed in the last <hours> back where it came from."""
    try:
        data = json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "I've not filed anything yet."
    cutoff = time.time() - hours * 3600
    recent = [m for m in data.get("moves", []) if m.get("t", 0) > cutoff]
    if not recent:
        return "Nothing's been filed recently, so there's nothing to undo."
    back, missing = 0, 0
    for move in reversed(recent):
        source, dest = Path(move["to"]), Path(move["from"])
        if not source.exists():
            missing += 1
            continue
        try:
            shutil.move(str(source), str(_unique(dest)))
            back += 1
        except OSError:
            missing += 1
    data["moves"] = [m for m in data.get("moves", []) if m.get("t", 0) <= cutoff]
    try:
        LOG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
    tail = f" {missing} had already been moved elsewhere." if missing else ""
    return f"Put {back} files back in Downloads.{tail}"


def recent(hours: float = 24) -> list[dict]:
    try:
        data = json.loads(LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cutoff = time.time() - hours * 3600
    return [m for m in data.get("moves", []) if m.get("t", 0) > cutoff]


def enabled() -> bool:
    try:
        return json.loads((BASE / "settings.json").read_text(
            encoding="utf-8")).get("file_downloads", True)
    except (OSError, json.JSONDecodeError):
        return True


def tick() -> None:
    """Called from the standby loop. Cheap: a directory listing every 15
    minutes, and only when the owner isn't mid-conversation."""
    global _last_check
    if not enabled() or time.time() - _last_check < CHECK_EVERY:
        return
    _last_check = time.time()
    try:
        file_now()
    except Exception:
        pass
