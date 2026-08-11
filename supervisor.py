"""TARS's guardian angel: runs the engine as a child, records how it dies,
and resurrects it. Exists because the engine once died NATIVELY (no Python
traceback, nothing in any log — likely the audio/driver layer) and simply
stayed dead until the owner noticed.

- clean exit (code 0 = "goodbye TARS" / power button) → supervisor stops too
- unexpected death → logs the exit code, waits 3s, relaunches
- another engine already serving :8765 → steps aside quietly (no wars with
  a newer instance's takeover)
- more than 3 deaths in 10 minutes → gives up loudly instead of looping
Kipp must never modify this file (same rule as boot.py).
"""
import datetime
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "logs" / "console.log"


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")
    except OSError:
        pass


def other_engine_alive() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=2)
        return True
    except Exception:
        return False


def speak(msg: str) -> None:
    try:
        import pyttsx3

        e = pyttsx3.init()
        e.say(msg)
        e.runAndWait()
    except Exception:
        pass


def main() -> None:
    passthrough = sys.argv[1:]
    first = True
    deaths: list[float] = []
    while True:
        cmd = ([sys.executable, "-s", "-X", "utf8", str(BASE / "boot.py")]
               + (passthrough if first else []))
        first = False
        code = subprocess.run(cmd, cwd=str(BASE)).returncode
        if code == 0:
            log("[supervisor] engine exited cleanly — standing down")
            return
        log(f"[supervisor] engine DIED, exit code {code} "
            f"({hex(code & 0xFFFFFFFF)})")
        if other_engine_alive():
            log("[supervisor] a newer engine is already serving — standing down")
            return
        now = time.time()
        deaths = [t for t in deaths if now - t < 600] + [now]
        if len(deaths) > 3:
            log("[supervisor] crash loop (4 deaths in 10 min) — giving up")
            speak("I keep crashing and my guardian has given up restarting "
                  "me. Ask Claude to look at the console log.")
            return
        log("[supervisor] resurrecting in 3 seconds")
        time.sleep(3)


if __name__ == "__main__":
    main()
