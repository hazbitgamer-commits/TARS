import os
import time
from pathlib import Path

DESCRIPTION = ("Find files OR folders by name in Jacob's user folders (Desktop, Documents, "
               "Downloads, Pictures, Videos, Music) and optionally open the best match. "
               "Understands 'latest'/'newest' as most recent.")
ARGS = {"name": "part of the file or folder name to look for",
        "open": "'true' to open the best match, otherwise just report"}

ROOTS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]
WORKSHOP = Path(__file__).resolve().parents[2] / "workshop"  # TARS's own creations
TIME_BUDGET_SEC = 6
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "runtime"}
FILLER_WORDS = {"latest", "newest", "recent", "most", "my", "the", "a", "file", "folder"}


def run(args: dict) -> str:
    raw = (args.get("name") or "").strip().lower()
    words = [w for w in raw.split() if w not in FILLER_WORDS]
    needle = " ".join(words) if words else raw
    if not needle:
        return "Search for what, exactly?"

    deadline = time.time() + TIME_BUDGET_SEC
    matches: list[Path] = []

    for base in [WORKSHOP] + [Path.home() / r for r in ROOTS]:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
            for d in dirnames:
                if needle in d.lower():
                    matches.append(Path(dirpath) / d)
            for f in filenames:
                if needle in f.lower():
                    matches.append(Path(dirpath) / f)
            if len(matches) >= 40 or time.time() > deadline:
                break
        if len(matches) >= 40 or time.time() > deadline:
            break

    if not matches:
        return f"No files or folders matching {needle} in your main folders."

    # newest first — "open the latest screenshot" then does the right thing
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    best = matches[0]
    kind = "folder" if best.is_dir() else "file"
    if str(args.get("open", "")).lower() == "true":
        os.startfile(best)
        return f"Opening {best.name}."
    where = best.parent.name
    if len(matches) == 1:
        return f"Found one {kind}: {best.name}, in {where}."
    return (f"Found {len(matches)}. Newest is {best.name}, a {kind} in {where}. "
            "Say open it if you want it.")
