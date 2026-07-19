# brightness

Reads or changes the screen (monitor) brightness.

## Usage
- "set screen brightness to 50 percent" -> level = "50"
- "brighten the screen" -> level = "+15"
- "dim the screen" -> level = "-15"
- "what's the screen brightness" -> level = "get"

## Notes
- Uses the `screen-brightness-control` package (installed into the TARS runtime).
- Only affects displays that support software brightness control (most laptop
  screens; some external monitors need DDC/CI support).
- Not for speaker volume (see the `volume` skill) and not for the microphone.
