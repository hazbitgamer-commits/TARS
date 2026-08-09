# check_installed
Checks whether a specific program is installed on this PC by reading Windows'
installed-programs list from the registry (the same list Control Panel >
Programs and Features shows) — more thorough than `open_app`'s Start Menu
shortcut search, since some installed programs don't have a Start Menu entry.
**Say:** "is minicat 3d installed" / "check if Blender is installed" / "do I have Steam installed"
**Args:** `name` — the program name to check for.
