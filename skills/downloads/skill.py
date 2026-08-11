"""Voice control for the Downloads auto-filer: what got filed, tidy it now,
put it back, or turn the whole thing off."""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]

DESCRIPTION = ("The DOWNLOADS folder tidy-up — 'what have you filed', 'tidy "
               "my downloads', 'undo the filing / put my downloads back', "
               "'stop filing my downloads'. Sorts finished downloads into "
               "Installers, Images, Documents, Video, Music, Archives, Code "
               "and 3D Prints. Only ever MOVES files inside Downloads. NOT "
               "for moving other folders (organize) and NOT for deleting "
               "anything (delete_files).")
ARGS = {"action": "'status' (default), 'now', 'undo', 'off', or 'on'"}


def _watch():
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    import downloads_watch

    return downloads_watch


def _setting(value: bool) -> None:
    path = BASE / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data["file_downloads"] = value
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _summarise(moves: list[dict]) -> str:
    counts: dict[str, int] = {}
    for move in moves:
        folder = Path(move["to"]).parent.name
        counts[folder] = counts.get(folder, 0) + 1
    return ", ".join(f"{n} into {folder}" for folder, n in
                     sorted(counts.items(), key=lambda kv: -kv[1]))


def run(args: dict) -> str:
    watch = _watch()
    action = str(args.get("action") or "status").strip().lower()

    if action in ("off", "stop", "disable", "pause"):
        _setting(False)
        return "Downloads filing is off. Nothing more gets moved."
    if action in ("on", "start", "enable", "resume"):
        _setting(True)
        return "Downloads filing is back on."
    if action in ("undo", "revert", "back", "restore"):
        return watch.undo()
    if action in ("now", "run", "tidy", "file", "sort"):
        if not watch.enabled():
            return "Filing is switched off — say turn on downloads filing first."
        moves = watch.file_now()
        if not moves:
            waiting = watch.file_now(dry_run=True)
            if waiting:
                return "Nothing ready yet — new downloads sit for a few minutes first."
            return "Downloads is already tidy."
        return f"Filed {len(moves)} files: {_summarise(moves)}."

    # status
    if not watch.enabled():
        return "Downloads filing is switched off."
    moves = watch.recent(24)
    if not moves:
        return "Nothing filed in the last day. Downloads is tidy."
    names = [Path(m["from"]).name for m in moves[-3:]]
    return (f"Filed {len(moves)} files today: {_summarise(moves)}. "
            f"Most recent: {', '.join(names)}. Say put them back to undo it.")
