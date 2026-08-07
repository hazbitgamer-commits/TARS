# steam_game
Launches a specific game you already own and have installed in Steam, by name.
**Say:** "open FC26 on Steam" / "play Counter-Strike 2 on Steam" / "launch Skyrim in Steam"
**Args:** `game` — the name of the Steam game to launch.

How it works: finds your Steam install folder, reads the installed-game list
straight from Steam's own library files (no internet needed), matches the
spoken name against it, and opens `steam://rungameid/<id>` which hands off
to the Steam client to launch it.
