#!/usr/bin/env bash
# Complete setup for Ocean Optics users: create .venv and install all application
# dependencies plus seabreeze. This script replaces setup.sh for Ocean Optics users.
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Creating virtual environment in .venv ..."
    python3 -m venv .venv
else
    echo ".venv already exists, skipping creation."
fi

echo "Installing application and Ocean Optics dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-oceanoptics.txt
.venv/bin/python -m pip check

echo "Running seabreeze_os_setup (installs OS-level udev rules on Linux; may need sudo)..."
.venv/bin/seabreeze_os_setup || echo "seabreeze_os_setup failed or was not needed on this OS; see the python-seabreeze documentation."

echo
echo "Ocean Optics setup complete. Set \"model\": \"OceanOptics\" in spectrometerConfig.json to use it."
