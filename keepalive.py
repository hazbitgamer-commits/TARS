"""The last line of defence: makes sure a guardian is on duty.

supervisor.py restarts the engine. Nothing used to restart the SUPERVISOR —
so if it was killed, or Windows Update rebooted the machine, or he shut the
console window, TARS stayed off until the next login.

Windows runs this every few minutes. It does almost nothing almost always:

  - a supervisor already holds its port  → do nothing (the usual case)
  - "goodbye TARS" was said on purpose   → do nothing, leave him off
  - otherwise                            → start a supervisor, silently

Deliberately tiny and dependency-free: it must be the one thing that can't
itself break. Removing the scheduled task (see doctor.py) disables it.
"""
import socket
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOCK_PORT = 8766
STOOD_DOWN = BASE / "standing_down.flag"


def guardian_on_duty() -> bool:
    """A supervisor holds 8766 for its whole life, so a refused bind means
    one is alive — no PID files, nothing to go stale."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        return False
    except OSError:
        return True
    finally:
        s.close()


def main() -> None:
    if STOOD_DOWN.exists():
        return          # he was switched off on purpose. Respect that.
    if guardian_on_duty():
        return
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    try:
        subprocess.Popen(
            [str(exe), "-s", "-X", "utf8", str(BASE / "supervisor.py")],
            cwd=str(BASE),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass


if __name__ == "__main__":
    main()
