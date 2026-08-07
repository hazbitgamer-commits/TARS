#!/bin/bash
# Start TARS Lite on macOS. First time: bash setup_mac.sh
cd "$(dirname "$0")"
[ -d .venv ] || { echo "run 'bash setup_mac.sh' first"; exit 1; }
source .venv/bin/activate
export PYTHONIOENCODING=utf-8
if [ "$1" = "--doctor" ]; then
  python3 doctor_mac.py
  exit 0
fi
python3 boot.py --window
