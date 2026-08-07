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

## 1. Install the AI brain (Ollama)
Download and install from https://ollama.com/download/mac — then in
Terminal:

    ollama pull qwen2.5:7b
    ollama cp qwen2.5:7b qwen2.5:7b-router
    ollama pull qwen3:8b

(That's ~10 GB of AI models — give it time.)

## 2. Get TARS
    git clone https://github.com/hazbitgamer-commits/TARS.git
    cd TARS

## 3. Run the setup script
    bash setup_mac.sh

This creates a private Python environment, installs the libraries, and
downloads the hearing (Vosk) and voice (Kokoro) models (~400 MB).

## 4. Start TARS
    bash tars_mac.sh

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
