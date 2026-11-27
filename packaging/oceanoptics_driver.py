"""Entry point of FluoRaPressee-OceanOpticsDriver.exe (work/work_updater.md 方針12).

Shared by setup_oceanoptics.bat and the built version: first check whether an
instrument can already be enumerated, and only attempt USB driver installation
when necessary. A console executable, so the user can follow the progress. Started
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
    # Called in-process because a frozen build has no Scripts\ folder. Upstream
    # can exit 0 even after pnputil errors; this result alone cannot confirm setup.
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
        print(f"SeaBreeze could not enumerate devices: {exc}")
        return False
    print("Detected:", devices)
    return bool(devices)


def main() -> int:
    print(f"FluoRaPressee - Ocean Optics driver check/setup ({version_details()})\n")
    # Keeps the installer from replacing files while this tool runs (方針6).
    hold_installer_mutex()
    if sys.platform != "win32":
        print("The Ocean Optics driver installation is only needed on Windows.")
        return 0

    print("Connect the intended instrument and close other programs using it.")
    print("Checking whether SeaBreeze can already find an instrument...")
    if _verify_device():
        print("\nAn instrument is already detected. No driver installation is needed.")
        print("No USB drivers were changed. Confirm acquisition in FluoRaPressee.")
        return 0

    if not _is_admin():
        print("ERROR: administrator rights are required.")
        print("Start this tool again and accept the Windows (UAC) prompt.")
        return 1

    print("\nNo instrument detected. Trying the Windows SeaBreeze driver package...")
    print("This package contains INF files for many different instrument models.")
    print("Some have missing/invalid signatures and may be rejected by Windows.")
    print("Your instrument needs a compatible driver, not every INF in the package.")
    setup_ok = _install_driver()

    print("\nChecking that the instrument can be found...")
    if not _verify_device():
        print("ERROR: No instrument detected; driver setup is NOT confirmed.")
        print("Connect the instrument, close other programs using it, and unplug/reconnect it.")
        print("A restart may be needed. Then run this tool again.")
        print("If detection still fails, check the driver assigned to this model in Device Manager.")
        print("A signature/hash error for your model needs a valid compatible driver package;")
        print("do not disable Windows driver signature enforcement to install rejected files.")
        return 1

    if not setup_ok:
        print("WARNING: Driver setup reported a failure, but SeaBreeze now detects an instrument.")
    print("\nSeaBreeze device detection confirmed.")
    print("Rejected INF files for other models do not need to be installed for this instrument.")
    print("This confirms detection only. Confirm acquisition in FluoRaPressee.")
    print('Choose "OceanOptics" in the setup wizard or Hardware Configuration to use it.')
    return 0


if __name__ == "__main__":
    code = main()
    _pause()
    sys.exit(code)
