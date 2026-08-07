"""Resume a paused game/match: brings its window to the front and taps
Escape, which is the key that closes the pause menu (and so un-pauses) in
most PC games."""
import time

import pyautogui
import pygetwindow

DESCRIPTION = ("Resume/unpause a game or match that's currently paused. E.g. "
               "'resume this match', 'unpause the game', 'continue playing'. "
               "NOT for music/video playback (that's the media skill) and NOT "
               "for launching a game fresh (that's steam/steam_game/open_app).")
ARGS = {"title": "part of the game window's title, or 'active'/blank for whichever "
                  "window is in front (default)"}

ACTIVE_WORDS = ("", "active", "this", "it", "current", "that", "match", "game", "the game")


def _bring_front(win) -> None:
    """pygetwindow's activate() raises 'error 0 - completed successfully'
    when Windows won't grant focus politely; go through the Win32 API."""
    try:
        win.activate()
    except Exception:
        import ctypes

        ctypes.windll.user32.ShowWindow(win._hWnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(win._hWnd)


def _target(title: str):
    title = (title or "").strip().lower()
    if title in ACTIVE_WORDS:
        return pygetwindow.getActiveWindow()
    cleaned = title.replace("the ", "").strip()
    for win in pygetwindow.getAllWindows():
        if win.title and cleaned in win.title.lower():
            return win
    return None


def run(args: dict) -> str:
    win = _target(args.get("title", ""))
    if win is None or not win.title:
        return "I can't tell which game is paused — bring it to the front and ask again."

    name = win.title.split(" - ")[0]
    if win.isMinimized:
        win.restore()
    _bring_front(win)
    time.sleep(0.3)
    pyautogui.press("esc")
    return f"Resuming {name}."
