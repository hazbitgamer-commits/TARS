"""File integrity checker: computes a SHA-256 checksum for a file and compares
it against the checksum recorded the last time it was checked, so TARS can
flag if the file changed or got corrupted since then. A small manifest of
known checksums is kept alongside this skill (manifest.json) and updated
automatically every time a file is checked — that's the "view integrity of
given files every time" part.
"""
import hashlib
import json
import os
import time
from pathlib import Path

DESCRIPTION = ("Check the integrity of a file by computing its SHA-256 checksum and "
               "comparing it to the checksum recorded the last time it was checked, "
               "so TARS can tell Jacob if a file changed, got corrupted, or is new. "
               "E.g. 'check the integrity of report.pdf', 'has budget.xlsx changed', "
               "'verify workshop/backup.zip'. Remembers each file's checksum between "
               "checks automatically — no setup needed.")
ARGS = {"path": ("the file to check — a name or path, relative to the workshop folder "
                  "or one of Jacob's main folders (Desktop, Documents, Downloads, "
                  "Pictures, Videos, Music), or a full absolute path")}

_SKILL_DIR = Path(__file__).resolve().parent
BASE = _SKILL_DIR.parents[1]              # C:\Users\hazbi\Projects\tars
WORKSHOP = BASE / "workshop"
MANIFEST_FILE = _SKILL_DIR / "manifest.json"
USER_ROOTS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "runtime"}
TIME_BUDGET_SEC = 6


def _load_manifest() -> dict:
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_manifest(manifest: dict) -> None:
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_file(raw: str):
    p = Path(raw)
    if p.is_absolute() and p.is_file():
        return p
    candidate = WORKSHOP / raw
    if candidate.is_file():
        return candidate
    candidate = Path.home() / raw
    if candidate.is_file():
        return candidate

    # fall back to a name search in the usual places; newest match wins
    needle = p.name.lower()
    deadline = time.time() + TIME_BUDGET_SEC
    matches = []
    for base in [WORKSHOP] + [Path.home() / r for r in USER_ROOTS]:
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
            for f in filenames:
                if needle and needle in f.lower():
                    matches.append(Path(dirpath) / f)
            if time.time() > deadline:
                break
        if time.time() > deadline:
            break
    if not matches:
        return None
    matches.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return matches[0]


def run(args: dict) -> str:
    raw = (args.get("path") or "").strip()
    if not raw:
        return "Check the integrity of which file?"

    target = _find_file(raw)
    if target is None:
        return f"I can't find a file matching {raw}."

    try:
        digest = _sha256(target)
    except OSError:
        return f"I couldn't read {target.name} to check it."

    manifest = _load_manifest()
    key = str(target.resolve())
    previous = manifest.get(key)
    manifest[key] = digest
    _save_manifest(manifest)

    if previous is None:
        return f"No earlier record of {target.name} — I've saved its checksum now as the baseline."
    if previous == digest:
        return f"{target.name} is intact — checksum still matches the last check."
    return f"Warning: {target.name} has changed since the last check — the checksum no longer matches."
