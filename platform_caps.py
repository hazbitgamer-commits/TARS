"""Where am I running? — TARS's platform awareness (Phase 1 of universal
TARS, 2026-08-07, target: Jacob's mate's MacBook).

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
    "camera", "camera_feed", "face_learn", "face_who", "object_detection",
    "voice_output", "delete_files", "organize", "type_text", "keyboard",
    "media", "dictation", "vacuum", "vacuum_room", "vacuum_speed",
    "speakers", "quiet_hours",
}


def blocked_skills() -> set:
    return BLOCKED_OFF_WINDOWS if LITE else set()


def python_cmd(base: Path | None = None) -> str:
    """The right Python for running/testing code on THIS platform —
    Windows uses TARS's private runtime, elsewhere it's whatever
    interpreter TARS itself runs on (the venv)."""
    if IS_WINDOWS and base is not None:
        return str(base / "runtime" / "python.exe")
    exe = sys.executable or "python3"
    return exe.replace("pythonw.exe", "python.exe")


def unavailable(feature: str) -> str:
    """A spoken, honest 'not on this machine' line."""
    return (f"I can't do {feature} on {PLATFORM_NAME} yet — that part of "
            f"me is still Windows-only.")
