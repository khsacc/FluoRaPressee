"""Entry point of FluoRaPressee-OceanOpticsDriver.exe (work/work_updater.md 方針12).

Shared by setup_oceanoptics.bat and the built version: first check whether an
instrument can already be enumerated, and only attempt USB driver installation
when necessary. A console executable, so the user can follow the progress. Started
elevated by the installer ([Run] Verb: runas), by the app (ShellExecuteW "runas")
or from the Start menu shortcut.
"""

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

# Running from a frozen build, the repository's "src" package sits next to this file
# only in source checkouts; make it importable in both cases.
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(os.path.dirname(_HERE), "src")):
    sys.path.insert(0, os.path.dirname(_HERE))

from src.core.runtime_env import hold_installer_mutex, version_details  # noqa: E402
from src.hardware.status import oceanoptics_windows  # noqa: E402

_DRIVER_ARCHIVE_URL = (
    "https://raw.githubusercontent.com/ap--/python-seabreeze/master/os_support/windows-driver-files.zip"
)


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


def _extract_driver_package(archive_path: Path, package_dir: Path) -> None:
    with ZipFile(archive_path) as archive:
        # Several XP variants advertise the same hardware IDs as the regular INF.
        # Keep catalog files and subdirectories intact for the Windows signature check.
        members = (name for name in archive.namelist() if not name.lower().endswith("_xp.inf"))
        archive.extractall(package_dir, members)


def _install_matching_infs(api, handle, devices, package_dir: Path) -> bool:
    paths = set()
    all_matched = True
    for device in devices:
        ids = ", ".join(device.hardware_ids)
        try:
            inf = oceanoptics_windows.best_matching_inf(api, handle, device, package_dir)
        except (OSError, ValueError) as exc:
            print(f"ERROR: Could not check driver compatibility for {ids}: {exc}")
            all_matched = False
            continue
        if inf is None:
            print(f"ERROR: No INF in the SeaBreeze package matches {ids} on this Windows version.")
            all_matched = False
            continue
        print(f"{ids} -> {inf.name}", flush=True)
        paths.add(inf)

    if not paths:
        return False
    try:
        answer = input("Install the matched USB driver packages? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        print("USB driver installation cancelled.")
        return False

    system_dir = Path(os.environ["SystemRoot"]) / "System32"
    if os.environ.get("PROCESSOR_ARCHITEW6432"):
        # A 32-bit source Python on 64-bit Windows needs the native PnPUtil.
        system_dir = system_dir.with_name("Sysnative")
    pnputil = system_dir / "pnputil.exe"
    all_installed = True
    for inf in sorted(paths):
        result = subprocess.run([str(pnputil), "/add-driver", str(inf), "/install"], check=False)
        if result.returncode == 3010:
            print(f"Windows requires a restart to complete installation of {inf.name}.")
        elif result.returncode != 0:
            print(f"ERROR: PnPUtil failed for {inf.name} (exit code {result.returncode}).")
            all_installed = False
    return all_matched and all_installed


def _install_driver(api, handle, devices) -> bool:
    try:
        with TemporaryDirectory(prefix="fluora-oceanoptics-") as tmp:
            download = Path(tmp) / "drivers.zip"
            print("\nDownloading the SeaBreeze Windows USB driver package...", flush=True)
            with urlopen(_DRIVER_ARCHIVE_URL, timeout=30) as response, download.open("wb") as output:
                shutil.copyfileobj(response, output)
            package_dir = (download.parent / "package").resolve()
            _extract_driver_package(download, package_dir)
            return _install_matching_infs(api, handle, devices, package_dir)
    except (OSError, BadZipFile, KeyError) as exc:
        print(f"ERROR: SeaBreeze driver setup failed: {exc}")
        return False


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
    detected = _verify_device()
    try:
        with oceanoptics_windows.connected_devices() as (api, handle, devices):
            ready = oceanoptics_windows.seabreeze_interfaces(api) if detected and devices else set()
            targets = [device for device in devices if device.instance_id not in ready]
            if detected and not targets:
                print("\nNo USB drivers were changed. Confirm acquisition in FluoRaPressee.")
                return 0
            if not targets:
                print("ERROR: Windows found no connected Ocean Optics USB device.")
                print("Connect the instrument and check that it appears in Device Manager.")
                return 1
            if not _is_admin():
                print("ERROR: administrator rights are required.")
                print("Start this tool again and accept the Windows (UAC) prompt.")
                return 1
            setup_ok = _install_driver(api, handle, targets)

        print("\nChecking that the instrument can be found...")
        detected = _verify_device()
        ready = oceanoptics_windows.seabreeze_interfaces(api) if detected else set()
    except OSError as exc:
        print(f"ERROR: Could not read Windows USB device information: {exc}")
        return 1

    missing = [device.hardware_ids[0] for device in targets if device.instance_id not in ready]
    if missing:
        print("ERROR: Driver setup is NOT confirmed for: " + ", ".join(missing))
        print("Connect the instrument, close other programs using it, and unplug/reconnect it.")
        print("A restart may be needed. Then run this tool again.")
        print("If detection still fails, check the driver assigned to this model in Device Manager.")
        print("A signature/hash error for your model needs a valid compatible driver package;")
        print("do not disable Windows driver signature enforcement to install rejected files.")
        return 1

    if not setup_ok:
        print("WARNING: Driver setup reported a failure, but SeaBreeze now detects an instrument.")
    print("\nSeaBreeze device detection confirmed.")
    print("This confirms detection only. Confirm acquisition in FluoRaPressee.")
    print('Choose "OceanOptics" in the setup wizard or Hardware Configuration to use it.')
    return 0


if __name__ == "__main__":
    code = main()
    _pause()
    sys.exit(code)
