"""TARS backs himself up — the parts that can't be rebuilt.

His code is on GitHub, but the owner's VAULT (every memory and conversation),
his DESIGNS, the faces and voices TARS has learned, routines, lists and
ideas exist in exactly one place on one disk. This makes a nightly zip and
puts it in OneDrive when it's there, so a dead drive costs nothing.

A backup nobody has restored isn't a backup: verify() opens the newest
archive, checks the important files are readable, and reports honestly.
"""
import datetime
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE = BASE / "backup_state.json"
KEEP = 7  # nightly archives to keep

# what's irreplaceable — deliberately NOT the code (that's on GitHub) or
# the models/runtime (hundreds of megabytes, re-downloadable)
FOLDERS = ("vault", "workshop/designs", "faces", "notes")
FILES = ("routines.json", "lists.json", "ideas.json", "settings.json",
         "voices.json", "recurring.json", "quiet_hours.json",
         "vacuum_nickname.txt", "voice_settings.json", "audio_out.json",
         "brain_neurons.json", "brain_synapses.json", "improve_state.json",
         "search_memory.json", "work_queue.json", "guest_mode.json",
         # who owns this copy — name, city, school logins. Backed up so a
         # reinstall doesn't mean typing it all again; never published.
         "profile.json", "school.json", "seqta_cache.json",
         "study_progress.json", "known_games.json")


def destination() -> Path:
    """OneDrive if it exists (that's offsite for free), else Documents."""
    onedrive = Path(os.environ.get("OneDrive", "")) if os.environ.get("OneDrive") \
        else Path.home() / "OneDrive"
    root = onedrive if onedrive.exists() else Path.home() / "Documents"
    out = root / "TARS Backups"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


def run_backup() -> str:
    dest = destination()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    archive = dest / f"tars_backup_{stamp}.zip"
    count = 0
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for folder in FOLDERS:
                src = BASE / folder
                if not src.exists():
                    continue
                for p in src.rglob("*"):
                    if p.is_file() and ".obsidian" not in p.parts:
                        z.write(p, str(Path(folder) / p.relative_to(src)))
                        count += 1
            for name in FILES:
                p = BASE / name
                if p.exists():
                    z.write(p, name)
                    count += 1
    except OSError as e:
        return f"The backup couldn't be written: {e}"

    for old in sorted(dest.glob("tars_backup_*.zip"))[:-KEEP]:
        try:
            old.unlink()
        except OSError:
            pass

    size = archive.stat().st_size / 1e6
    state = _state()
    state.update(last=time.time(), file=str(archive), files=count,
                 mb=round(size, 1))
    _save(state)
    where = "OneDrive" if "onedrive" in str(dest).lower() else str(dest)
    return (f"Backed up {count} files, {size:.1f} megabytes, to {where}.")


def verify() -> str:
    """The restore drill — prove the newest archive actually restores."""
    dest = destination()
    archives = sorted(dest.glob("tars_backup_*.zip"))
    if not archives:
        return "There's no backup to test yet."
    newest = archives[-1]
    import tempfile

    try:
        with zipfile.ZipFile(newest) as z:
            bad = z.testzip()
            if bad:
                return f"The backup is damaged at {bad} — I'd make a new one."
            names = z.namelist()
            with tempfile.TemporaryDirectory() as tmp:
                sample = [n for n in names
                          if n.endswith((".json", ".md"))][:25]
                for n in sample:
                    z.extract(n, tmp)
                ok = 0
                for n in sample:
                    p = Path(tmp) / n
                    if not p.exists() or p.stat().st_size == 0:
                        continue
                    if n.endswith(".json"):
                        json.loads(p.read_text(encoding="utf-8"))
                    ok += 1
    except Exception as e:
        return f"The restore test failed: {type(e).__name__} — tell Claude."
    vault = sum(1 for n in names if n.startswith("vault/"))
    designs = sum(1 for n in names if "designs" in n and n.endswith(".stl"))
    age = datetime.datetime.fromtimestamp(newest.stat().st_mtime)
    return (f"Restore test passed: {len(names)} files including {vault} "
            f"memories and {designs} printable designs, {ok} spot-checked "
            f"and readable. Newest backup is from {age:%d %B, %H:%M}.")


def status() -> str:
    s = _state()
    if not s.get("last"):
        return "I haven't backed up yet — say 'back yourself up' and I will."
    when = datetime.datetime.fromtimestamp(s["last"])
    hours = (time.time() - s["last"]) / 3600
    return (f"Last backup {when:%d %B at %H:%M} ({hours:.0f} hours ago): "
            f"{s.get('files', '?')} files, {s.get('mb', '?')} megabytes, in "
            f"{'OneDrive' if 'onedrive' in s.get('file','').lower() else 'Documents'}.")


_last_tick = 0.0


def tick() -> None:
    """Nightly, from the standby loop — quiet unless something's wrong."""
    global _last_tick
    if time.time() - _last_tick < 900:
        return
    _last_tick = time.time()
    s = _state()
    if time.time() - s.get("last", 0) < 20 * 3600:
        return
    if datetime.datetime.now().hour < 2:   # small hours: PC is usually idle
        return

    import threading

    def worker():
        try:
            said = run_backup()
            s2 = _state()
            s2["last_message"] = said
            _save(s2)
            print(f"(backup: {said})")
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()
