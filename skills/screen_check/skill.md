# screen_check

Checks every detected screen/monitor to see whether it actually responds to
software brightness commands, and reports which one (if any) is broken.

## Usage
- "which screens can you change the brightness of" -> no args
- "which monitor is broken" -> no args
- "check my screens" -> no args

## How it works
- Uses `screen_brightness_control` (`sbc.list_monitors()`) to enumerate screens.
- For each screen: reads its current brightness, nudges it by 20 percent,
  reads it back to see if the change actually stuck, then restores the
  original value.
- A screen that reports success but the value doesn't change is called out
  as "broken" (this happens with monitors that accept DDC/CI commands but
  silently ignore them).
- A screen that errors out entirely is called "not readable".

## Notes
- This is a diagnostic/read-only-outcome skill — it always restores each
  screen to its original brightness before returning.
- Not for actually setting brightness — see the `brightness` skill for that.
- Not for speaker volume or the microphone — those are different skills.
