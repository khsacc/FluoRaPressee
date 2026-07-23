#!/usr/bin/env bash
# Install optional Ocean Optics (seabreeze) support into the existing .venv.
# Run ./setup.sh first to create the virtual environment; this script only adds the
# Ocean Optics dependency on top of it. See work/work_OceanOptics.md for background.
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "No .venv found. Run ./setup.sh first."
    exit 1
fi

echo "Installing Ocean Optics (seabreeze) dependencies..."
.venv/bin/pip install -r requirements-oceanoptics.txt

echo "Running seabreeze_os_setup (installs OS-level udev rules on Linux; may need sudo)..."
.venv/bin/seabreeze_os_setup || echo "seabreeze_os_setup failed or was not needed on this OS; see the python-seabreeze documentation."

echo
echo "Ocean Optics setup complete. Set \"model\": \"OceanOptics\" in spectrometerConfig.json to use it."
