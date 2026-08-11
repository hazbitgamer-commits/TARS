#!/bin/bash
# TARS Lite for Mac — one-paste installer.
#   curl -fsSL https://raw.githubusercontent.com/hazbitgamer-commits/TARS/main/get_tars.sh | bash
# Installs: Ollama (+AI models), TARS code, Python environment, voice models.
set -e
echo "======================================"
echo "  TARS Lite — Mac installer"
echo "======================================"

# 0. developer tools (git/python come with them)
if ! xcode-select -p >/dev/null 2>&1; then
  echo "-- macOS needs its developer tools first. A window will pop up:"
  echo "   click Install, wait for it, then PASTE THIS COMMAND AGAIN."
  xcode-select --install || true
  exit 0
fi

# 1. TARS code
cd "$HOME"
if [ -d "$HOME/TARS/.git" ]; then
  echo "-- updating existing TARS"
  cd "$HOME/TARS"
  # This used to be `git pull --ff-only || true`, which SILENTLY did nothing
  # when the pull couldn't fast-forward — an install sat months out of date
  # reporting success. Now it forces the code to match GitHub and says what
  # it ended up on. Personal files (profile.json, .env, logs, vault) are
  # untracked, so none of this touches them.
  git remote set-url origin https://github.com/hazbitgamer-commits/TARS.git
  if ! git fetch --quiet origin main; then
    echo "!! couldn't reach GitHub — check the internet, then run this again"
  fi
  if ! git merge --ff-only origin/main >/dev/null 2>&1; then
    echo "-- local edits were in the way; saving them aside and taking the update"
    git stash push --quiet -m "before-update-$(date +%s)" >/dev/null 2>&1 || true
    git checkout -q -B main origin/main
  fi
  echo "-- now on: $(git log --oneline -1)"
  echo "-- $(ls skills 2>/dev/null | wc -l | tr -d ' ') skills installed"
else
  echo "-- downloading TARS"
  rm -rf "$HOME/TARS.broken" 2>/dev/null || true
  [ -e "$HOME/TARS" ] && mv "$HOME/TARS" "$HOME/TARS.broken"
  git clone https://github.com/hazbitgamer-commits/TARS.git "$HOME/TARS"
  cd "$HOME/TARS"
  echo "-- $(ls skills 2>/dev/null | wc -l | tr -d ' ') skills installed"
fi

# 2. Ollama (the AI brain server)
OLLAMA_BIN="$(command -v ollama || true)"
if [ -z "$OLLAMA_BIN" ] && [ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]; then
  OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
fi
if [ -z "$OLLAMA_BIN" ]; then
  echo "-- installing Ollama (~700 MB)"
  curl -L -o /tmp/Ollama-darwin.zip https://ollama.com/download/Ollama-darwin.zip
  ditto -xk /tmp/Ollama-darwin.zip /Applications/
  rm -f /tmp/Ollama-darwin.zip
  OLLAMA_BIN="/Applications/Ollama.app/Contents/Resources/ollama"
fi
open -a Ollama || true
echo "-- waiting for the Ollama server"
for i in $(seq 1 30); do
  curl -s http://127.0.0.1:11434/api/version >/dev/null && break
  sleep 2
done

# 3. the AI models (~7 GB — the long part, go make a coffee)
# Lite: big model talks, small model routes — quick AND light on memory
echo "-- downloading TARS's brain models (this is the big download)"
"$OLLAMA_BIN" pull qwen2.5:7b
"$OLLAMA_BIN" pull qwen2.5:3b

# 4. Python environment + voice/hearing models
bash setup_mac.sh

echo ""
echo "======================================"
echo "  Done. Start TARS any time with:"
echo "    cd ~/TARS && bash tars_mac.sh"
echo "  Allow Microphone access when asked,"
echo "  then say: Hey TARS"
echo "======================================"
