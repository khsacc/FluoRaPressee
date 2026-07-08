#!/usr/bin/env bash
# Launch the app in debug mode (simulated camera/spectrometer, no hardware needed).
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

.venv/bin/python main.py --debug
