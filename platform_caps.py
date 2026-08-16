"""Where am I running? — TARS's platform awareness (Phase 1 of universal
TARS, 2026-08-07, target: the owner's mate's MacBook).

Windows = the full body. Mac/Linux = TARS Lite: the complete thinking
stack (Ollama chat/routing, Whisper hearing, Kokoro voice, dashboard,
timers/lists/weather/web/Telegram) minus the Windows-only hands.
Skills whose libraries don't exist off-Windows already remove themselves
(skills_engine skips failed imports); BLOCKED_OFF_WINDOWS catches the
rest — ones that import fine anywhere but can only DO on Windows.
"""
import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
# Lite = reduced body. Automatic off-Windows; TARS_LITE=1 forces it on
# Windows so Lite mode can be TESTED here before shipping to the MacBook.
LITE = (not IS_WINDOWS) or os.environ.get("TARS_LITE") == "1"

PLATFORM_NAME = ("Windows" if IS_WINDOWS else
                 "macOS" if IS_MAC else
                 "Linux" if IS_LINUX else sys.platform)

# skills that import happily everywhere but are Windows-only in practice
BLOCKED_OFF_WINDOWS = {
    "open_app", "close_app", "close_window", "manage_window", "list_windows",
    "steam", "lock_pc", "run_command", "screenshot", "screen_check",
    "brightness", "look_at_screen", "click_screen", "screen_task", "tabs",
    # camera_feed and signals stay AVAILABLE off Windows: the HUD is a web
    # page and hand signals need only mediapipe + the webcam (~200MB), not
    # the 6GB vision model. "camera" (what can you see) does need it, so it
    # stays blocked on 16GB Lite machines.
    "camera", "face_learn", "face_who", "object_detection",
    "voice_output", "delete_files", "organize", "type_text", "keyboard",
    "media", "dictation", "vacuum", "vacuum_room", "vacuum_speed",
    "speakers", "quiet_hours",
    "notes_box",  # Tk popup — same NSException risk on macOS as the pill
}


def blocked_skills() -> set:
    return BLOCKED_OFF_WINDOWS if LITE else set()


# Raised from qwen2.5:7b at his request: he has 34GB of RAM and a 14B model
# already installed, and wanted the better answers. The cost is real and
# worth stating — measured warm on his PC, 7B answers in about 0.4s and this
# one in about 2.2s. The per-question router is what makes that bearable:
# "what time is it" still goes to the 3B, so the slow model is only paying
# its way on questions that actually need it.
CHAT_MODEL = "qwen3:14b"


def total_ram_gb() -> float:
    """How much memory this machine actually has. Model choice was fixed at
    7B + 3B for every Lite machine, which is fine on a 16GB M4 and grinds an
    8GB Mac to a halt — reported as "lags out my computer" and "doesn't
    respond every time"."""
    try:
        import psutil

        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        pass
    try:  # psutil missing: ask the OS directly
        import subprocess

        if IS_MAC:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / (1024 ** 3)
        if IS_LINUX:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / (1024 ** 2)
    except Exception:
        pass
    return 16.0  # unknown: assume roomy rather than cripple a good machine


def tight_on_memory() -> bool:
    """Under ~12GB there isn't room for a 7B model plus the OS plus a
    browser, and everything else on the machine suffers."""
    return LITE and total_ram_gb() < 12


def chat_model() -> str:
    return "qwen2.5:3b" if tight_on_memory() else CHAT_MODEL


def bg_model() -> str:
    """Background-thinking model. Windows (16GB GPU) affords the smarter
    qwen3:8b as a third resident model; Lite machines (MacBook unified
    memory) reuse the ONE chat model — three residents at once swamped an
    M4 into system-wide lag."""
    return chat_model() if LITE else "qwen3:8b"


def router_model() -> str:
    """Windows runs a second instance of the chat model so router and chat
    keep separate prompt caches (2x latency win there). Lite v2: a NIMBLE
    3B routes — the routing step is the felt latency on every command, and
    the deterministic hard gates catch what a small router fumbles.
    (7B chat + 3B router ≈ 7.5GB resident — comfortable in 16GB.)
    On a tight machine chat is ALSO the 3B, so they share one model and
    only ~2GB is resident in total."""
    return "qwen2.5:3b" if LITE else "qwen2.5:7b-router"


def python_cmd(base: Path | None = None) -> str:
    """The right Python for running/testing code on THIS platform —
    Windows uses TARS's private runtime, elsewhere it's whatever
    interpreter TARS itself runs on (the venv)."""
    if IS_WINDOWS and base is not None:
        return str(base / "runtime" / "python.exe")
    exe = sys.executable or "python3"
    return exe.replace("pythonw.exe", "python.exe")


# ---------- the small cross-platform primitives ----------
# Written once here rather than re-guessed in every skill: os.startfile is
# Windows-only and throws AttributeError on a Mac, which is how half the
# "naked" skills would have crashed on the owner's mates' machines.

def open_file(path) -> bool:
    """Open a file or folder in whatever the OS uses for it."""
    import subprocess

    target = str(path)
    try:
        if IS_WINDOWS:
            os.startfile(target)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        return False


def browser_exe() -> str:
    """Path/command for a Chromium browser that supports --app windows."""
    candidates = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            Path(local) / "BraveSoftware/Brave-Browser/Application/brave.exe",
            Path(r"C:\Program Files\BraveSoftware\Brave-Browser"
                 r"\Application\brave.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application"
                 r"\msedge.exe"),
        ]
    elif IS_MAC:
        candidates = [
            Path("/Applications/Brave Browser.app/Contents/MacOS/"
                 "Brave Browser"),
            Path("/Applications/Google Chrome.app/Contents/MacOS/"
                 "Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/"
                 "Microsoft Edge"),
        ]
    else:
        for name in ("brave-browser", "google-chrome", "chromium"):
            import shutil as _sh

            found = _sh.which(name)
            if found:
                return found
    for exe in candidates:
        if exe.exists():
            return str(exe)
    return ""


def browser_data_dirs() -> list:
    """Where Chromium browsers keep their profiles — used by history
    search, which was reading %LOCALAPPDATA% and finding nothing on Mac."""
    home = Path.home()
    if IS_WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        return [local / "BraveSoftware/Brave-Browser/User Data",
                local / "Google/Chrome/User Data",
                local / "Microsoft/Edge/User Data"]
    if IS_MAC:
        support = home / "Library/Application Support"
        return [support / "BraveSoftware/Brave-Browser",
                support / "Google/Chrome",
                support / "Microsoft Edge"]
    return [home / ".config/BraveSoftware/Brave-Browser",
            home / ".config/google-chrome",
            home / ".config/chromium"]


def camera_backend():
    """cv2 capture backend for this OS. DirectShow on Windows (MSMF can't
    grab on the owner's webcam); AVFoundation on Mac; default elsewhere."""
    try:
        import cv2
    except Exception:
        return None
    if IS_WINDOWS:
        return cv2.CAP_DSHOW
    if IS_MAC:
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def unavailable(feature: str) -> str:
    """A spoken, honest 'not on this machine' line — said instead of
    letting chat improvise around a missing ability."""
    where = "this Mac" if IS_MAC else PLATFORM_NAME
    if IS_WINDOWS:  # forced Lite for testing
        return f"({feature} is switched off — Lite test mode.)"
    return (f"I can't do {feature} on {where} — that's one of my "
            f"Windows-only parts. Everything else works.")
