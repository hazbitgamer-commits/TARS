# sleep_timer
Delayed PC action: pause music, mute, lock or sleep after N minutes (threading.Timer inside the TARS process; state in sleep_timer.json). Cancellable. Lost on restart by design.
**Say:** "stop the music in 20 minutes" / "sleep the computer in an hour" / "cancel the sleep timer"
**Args:** `action`, `minutes`.
