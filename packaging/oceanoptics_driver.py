"""Entry point of FluoRaPressee-OceanOpticsDriver.exe (work/work_updater.md 方針12).

Does what the second half of setup_oceanoptics.bat does, for the built version:
install the Windows SeaBreeze USB driver, then check that an instrument can be
enumerated. A console executable, so the user can follow the progress. Started
elevated by the installer ([Run] Verb: runas), by the app (ShellExecuteW "runas")
or from the Start menu shortcut.
"""

import ctypes
import os
import sys

# Running from a frozen build, the repository's "src" package sits next to this file
# only in source checkouts; make it importable in both cases.
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(os.path.dirname(_HERE), "src")):
    sys.path.insert(0, os.path.dirname(_HERE))

from src.core.runtime_env import hold_installer_mutex, version_details  # noqa: E402


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _pause():
    try:
        input("\nPress Enter to close this window.")
    except (EOFError, KeyboardInterrupt):
        pass


def _install_driver() -> bool:
    # seabreeze_os_setup is what setup_oceanoptics.bat runs as an executable; here it
    # is called in-process because a frozen build has no Scripts\ folder.
    try:
        from seabreeze.os_setup import main as os_setup_main
    except Exception as exc:
        print(f"ERROR: seabreeze's driver setup is not available in this build: {exc}")
        return False
    try:
        result = os_setup_main()
    except SystemExit as exc:
        result = exc.code
    except Exception as exc:
        print(f"ERROR: seabreeze driver setup failed: {exc}")
        return False
    if result not in (None, 0):
        print(f"ERROR: seabreeze driver setup failed (exit code {result}).")
        return False
    return True


def _verify_device() -> bool:
    try:
        import seabreeze

        seabreeze.use("cseabreeze")
        from seabreeze.spectrometers import list_devices

        devices = list_devices()
    except Exception as exc:
        print(f"ERROR: SeaBreeze could not enumerate devices: {exc}")
        return False
    print("Detected:", devices)
    return bool(devices)


def main() -> int:
    print(f"FluoRaPressée - Ocean Optics driver installation ({version_details()})\n")
    # Keeps the installer from replacing files while this tool runs (方針6).
    hold_installer_mutex()
    if sys.platform != "win32":
        print("The Ocean Optics driver installation is only needed on Windows.")
        return 0
    if not _is_admin():
        print("ERROR: administrator rights are required.")
        print("Start this tool again and accept the Windows (UAC) prompt.")
        return 1

    print("Installing the Windows SeaBreeze driver...")
    if not _install_driver():
        return 1

    print("\nChecking that the instrument can be found...")
    if not _verify_device():
        print("ERROR: SeaBreeze still cannot detect an instrument. "
              "Unplug and reconnect it, then run this tool again.")
        return 1

    print("\nOcean Optics driver installation complete.")
    print('Choose "OceanOptics" in the setup wizard or Hardware Configuration to use it.')
    return 0


if __name__ == "__main__":
    code = main()
    _pause()
    sys.exit(code)
