# virus_scan
Runs a virus/malware scan of the PC using Windows Defender (the antivirus already built into Windows) and automatically removes or quarantines anything it finds. Uses `Start-MpScan` to scan, `Get-MpThreatDetection` to see what turned up, and `Remove-MpThreat` to clean it up -- no third-party tools, no files touched outside what Defender itself manages.
**Say:** "run a virus scan" / "scan my computer for viruses" / "check for malware" / "do a full virus scan"
**Args:** `scan_type` -- "quick" (default, a few minutes, checks common trouble spots) or "full" (thorough, checks every file, can take a long time).
