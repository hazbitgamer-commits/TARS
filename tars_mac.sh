#!/bin/bash
# Start TARS Lite on macOS. First time: bash setup_mac.sh
cd "$(dirname "$0")"
[ -d .venv ] || { echo "run 'bash setup_mac.sh' first"; exit 1; }
source .venv/bin/activate
export PYTHONIOENCODING=utf-8
if [ "$1" = "--doctor" ]; then
  python3 doctor.py            # self-diagnosis, fixes what it can
  python3 doctor_mac.py        # plus the mic/speaker listening tests
  exit 0
fi
python3 boot.py --window
