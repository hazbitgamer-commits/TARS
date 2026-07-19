import screen_brightness_control as sbc

DESCRIPTION = ("Read or change SCREEN brightness (the monitor/display backlight). "
               "E.g. 'set screen brightness to 50 percent', 'brighten the screen' "
               "(level '+15'), 'dim it' (level '-15'). "
               "NOT for speaker volume and NOT for the microphone — those are "
               "different skills.")
ARGS = {"level": "0-100 to set, +N or -N to nudge, or 'get' to just read it"}


def _describe(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "unknown"
    if len(set(values)) == 1:
        return f"{values[0]} percent"
    return ", ".join(f"{v} percent" for v in values)


def run(args: dict) -> str:
    level = str(args.get("level", "get")).strip().lower().rstrip("%")

    try:
        current_list = sbc.get_brightness()
        current = current_list[0] if current_list else 50
    except Exception:
        return "I couldn't read the screen brightness on this PC."

    if level.startswith(("+", "-")) and level[1:].isdigit():
        new = max(0, min(100, current + int(level)))
    elif level.isdigit():
        new = max(0, min(100, int(level)))
    else:
        return f"Screen brightness is at {_describe(current_list)}."

    try:
        sbc.set_brightness(new)
    except Exception:
        return "I couldn't change the screen brightness on this PC."

    return f"Screen brightness set to {new} percent."
