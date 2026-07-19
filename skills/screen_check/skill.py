import screen_brightness_control as sbc

DESCRIPTION = ("Check which physical screens/monitors actually respond to software "
               "brightness control, and detect if one of them is broken (accepts the "
               "command but doesn't change). E.g. 'which screens can you change the "
               "brightness of', 'which monitor is broken', 'check my screens'. "
               "NOT for actually setting the brightness — use the brightness skill "
               "for that.")
ARGS = {}


def _label(name: str, index: int) -> str:
    name = (name or "").strip()
    if not name or name.lower().startswith("none"):
        parts = name.split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
        return f"screen {index + 1}"
    return name


def run(args: dict) -> str:
    try:
        names = sbc.list_monitors()
    except Exception:
        return "I couldn't find any screens to check on this PC."

    if not names:
        return "I couldn't detect any controllable screens on this PC."

    working, broken, unreadable = [], [], []

    for i, name in enumerate(names):
        label = _label(name, i)
        try:
            before = sbc.get_brightness(display=i)[0]
        except Exception:
            unreadable.append(label)
            continue

        test = before - 20 if before >= 20 else before + 20
        test = max(0, min(100, test))

        try:
            sbc.set_brightness(test, display=i)
            after = sbc.get_brightness(display=i)[0]
        except Exception:
            broken.append(label)
            try:
                sbc.set_brightness(before, display=i)
            except Exception:
                pass
            continue

        try:
            sbc.set_brightness(before, display=i)
        except Exception:
            pass

        if after == test:
            working.append(label)
        else:
            broken.append(label)

    sentences = []
    if working:
        if len(working) == 1:
            sentences.append(f"{working[0]} lets me change its brightness.")
        else:
            sentences.append(", ".join(working) + " let me change their brightness.")
    if broken:
        if len(broken) == 1:
            sentences.append(f"{broken[0]} did not respond, so that one's broken.")
        else:
            sentences.append(", ".join(broken) + " did not respond, so those are broken.")
    if unreadable:
        if len(unreadable) == 1:
            sentences.append(f"{unreadable[0]} isn't readable at all.")
        else:
            sentences.append(", ".join(unreadable) + " aren't readable at all.")

    if not sentences:
        return "I found screens but couldn't test any of them."

    return " ".join(sentences)
