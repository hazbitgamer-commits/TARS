# restart_engine

the owner's rule: "if I say 'restart yourself' you must restart your engine and
close and reopen dashboard." This is a full self-restart, not a shutdown.

## Trigger phrases
- "restart yourself"
- "restart your engine"
- "reboot yourself"
- "restart TARS"

## What it does
0. If a restart was already kicked off in the last 25 seconds, it does NOT
   restart again — it asks "I just kicked off a restart — say yes if you
   want me to do it again." This is for the case where "restart yourself"
   gets said twice in a row because the first one looked like it failed
   (no reply heard yet, dashboard hasn't reopened). Saying yes runs the
   real restart; anything else cancels. A fresh ask more than 25 seconds
   after the last one runs immediately, same as always.
1. Closes TARS's own dashboard/brain/camera-feed windows (chromeless app
   windows whose title starts with "TARS").
2. Replies "Restarting my engine now. I'll be back in a few seconds."
3. Hands off to a detached helper (`_do_restart.py`) that:
   - waits 6 seconds so the spoken reply finishes playing
   - force-kills the current engine process by PID (`taskkill /F /PID`)
   - runs `TARS.bat` again from the TARS folder — the exact same thing
     that happens when the owner double-clicks the desktop icon

`TARS.bat` -> `boot.py --window` starts the engine fresh and, after ~7
seconds, reopens the dashboard window automatically. No extra code needed
here for that part — it's already how TARS boots normally.

## Not to be confused with
- "goodbye TARS" / "shut down TARS" — a real shutdown, TARS does NOT come
  back on its own (main.py's SHUTDOWN_WORDS).
- close_window — closes one window without touching the engine.
- open_dashboard — opens the dashboard without restarting anything.
