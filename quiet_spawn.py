"""Stop child processes popping black console windows on the owner's desktop.

The Claude CLI is a console program. TARS runs as pythonw (no console of
its own), so every time the big brain or Kipp starts thinking, Windows
gives that child a brand new console window — a blank box titled "claude"
that appears over whatever the owner is doing and sits there until the job
ends. He asked for it to stop.

anyio.open_process goes to asyncio, and asyncio on Windows does NOT use
subprocess.Popen directly — it uses asyncio.windows_utils.Popen, which
subclassed the original at import time. Patching subprocess.Popen alone
therefore does nothing (measured: the flag never arrived). Both are
patched here.
"""
import os
import subprocess

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010


def _windowless(original):
    class WindowlessPopen(original):
        _tars_windowless = True

        def __init__(self, *args, **kwargs):
            # never override a caller that asked for a window on purpose
            flags = kwargs.get("creationflags", 0)
            if not flags & CREATE_NEW_CONSOLE:
                kwargs["creationflags"] = flags | CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    return WindowlessPopen


def hide() -> bool:
    """Make every subprocess from this process windowless. Idempotent."""
    if os.name != "nt":
        return False
    if not getattr(subprocess.Popen, "_tars_windowless", False):
        subprocess.Popen = _windowless(subprocess.Popen)
    try:
        import asyncio.windows_utils as win_utils

        if not getattr(win_utils.Popen, "_tars_windowless", False):
            win_utils.Popen = _windowless(win_utils.Popen)
    except Exception:
        pass
    return True
