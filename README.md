# TARS — a voice assistant that runs on your own machine

## How to start / stop
- **Start:** double-click `TARS.bat` in this folder.
- **Talk:** say **"Hey TARS"**, wait for the beep, then speak. After TARS
  answers you'll hear a soft blip — you can keep talking without repeating
  the wake word. Go quiet for ~5 seconds (or say "that's all") and TARS
  goes back to standby. The pill in the bottom-right corner shows its
  state: grey standby, green listening, amber thinking, blue speaking.
- **Stop:** press `Ctrl+C` in the TARS window, or just close the window.

## Monthly cost
**$0.** Local brain (Ollama), free Microsoft voice, free wake-word tier,
and hard tasks go through your own Claude subscription (optional).

Since Aug 2026 there's also a free **cloud brain** (Ox Alpha, a stealth
preview model on OpenRouter): genuinely hard questions, coding questions,
and everything mid-game (it costs the PC nothing) route to it; everyday
chat stays on the local brain and never leaves the PC. Honest trade-offs:
those routed questions DO leave the PC (the model's lab can see them,
passwords are stripped first), and stealth models get retired without
notice — when Ox dies, TARS quietly falls back to local and someone should
swap `CLOUD_MODEL` to the next free one. See `cloud_brain.py`.

## What TARS can do right now (Phases 1–3)
- Wake on **"Hey TARS"** (local Vosk keyword spotting — free, offline, no account)
- Understand spoken questions (local Whisper — nothing leaves the PC)
- Answer with its local brain (Ollama) with the TARS personality; starts
  Ollama itself if it's not running
- Reply out loud in a British neural voice (offline fallback voice if internet drops)
- Remember the conversation within a session; log everything to `logs/`
- **Control the computer** (say it naturally, TARS works out which skill to use):
  - "open chrome" / "open youtube dot com" / "close spotify"
  - "set volume to 40" / "turn it down" / "mute"
  - "take a screenshot" (saved to Pictures\TARS)
  - "find my tax file" / "find and open my resume"
  - "type hello there" (types into the focused window)
  - "pause the music" / "next track"
  - "lock the computer"
  - "run ipconfig" (command line; destructive commands are refused)
- **Answer with live info from the internet:**
  - "what's the weather" / "will it rain tomorrow" / "weather in Sydney"
    (home city is Perth — change `HOME_CITY` in `.env` to move house)
  - "who won the game last night" / "what's the price of X" — web search,
    summarized out loud
- Knows today's date and time (ask "what day is it")
- **Timers & reminders**, announced out loud with a chime:
  - "set a timer for 10 minutes" / "remind me to check the oven in 25 minutes"
  - "remind me to call mum at 5 pm" / "what timers are running" / "cancel my timers"
- Find folders too, and understands "latest": "open the latest screenshot"
- "close the pictures window" / "close this window" — closes single windows
- **Window juggling:** "bring it to my main screen" / "put that on the left
  monitor" / "bring claude to the front" / "maximize that" / "minimize
  everything" / "what windows are open"
- **Keyboard editing:** "select all and delete" / "press enter" / "undo that" /
  "copy" / "paste" / "new tab"
- **Show things in the browser:** "open a map of England" / "look up flights
  to Bali in the browser" (spoken answers still come from plain questions)
- **"Goodbye TARS"** — shuts TARS down politely (its own window is otherwise protected)

- "what are my PC specs" — reads out CPU, RAM, graphics card, disk space
- **Big-brain tasks** (needs the one-time token setup below): "write me a
  script that..." / "build me a..." — TARS hands it to Claude, which can
  create and run code in `workshop/`, then TARS announces the result.
  Full transcripts land in `logs/deep_tasks.log`.

- **Gmail** ([personal email removed]): "any new emails?" / "summarize my inbox" /
  "draft an email to mum about sunday dinner" — TARS writes DRAFTS only;
  you review and send from Gmail yourself (hard rule, by design)
- **Calendar:** "what's on my calendar today / tomorrow / this week" /
  "add dentist to my calendar friday at 3 pm"

## One-time setup for big-brain tasks
1. Open Command Prompt (press Win, type `cmd`, Enter)
2. Type `claude setup-token` and press Enter — a browser window opens
3. Approve it (uses your own Claude subscription)
4. Copy the token it prints (starts with `sk-ant-`) and give it to Claude
   Code to store in `.env` as `CLAUDE_CODE_OAUTH_TOKEN`

- **Self-learning:** ask for something TARS can't do yet and it teaches
  itself — the big brain writes a brand-new skill, tests it, and TARS can
  use it immediately (first self-taught skill: screen brightness).
  Everything it learns is reviewable in `skills/` and `logs/deep_tasks.log`.

