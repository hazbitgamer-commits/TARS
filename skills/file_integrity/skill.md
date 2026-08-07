# file_integrity
Checks a file's integrity by computing its SHA-256 checksum and comparing it to the checksum saved the last time it was checked, so TARS can catch changes or corruption. Remembers checksums automatically in manifest.json next to this skill.
**Say:** "check the integrity of report.pdf" / "has budget.xlsx changed" / "verify workshop/backup.zip"
**Args:** `path` — file name or path to check (relative to workshop, one of Jacob's main folders, or absolute).
