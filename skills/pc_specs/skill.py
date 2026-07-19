import itertools
import platform
import winreg

import psutil

DESCRIPTION = "Report the PC's specs: CPU, memory, graphics card, disk space, Windows version."
ARGS = {}


def _gpus() -> list[str]:
    names = []
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}",
        )
        for i in itertools.count():
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                break
            try:
                name = winreg.QueryValueEx(winreg.OpenKey(key, sub), "DriverDesc")[0]
                if "virtual" not in name.lower():
                    names.append(name)
            except OSError:
                pass
    except OSError:
        pass
    return names


def _cpu_name() -> str:
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        return platform.processor() or "unknown CPU"


def run(args: dict) -> str:
    ram = round(psutil.virtual_memory().total / 2**30)
    disk = psutil.disk_usage("C:\\")
    free = round(disk.free / 2**30)
    cpu = _cpu_name()
    cores = psutil.cpu_count(logical=False)
    gpus = _gpus()
    gpu = gpus[0] if gpus else "no dedicated graphics"
    return (f"{cores}-core {cpu}, {ram} gigs of memory, {gpu}, "
            f"{free} gigabytes free on the C drive, running Windows "
            f"{platform.release()}.")
