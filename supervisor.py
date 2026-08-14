"""TARS's guardian angel: runs the engine as a child, records how it dies,
and resurrects it. Exists because the engine once died NATIVELY (no Python
traceback, nothing in any log — likely the audio/driver layer) and simply
stayed dead until the owner noticed.

- clean exit (code 0 = "goodbye TARS" / power button) → supervisor stops too
- unexpected death → logs the exit code, waits 3s, relaunches
- another engine already serving :8765 → does NOT fight it, but does NOT
  leave either: it watches that engine and takes over the moment it stops
- crash loop → says so out loud, then backs off and keeps trying anyway

The watching matters. It used to stand down for good when a restart handed
the port to a newer engine — so after every "restart yourself" the engine
that was actually running had no guardian at all, and when it later died it
simply stayed dead. That is exactly how he found TARS off.

Only one supervisor may run at a time; the second one exits on the spot.
Kipp must never modify this file (same rule as boot.py).
"""
import datetime
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "logs" / "console.log"
LOCK_PORT = 8766      # held for as long as a supervisor lives
WATCH_EVERY = 20      # seconds between "is the other engine still up?" checks
COOLDOWN = 600        # after a crash loop, wait this long and try again
# "goodbye TARS" has to MEAN goodbye. This marker is how the five-minute
# keepalive knows the silence is deliberate and leaves him alone. Logging
# back in, or starting him yourself, clears it.
STOOD_DOWN = BASE / "standing_down.flag"


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


def claim_post() -> socket.socket | None:
    """One guardian only. Holding a port is an atomic claim that dies with
    the process — a lock FILE would survive a power cut and lock TARS out
    of his own watchdog forever."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def stand_watch() -> None:
    """Someone else's engine has the port. Don't fight it, don't leave —
    just wait for it to stop needing to exist."""
    log("[supervisor] a newer engine is serving — watching it instead")
    while other_engine_alive():
        time.sleep(WATCH_EVERY)
    log("[supervisor] that engine has gone — taking over")


def main() -> None:
    post = claim_post()
    if post is None:
        log("[supervisor] another guardian is already on duty — standing down")
        return

    STOOD_DOWN.unlink(missing_ok=True)   # we're on duty again
    passthrough = sys.argv[1:]
    first = True
    deaths: list[float] = []
    complained = False
    while True:
        if other_engine_alive():
            # something is already serving (a manual launch, or a restart
            # that took the port off us). Wait it out rather than starting
            # a second engine or abandoning him.
            stand_watch()
            first = False

        cmd = ([sys.executable, "-s", "-X", "utf8", str(BASE / "boot.py")]
               + (passthrough if first else []))
        first = False
        code = subprocess.run(cmd, cwd=str(BASE)).returncode
        if code == 0:
            log("[supervisor] engine exited cleanly — standing down")
            try:
                STOOD_DOWN.write_text("shut down on purpose", encoding="utf-8")
            except OSError:
                pass
            # Tell the servo on the power button that this shutdown was
            # meant. Otherwise it does exactly its job three minutes later
            # and switches the machine back on, which is correct behaviour
            # and completely against his wishes. Done here rather than in
            # the engine because the engine has already gone, releasing the
            # serial port for us to use.
            try:
                import button_finger

                if button_finger._open_and_send("D120"):
                    log("[supervisor] told the button finger to stay down")
            except Exception:
                pass
            return
        log(f"[supervisor] engine DIED, exit code {code} "
            f"({hex(code & 0xFFFFFFFF)})")
        if other_engine_alive():
            continue          # a takeover, not a death — go and watch it

        now = time.time()
        deaths = [t for t in deaths if now - t < 600] + [now]
        if len(deaths) > 3:
            log(f"[supervisor] crash loop (4 deaths in 10 min) — "
                f"backing off {COOLDOWN // 60} minutes, then trying again")
            if not complained:      # say it once, not every ten minutes
                speak("I keep crashing. I'll keep trying, but ask Claude to "
                      "look at my console log.")
                complained = True
            time.sleep(COOLDOWN)
            deaths = []
            continue
        log("[supervisor] resurrecting in 3 seconds")
        time.sleep(3)


if __name__ == "__main__":
    main()
