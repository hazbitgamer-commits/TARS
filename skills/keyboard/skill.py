import time

import pyautogui

DESCRIPTION = ("Press editing keys in the focused window: select all, delete, copy, paste, "
               "undo, enter, escape, new tab... E.g. 'select all and delete', 'press enter'.")
ARGS = {"actions": "comma-separated key actions, e.g. 'select all, delete'"}

ACTIONS = {
    "select all": ("ctrl", "a"),
    "copy": ("ctrl", "c"),
    "paste": ("ctrl", "v"),
    "cut": ("ctrl", "x"),
    "undo": ("ctrl", "z"),
    "redo": ("ctrl", "y"),
    "save": ("ctrl", "s"),
    "find": ("ctrl", "f"),
    "new tab": ("ctrl", "t"),
    "close tab": ("ctrl", "w"),
    "next tab": ("ctrl", "tab"),
    "refresh": ("f5",),
    "delete": ("delete",),
    "backspace": ("backspace",),
    "enter": ("enter",),
    "escape": ("esc",),
    "tab": ("tab",),
}


def run(args: dict) -> str:
    wanted = [a.strip().lower().replace("press ", "") for a in
              (args.get("actions") or "").split(",") if a.strip()]
    if not wanted:
        return "Press what, exactly?"
    time.sleep(0.4)  # let focus settle after the voice exchange
    done = []
    for action in wanted:
        keys = ACTIONS.get(action)
        if keys is None:
            return f"I don't know the key action {action}." + (
                f" (Did do: {', '.join(done)}.)" if done else "")
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        done.append(action)
        time.sleep(0.15)
    return "Done: " + ", ".join(done) + "."
