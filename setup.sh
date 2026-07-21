#!/usr/bin/env bash
# Create a virtual environment (.venv) and install dependencies.
# Run this once after cloning the repository.
# Note: this project targets Windows for hardware control; use this script
# only for --debug UI development on macOS/Linux.
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Creating virtual environment in .venv ..."
    python3 -m venv .venv
else
    echo ".venv already exists, skipping creation."
fi

echo "Installing dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo
echo "Setup complete. Use ./FluoRaPressee_run_debug.sh to launch the app in debug mode."
