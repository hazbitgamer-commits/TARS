"""Run a Windows Defender virus/malware scan and automatically remove
anything it finds -- uses the antivirus already built into Windows, no
third-party tools needed."""
import json
import os
import subprocess

DESCRIPTION = ("Run a virus/malware scan of THIS PC using Windows Defender, "
               "the antivirus already built into Windows, then automatically "
               "remove or quarantine anything it finds. E.g. 'run a virus "
               "scan', 'scan my computer for viruses', 'check for malware', "
               "'do I have any viruses'. A quick scan checks the common "
               "trouble spots (a few minutes); say 'full scan' to check "
               "every file on the PC, which is much slower.")
ARGS = {"scan_type": "'quick' (default -- fast, checks common trouble spots) "
                      "or 'full' (thorough, checks every file, can take a "
                      "long time)"}

POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
_SCRIPT = os.path.join(os.path.dirname(__file__), "scan.ps1")


def _run_ps(scan_type: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", _SCRIPT, "-ScanType", scan_type],
        capture_output=True, text=True, timeout=timeout,
    )


def run(args: dict) -> str:
    scan_type = str(args.get("scan_type", "quick")).strip().lower()
    full = scan_type.startswith("full")
    ps_type = "FullScan" if full else "QuickScan"
    kind = "Full" if full else "Quick"
    timeout = 3600 if full else 900

    try:
        proc = _run_ps(ps_type, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ("That scan is taking longer than expected and is still "
                "running in the background -- ask me again in a bit and "
                "I'll tell you what it found.")
    except FileNotFoundError:
        return "I couldn't find Windows Defender on this PC to run a scan with."

    out = (proc.stdout or "").strip()

    if "ALREADY_RUNNING" in out:
        return ("A scan is already running -- give it a few minutes and "
                "ask me again.")

    if out.startswith("ERR:"):
        msg = out[4:].strip()
        low = msg.lower()
        if "access" in low or "denied" in low or "0x80070005" in low:
            return ("I need administrator rights to run a virus scan -- "
                    "start me as admin and I'll try again.")
        return f"The scan didn't finish properly: {msg}"

    try:
        data = json.loads(out)
    except (ValueError, json.JSONDecodeError):
        return "The scan finished, but I couldn't read the results back."

    count = int(data.get("count", 0))
    removed = int(data.get("removed", 0))

    if count == 0:
        return f"{kind} scan finished -- your PC is clean, no threats found."
    if removed >= count:
        return (f"{kind} scan finished -- found {count} threat"
                f"{'s' if count != 1 else ''} and removed them all.")
    return (f"{kind} scan finished -- found {count} threat"
            f"{'s' if count != 1 else ''}, removed {removed} of them. "
            "Open Windows Security to check the rest.")
