#!/bin/bash
# TARS Lite — one-time Mac setup. Run: bash setup_mac.sh
set -e
cd "$(dirname "$0")"
echo "== TARS Lite setup for macOS =="

command -v python3 >/dev/null || { echo "python3 not found — install Xcode Command Line Tools first (xcode-select --install)"; exit 1; }

echo "-- creating private Python environment (.venv)"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q

echo "-- installing libraries"
pip install -r requirements_lite.txt

echo "-- downloading hearing model (Vosk, ~40 MB)"
mkdir -p wakeword
if [ ! -d "wakeword/vosk-model-small-en-us-0.15" ]; then
  curl -L -o /tmp/vosk.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  unzip -q /tmp/vosk.zip -d wakeword/
  rm /tmp/vosk.zip
fi

echo "-- downloading voice model (Kokoro, ~340 MB)"
mkdir -p models
[ -f models/kokoro-v1.0.onnx ] || curl -L -o models/kokoro-v1.0.onnx \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
[ -f models/voices-v1.0.bin ] || curl -L -o models/voices-v1.0.bin \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

command -v ollama >/dev/null && echo "-- Ollama found" || \
  echo "!! Ollama not found — install it from https://ollama.com/download/mac and run the 'ollama pull' commands in INSTALL_MAC.md"

echo "== done. Start TARS with: bash tars_mac.sh =="