- **Personality by voice:** "set humor to 90" / "dial the sarcasm down" /
  "what are your settings" — and invent NEW settings: "set paranoia to 80"
- **Permanent memory (the vault):** "remember that my bin day is Thursday" /
  "what do you know about me". Notes live in `vault\` as plain Markdown —
  browse TARS's brain in Obsidian.
- **Total recall:** every conversation is transcribed into
  `vault\Conversations\` as it happens, and TARS can answer from them —
  "when did I ask about the map of England?" → "At 19:46 on July 17."
- **Topic brain:** after each conversation, TARS distills what you talked
  about into topic notes in `Knowledge\` (wikilinked to each other and to
  the transcripts) — the Obsidian graph grows around subjects, not dates.
- **The agent staff:** Scout delivers a spoken morning briefing at 7:30
  automatically (weather, email, calendar, timers — or say "give me my
  briefing" anytime); the Archivist files conversations into topics; the
  Librarian cross-links near-duplicate memories ("run the librarian").
  All three appear in the 3D brain as glowing shapes that fly to the
  neurons they work on. "Who are your agents" lists them.
- **The neuron brain** ("show me the brain"): every memory is a neuron that
  FIRES when you talk about related things. Neurons that fire together
  strengthen their connection (real STDP learning); strong learned
  associations get written into Obsidian as links the brain discovered
  itself. Fired memories flow into TARS's replies automatically. The 3D
  page shows it live — drag to spin, watch neurons flash as you speak.
- **Sleep mode:** "go to sleep" (purple pill; ignores everything except
  "Hey TARS, wake up")
- **Starts with Windows automatically** (minimized). To disable: delete
  `TARS.bat` from the Startup folder (Win+R → `shell:startup`).

- **Webcam eye** (only when you say "camera"/"webcam"): "access my camera" opens
  the live feed page; "access my camera, what am I holding" describes a snapshot
- **Face memory:** "the person in the white shirt is Sam" teaches TARS a
  face; "who is this?" answers by name; known people get live nametags on the
  camera feed and a person-note in the vault (all local — faces never leave the PC)
- **Eyes:** "what's on my screen?" / "look at my left screen and read the
  error" — TARS screenshots and describes it with a local vision model
  (nothing leaves the PC; takes ~20-30 seconds)
- **Guarded deletion:** "delete all screenshots in the TARS folder" —
  TARS states the count, waits for your spoken "yes", and uses the
  Recycle Bin so nothing is ever gone for good
- **Dashboard:** "show me the home page" — a sci-fi HUD in the browser with
  live status, weather, timers, personality sliders (drag = instant effect),
  activity feed, skills list, and brain stats with links into Obsidian.
  (localhost only — invisible to the internet)

- **The robot vacuum** (eufy S2): "start the vacuum" / "pause the vacuum" /
  "send the vacuum home" / "is the vacuum connected". Cleaning is blocked
  during quiet hours unless you say "override quiet hours".

**That's the entire original plan built.** Everything from here is refinement.

## Repair kit
TARS has its own private Python in `runtime/` (nothing else on the PC touches it).
If it ever breaks, re-extract `python312.tar.gz` here and rename `python` → `runtime`.

## Can I run TARS on a Mac?

**Yes — TARS Lite.** See **INSTALL_MAC.md** for the step-by-step guide:
voice conversation, hearing, his voice, the dashboard, timers, lists,
weather and web answers all run on a Mac (Apple Silicon recommended).
The Windows-only hands (app control, screen clicking, camera) don't — the
guide is honest about exactly what works. Lite mode is tested in Lite
form on TARS's home machine; a real-Mac test run is still to come.

*(Original answer, kept for honesty about the full version:)*
**Full TARS: not yet.** TARS was built for Windows and many of his
organs are Windows-only — the microphone/speaker handling, the webcam feed,
opening and controlling apps, the screen capture used by his eyes, and the
launcher scripts are all wired to Windows.

What a Mac user CAN do today:
- **Read everything.** All of TARS's code is in this repository — the brain
  (`brain.py`), the self-improvement agent (`improve.py`), every skill in
  `skills/`, and the dashboard. It's a complete picture of how he works.
- **Reuse the brains.** The AI models TARS runs on — Ollama (chat + routing),
  faster-whisper (hearing), and Kokoro (voice) — all exist on macOS, so the
  thinking parts of a Mac TARS are entirely possible.

What a true Mac port would need: replacing the Windows-specific pieces
(audio device control, screen/webcam capture, app launching, the .bat
launchers) with macOS equivalents. It's a real project, not an install step —
if it ever happens, instructions will appear right here.
