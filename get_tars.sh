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
  git -C "$HOME/TARS" pull --ff-only || true
else
  echo "-- downloading TARS"
  git clone https://github.com/hazbitgamer-commits/TARS.git
fi
cd "$HOME/TARS"

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

# 3. the AI model (~4.7 GB — the long part, go make a coffee)
# Lite runs ONE model for everything — leaner on a MacBook's memory
echo "-- downloading TARS's brain model (this is the big download)"
"$OLLAMA_BIN" pull qwen2.5:7b

# 4. Python environment + voice/hearing models
bash setup_mac.sh

echo ""
echo "======================================"
echo "  Done. Start TARS any time with:"
echo "    cd ~/TARS && bash tars_mac.sh"
echo "  Allow Microphone access when asked,"
echo "  then say: Hey TARS"
echo "======================================"
