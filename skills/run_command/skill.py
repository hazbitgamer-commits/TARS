import subprocess

DESCRIPTION = "Run a Windows command-line command and report the result. For technical requests only."
ARGS = {"command": "the exact command line to run"}

# Hard-block list (§8 of the spec): destructive things need explicit
# confirmation, and the voice confirmation flow isn't built yet.
BLOCKED_BITS = ("format ", "del ", "erase ", "rmdir", "rd /", "remove-item", "diskpart",
                "reg delete", "shutdown", "cipher /w", "bcdedit", "mkfs")


def run(args: dict) -> str:
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return "Run what, exactly?"
    lowered = f" {cmd.lower()} "
    if any(bit in lowered for bit in BLOCKED_BITS):
        return ("That command is on my hard-block list — deleting or destructive stuff "
                "needs a confirmation system I don't have yet. Declined for now.")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "That command ran over a minute, so I cut it off."
    out = (r.stdout or r.stderr or "").strip()
    if not out:
        return "Done. No output."
    return out[:350]
