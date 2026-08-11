"""Backups by voice — 'back yourself up', 'when was your last backup',
'test the backup'. Protects the irreplaceable half of TARS: the owner's vault,
his designs, learned faces and voices, routines and lists."""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

DESCRIPTION = ("BACK UP TARS's irreplaceable data — the owner's memories, "
               "designs, learned faces and voices, routines and lists. "
               "'back yourself up', 'when was your last backup', 'test the "
               "backup' (proves it restores). NOT for uploading his code "
               "(github_publish).")
ARGS = {"action": "'run' (default), 'status', or 'verify'"}


def run(args: dict) -> str:
    import backup

    action = str(args.get("action") or "run").strip().lower()
    if action in ("status", "when", "last"):
        return backup.status()
    if action in ("verify", "test", "check", "drill"):
        return backup.verify()
    return backup.run_backup()
