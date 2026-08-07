# restart_engine

Jacob's rule: "if I say 'restart yourself' you must restart your engine and
close and reopen dashboard." This is a full self-restart, not a shutdown.

## Trigger phrases
- "restart yourself"
- "restart your engine"
- "reboot yourself"
- "restart TARS"

## What it does
1. Closes TARS's own dashboard/brain/camera-feed windows (chromeless app
   windows whose title starts with "TARS").
2. Replies "Restarting my engine now. I'll be back in a few seconds."
3. Hands off to a detached helper (`_do_restart.py`) that:
   - waits 6 seconds so the spoken reply finishes playing
   - force-kills the current engine process by PID (`taskkill /F /PID`)
   - runs `TARS.bat` again from the TARS folder — the exact same thing
     that happens when Jacob double-clicks the desktop icon

`TARS.bat` -> `boot.py --window` starts the engine fresh and, after ~7
seconds, reopens the dashboard window automatically. No extra code needed
here for that part — it's already how TARS boots normally.

## Not to be confused with
- "goodbye TARS" / "shut down TARS" — a real shutdown, TARS does NOT come
  back on its own (main.py's SHUTDOWN_WORDS).
- close_window — closes one window without touching the engine.
- open_dashboard — opens the dashboard without restarting anything.
