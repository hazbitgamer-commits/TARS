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
   `ollama pull qwen2.5:7b` and `ollama pull qwen2.5:3b`
   (the big one talks, the small one routes commands — fast and light)
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
Opening apps, clicking the screen, reading the screen, face recognition,
brightness, Steam, the vacuum and smart speakers, and self-modification.
Those need his Windows body (or a future Mac port of each organ).

Hand signals and the camera HUD **do** work on Mac — they only need the
webcam, not the heavy vision model.

---

# Repair kit

## "He doesn't answer me"

Run this. It walks the whole chain — microphone, wake word, understanding
speech, thinking, speaking — and stops at the **first** thing that's
actually broken, with the command to fix it:

```bash
cd ~/TARS && bash tars_mac.sh --voice
```

It talks you through it (say something when it asks) and writes
`voice_report.txt`. If you're still stuck, send that file — it says
exactly where the chain breaks, so nobody has to guess.

The three most common causes, in order:

1. **Ollama isn't running.** It's the part that does the thinking. Open
   the Ollama app and start TARS again.
2. **macOS is blocking the microphone.** System Settings → Privacy &
   Security → Microphone → turn on for Terminal, then restart TARS.
3. **PortAudio is missing**, so nothing audio works at all:
   `brew install portaudio && bash setup_mac.sh`

## "It's stuck on an old version"

The symptom: far fewer skills than the repo has, no setup page on first
run, no box to type into on the dashboard. Older installers ran
`git pull || true`, which silently did nothing whenever the update
couldn't apply — so the install reported success and stayed stale.

Paste this. It forces the code to match GitHub. Your details, logs and
memories aren't tracked by git, so none of them are touched:

```bash
cd ~/TARS && \
git remote set-url origin https://github.com/hazbitgamer-commits/TARS.git && \
git fetch origin main && \
git stash push -m pre-repair; \
git checkout -B main origin/main && \
echo "now on: $(git log --oneline -1)" && \
echo "skills: $(ls skills | wc -l)"
```

Then bring the libraries and models up to date and start him:

```bash
cd ~/TARS && bash setup_mac.sh && bash tars_mac.sh
```

## Other quick fixes

| Symptom | Fix |
| --- | --- |
| "Hey TARS" does nothing | Allow **Microphone** for Terminal in System Settings → Privacy & Security, then restart TARS |
| He can't hear you, but the beep plays | `python3 doctor_mac.py` — it checks the mic and says what's wrong |
| No voice, or a robotic one | The voice model didn't download: `bash setup_mac.sh` again |
| "My local brain is offline" | Ollama isn't running: open the Ollama app, then restart TARS |
| Camera or hand signals missing | `source .venv/bin/activate && pip install opencv-python mediapipe` |
| Everything's odd after an update | `python3 doctor_mac.py`, then restart |

## Checking your version

```bash
cd ~/TARS && git log --oneline -1 && ls skills | wc -l
```

TARS also checks for updates himself a few times a day and will say when
there's one waiting. Ask him **"is there an update"** or tell him
**"update yourself"** any time.
