# breaks
Eye/posture break nudges on an interval. State in breaks.json; the actual firing happens in timers_watch._breaks_due (polled by main standby loop). Skips quiet hours and fullscreen games.
**Say:** "remind me to take breaks" / "break reminders every 30 minutes" / "stop break reminders"
**Args:** `action` on/off/status, `minutes`.
