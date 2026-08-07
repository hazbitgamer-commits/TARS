"""TARS's black box / crash safety net. TARS.bat starts THIS instead of
main.py. If TARS's core code won't even start — which matters now that Kipp
(improve.py) rewrites core files automatically — this restores the last
known-good copies from backups/last_good/ (snapshotted by main.py after
every healthy minute of uptime) and starts TARS again.

Kipp must NEVER modify this file: it is the one piece that has to keep
working when everything else is broken.
"""
import datetime
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
LAST_GOOD = BASE / "backups" / "last_good"

# App mode (pythonw) has no terminal: stdout/stderr don't exist, and a bare
# print() would crash the engine. Route everything to logs/console.log —
# the same transcript Jacob used to copy out of the black window.
if sys.stdout is None or sys.stderr is None:
    log_path = BASE / "logs" / "console.log"
    try:
        log_path.parent.mkdir(exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > 2_000_000:
            log_path.unlink()  # rotate before it balloons
    except OSError:
        pass
    _logf = open(log_path, "a", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = sys.stdout or _logf
    sys.stderr = sys.stderr or _logf
    print(f"\n=== TARS boot {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===")


def _speak(message: str) -> None:
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.say(message)
        engine.runAndWait()
    except Exception:
        pass


def _restore() -> list[str]:
    restored = []
    for f in LAST_GOOD.glob("*.py"):
        if f.name == "boot.py":
            continue
        try:
            shutil.copy2(f, BASE / f.name)
            restored.append(f.name)
        except OSError:
            pass
    return restored


def _engine_running() -> bool:
    try:
        import urllib.request

        urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=2)
        return True
    except Exception:
        return False


def _open_window() -> None:
    """The dashboard as an app window — chromeless on Windows, default
    browser elsewhere (Mac/Linux: TARS Lite still gets his face)."""
    if sys.platform != "win32":
        import webbrowser

        webbrowser.open("http://127.0.0.1:8765")
        return
    brave = (Path(os.environ.get("LOCALAPPDATA", ""))
             / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe")
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    exe = brave if brave.exists() else edge
    try:
        subprocess.Popen([str(exe), "--app=http://127.0.0.1:8765",
                          "--window-size=1100,760"])
    except OSError:
        pass


def start() -> None:
    want_window = "--window" in sys.argv
    if want_window and _engine_running():
        # TARS is already awake — clicking the icon just opens his face,
        # never restarts the engine mid-conversation
        _open_window()
        return
    if want_window:
        import threading

        threading.Timer(7, _open_window).start()
    try:
        import main

        main.main()
        return
    except (KeyboardInterrupt, SystemExit):
        return
    except BaseException:
        print("\nTARS failed to start:\n" + traceback.format_exc())

    if os.environ.get("TARS_BOOT_RETRY") == "1":
        print("Already retried once after a rollback — stopping so nothing "
              "loops. Ask Claude for help with the error above.")
        _speak("I could not start even after rolling back. I need help.")
        return
    if not LAST_GOOD.exists() or not any(LAST_GOOD.glob("*.py")):
        _speak("I failed to start and have no backup to roll back to.")
        return

    restored = _restore()
    print(f"Rolled back {len(restored)} core files from backups/last_good.")
    _speak("One of my self upgrades broke me. I have rolled back to my last "
           "working self and I am starting again.")
    try:
        import announce

        announce.post("Heads up — one of my self-upgrades broke my start-up "
                      "earlier, so I rolled myself back to the last working "
                      "version. The bad change is preserved in the logs.",
                      hold_during_quiet=True)
    except Exception:
        pass
    env = dict(os.environ, TARS_BOOT_RETRY="1")
    subprocess.call([sys.executable, "-s", "-X", "utf8", str(BASE / "boot.py")],
                    env=env, cwd=str(BASE))


if __name__ == "__main__":
    start()
