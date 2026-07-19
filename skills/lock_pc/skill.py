import ctypes

DESCRIPTION = "Lock the PC (Windows lock screen)."
ARGS = {}


def run(args: dict) -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Locking up. See you soon."
