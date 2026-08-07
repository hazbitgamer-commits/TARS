# TARS Lite on a Mac — honest install guide

TARS was born on Windows. On a Mac you get **TARS Lite**: the full
thinking stack — voice conversation, hearing, his British voice, the
dashboard, timers, lists, weather, web answers — without the Windows-only
hands (app control, screen clicking, camera, PC volume).

**Honesty first:** this Lite mode is tested in Lite form on the Windows
machine TARS lives on, but it has NOT yet run on a real Mac. You are the
first. If anything breaks, copy the error and send it back — every report
makes the next attempt better.

Works best on Apple Silicon (M1/M2/M3/M4) with 16 GB memory.

## The one-paste install

Open Terminal (press Cmd+Space, type "terminal", press Enter), paste
this single line, and press Enter:

    curl -fsSL https://raw.githubusercontent.com/hazbitgamer-commits/TARS/main/get_tars.sh | bash

It installs everything: Ollama and its AI models (~10 GB — the long
part), TARS himself, and his voice and hearing (~400 MB). If macOS pops
up asking to install developer tools first, click Install, wait, then
paste the same line again.

Then start TARS any time with:

    cd ~/TARS && bash tars_mac.sh

<details><summary>Manual steps (if you'd rather do it piece by piece)</summary>

1. Install Ollama from https://ollama.com/download/mac, then:
   `ollama pull qwen2.5:7b`, `ollama cp qwen2.5:7b qwen2.5:7b-router`,
   `ollama pull qwen3:8b`
2. `git clone https://github.com/hazbitgamer-commits/TARS.git && cd TARS`
3. `bash setup_mac.sh`
4. `bash tars_mac.sh`

</details>

macOS will ask for **Microphone** permission the first time — allow it,
or TARS is deaf. The dashboard opens in your browser; say **"Hey TARS"**
and talk.

## What works on Mac (Lite)
- Voice conversation with personality (say "hey TARS")
- The dashboard: status, chat feed, personality sliders, map
- Timers, to-do and shopping lists, weekly reminders
- Weather and spoken web answers
- Say "stop" to cut him off mid-sentence

## What does NOT work on Mac yet
Opening apps, clicking the screen, reading the screen, camera and face
recognition, PC volume/brightness, Steam, the vacuum and smart speakers,
and self-modification. Those need his Windows body (or a future Mac port
of each organ).
