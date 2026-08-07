"""PC health report: disk space, memory, CPU load, uptime, and startup
bloat — spoken plainly for a non-technical owner."""
import datetime
import shutil

import psutil

DESCRIPTION = ("Health report on THIS PC — 'how's my PC doing', 'PC health "
               "check', 'how much disk space do I have', 'is my computer "
               "okay'. Covers disk space, memory, processor load, uptime, "
               "and how many programs auto-start. NOT for the PC's specs "
               "(that's pc_specs).")
ARGS = {}


def _startup_count() -> int:
    import winreg

    count = 0
    for hive, path in (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run")):
        try:
            with winreg.OpenKey(hive, path) as key:
                count += winreg.QueryInfoKey(key)[1]
        except OSError:
            continue
    return count


def run(args: dict) -> str:
    parts = []
    total, used, free = shutil.disk_usage("C:\\")
    free_gb, total_gb = free / 1e9, total / 1e9
    pct = round(100 * free / total)
    parts.append(f"Drive C has {free_gb:.0f} gigabytes free of "
                 f"{total_gb:.0f} — {pct} percent")
    if pct < 10:
        parts[-1] += ", which is getting tight"

    mem = psutil.virtual_memory()
    parts.append(f"memory is {mem.percent:.0f} percent used")
    cpu = psutil.cpu_percent(interval=0.6)
    parts.append(f"the processor is at {cpu:.0f} percent")

    up = datetime.datetime.now() - datetime.datetime.fromtimestamp(
        psutil.boot_time())
    days, hours = up.days, up.seconds // 3600
    parts.append(f"the PC's been on {days} day{'s' if days != 1 else ''} "
                 f"and {hours} hour{'s' if hours != 1 else ''}"
                 if days else f"the PC's been on {hours} "
                 f"hour{'s' if hours != 1 else ''}")
    try:
        n = _startup_count()
        parts.append(f"and {n} programs launch at startup")
        if n > 15:
            parts[-1] += " — a cleanout would speed up boots"
    except Exception:
        pass
    verdict = "All healthy. " if pct >= 10 and mem.percent < 90 else "Worth a look: "
    return verdict + "; ".join(parts) + "."
