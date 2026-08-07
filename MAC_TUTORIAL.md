# Mac tutorial — download TARS's code and help port it

TARS itself doesn't run on a Mac yet (see "Can I run TARS on a Mac?" in the
main [README](README.md) for why). But you can still **download the code**,
look around, and **help build the Mac version**. Here's how.

## 1. Download the code

You don't need to know Git to do this.

**Easiest way (just a ZIP file):**
1. Go to the repo's main page: https://github.com/hazbitgamer-commits/TARS
2. Click the green **`<> Code`** button.
3. Click **"Download ZIP"**.
4. Unzip it — you now have the full project on your Mac.

**Or, if you're comfortable with Terminal:**
```
git clone https://github.com/hazbitgamer-commits/TARS.git
```
That copies the whole repo into a new `TARS` folder in your current directory.

## 2. What you can do once it's downloaded

- **Read the code.** `brain.py` is the "thinking" part, `skills/` holds every
  individual skill (things TARS can do), and `dashboard/` is the web UI.
- **Try the AI parts on their own.** The three AI engines TARS uses —
  [Ollama](https://ollama.com) (chat), 
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (speech-to-text),
  and [Kokoro](https://github.com/hexgrad/kokoro) (text-to-speech) — all have
  Mac versions. You can install and experiment with those directly, even
  though the full `main.py` loop isn't Mac-ready.

## 3. How to help port TARS to Mac

The parts that need replacing are the Windows-only ones: microphone/speaker
handling, opening and controlling apps, screen/webcam capture, and the
`.bat` launcher scripts. If you'd like to help:

1. Open an **Issue** on the repo (button near the top of the GitHub page)
   describing what you'd like to work on — e.g. "swapping the audio code
   for a Mac-friendly library."
2. Or make the change yourself and open a **Pull Request** — GitHub's own
   guide walks through this step by step:
   https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request

No change is too small — even fixing a typo in these docs is a welcome
first contribution.
