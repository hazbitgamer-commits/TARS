#!/usr/bin/env bash
# TARS Lite installer for macOS / Linux. Run: bash setup_mac.sh
#
# Written for people who have never touched Python: no Python knowledge assumed, every
# step says what it's doing, and anything that fails explains what to do
# instead of dumping a stack trace. Safe to re-run — it skips what's done.
#
# Deliberately not `set -e`: one failed optional download shouldn't abort
# an install that's otherwise fine.
set -u
cd "$(dirname "$0")"

BLUE=$'\033[36m'; DIM=$'\033[2m'; WARN=$'\033[33m'; BAD=$'\033[31m'; OFF=$'\033[0m'
step() { echo "${BLUE}==${OFF} $*"; }
note() { echo "${DIM}   $*${OFF}"; }
warn() { echo "${WARN}!!${OFF} $*"; }
fail() { echo "${BAD}xx${OFF} $*"; }

echo
echo "${BLUE}TARS Lite — setup${OFF}"
echo "${DIM}   a voice assistant that runs entirely on this machine${OFF}"
echo

# ---------- python ----------
step "Checking Python"
if ! command -v python3 >/dev/null; then
  fail "python3 not found."
  note "Install Apple's developer tools first:  xcode-select --install"
  exit 1
fi
PY_VER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)'; then
  fail "TARS needs Python 3.10 or newer (this is $PY_VER)."
  note "Get a newer one:  brew install python@3.12"
  exit 1
fi
note "python3 $PY_VER"

# ---------- system libraries ----------
# sounddevice is a WRAPPER around PortAudio, which macOS does not ship.
# pip installs happily and then every import fails with "PortAudio library
# not found" — which reads as "voice recognition wouldn't install".
step "Checking the audio library (PortAudio)"
if python3 -c "import ctypes.util,sys; sys.exit(0 if ctypes.util.find_library('portaudio') else 1)" 2>/dev/null; then
  note "PortAudio already here"
elif command -v brew >/dev/null; then
  note "installing PortAudio with Homebrew…"
  brew install portaudio >/dev/null 2>&1 && note "PortAudio in" || \
    warn "PortAudio wouldn't install — the microphone won't work until it does"
else
  warn "PortAudio is missing and Homebrew isn't installed."
  note "TARS can't hear you without it. Install Homebrew from https://brew.sh"
  note "then run:  brew install portaudio  &&  bash setup_mac.sh"
fi

# ---------- virtual environment ----------
step "Setting up its own Python environment"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip -q

step "Installing the core libraries (a few minutes the first time)"
if ! pip install -q -r requirements_lite.txt; then
  fail "Some libraries wouldn't install."
  note "Scroll up to the FIRST red error — that's the one that matters."
  exit 1
fi
note "core libraries in"

# ---------- optional: eyes ----------
step "Installing camera extras (hand signals + the camera HUD)"
if pip install -q opencv-python mediapipe 2>/dev/null; then
  note "camera support in"
  CAMERA=yes
else
  warn "camera extras wouldn't install — everything else still works."
  note "TARS will just say the camera isn't available on this machine."
  CAMERA=no
fi

# ---------- models ----------
step "Downloading the voice models"
mkdir -p wakeword models
if [ ! -d wakeword/vosk-model-small-en-us-0.15 ]; then
  note "wake word, so 'Hey TARS' works (~40MB)…"
  if curl -fL# -o /tmp/vosk.zip \
       https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip; then
    unzip -q -o /tmp/vosk.zip -d wakeword && rm -f /tmp/vosk.zip
  else
    warn "wake-word model failed — 'Hey TARS' won't work until it downloads."
  fi
fi
if [ ! -f models/kokoro-v1.0.onnx ]; then
  note "his voice (~340MB)…"
  curl -fL# -o models/kokoro-v1.0.onnx \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    || warn "voice model failed — he'll fall back to the built-in Mac voice."
fi
[ -f models/voices-v1.0.bin ] || curl -fL# -o models/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin \
  || warn "voice pack failed."
if [ "$CAMERA" = yes ] && [ ! -f models/gesture_recognizer.task ]; then
  note "hand signals (~8MB)…"
  curl -fL# -o models/gesture_recognizer.task \
    https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task \
    || warn "gesture model failed — hand signals will be off."
fi

# ---------- the big brain (optional) ----------
# The Python SDK alone isn't enough: it drives the `claude` command, so
# without that the token looks accepted and nothing ever runs.
step "Checking the big brain (optional — for self-teaching)"
if command -v claude >/dev/null; then
  note "claude command found"
elif command -v npm >/dev/null; then
  note "installing the claude command…"
  npm install -g @anthropic-ai/claude-code >/dev/null 2>&1 \
    && note "claude command in" \
    || warn "couldn't install it — big jobs stay off, everything else works"
else
  warn "Node isn't installed, so the big brain can't run."
  note "Only needed for self-teaching. To enable it later:"
  note "  brew install node && npm install -g @anthropic-ai/claude-code"
fi

# ---------- the thinking ----------
step "Setting up his brain (Ollama)"
if ! command -v ollama >/dev/null; then
  warn "Ollama isn't installed — that's the part that does the thinking."
  note "Get it from https://ollama.com/download/mac, then run this script again."
  note "Everything else is ready, so the second run only takes a minute."
else
  note "Ollama found — pulling the two models he needs (~6GB total)."
  note "Fine to leave this running and come back."
  ollama pull qwen2.5:7b || warn "couldn't pull qwen2.5:7b (the talking brain)"
  ollama pull qwen2.5:3b || warn "couldn't pull qwen2.5:3b (the quick router)"
  note "brain ready"
fi

# ---------- check it over ----------
step "Checking everything over"
if [ -f doctor_mac.py ]; then
  python3 doctor_mac.py || note "(the self-check found problems — see above)"
fi

echo
echo "${BLUE}Done.${OFF}  Start him with:   ${BLUE}bash tars_mac.sh${OFF}"
echo "${DIM}   Then say \"Hey TARS\" — or open http://127.0.0.1:8765 and type instead.${OFF}"
echo "${DIM}   macOS will ask for microphone (and camera) permission the first time.${OFF}"
echo
