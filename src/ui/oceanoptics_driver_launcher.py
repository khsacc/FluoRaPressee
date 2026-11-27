"""Start the Ocean Optics driver installer from the setup wizard or Hardware Configuration.

work/work_updater.md 方針12. Installing the SeaBreeze driver needs administrator
rights, so only the small FluoRaPressee-OceanOpticsDriver.exe is started elevated
(the UAC prompt appears); the app itself keeps running without them. A source
checkout has no such exe and is pointed at setup_oceanoptics.bat instead.
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QMessageBox, QPushButton

from src.core.runtime_env import app_dir, is_frozen

DRIVER_EXE_NAME = "FluoRaPressee-OceanOpticsDriver.exe"
_SW_SHOWNORMAL = 1


def make_driver_button(parent=None) -> QPushButton:
    button = QPushButton("Install Ocean Optics driver… (administrator)")
    button.setToolTip(
        "Checks SeaBreeze device detection and installs the USB driver only if "
        "no instrument is detected. Requires administrator rights."
    )
    button.clicked.connect(lambda: launch_oceanoptics_driver_installer(button.window()))
    return button


def launch_oceanoptics_driver_installer(parent=None) -> bool:
    if not (is_frozen() and sys.platform == "win32"):
        QMessageBox.information(
            parent, "Ocean Optics driver",
            "This copy runs from source. Install the driver by right-clicking "
            "setup_oceanoptics.bat in the FluoRaPressée folder and choosing "
            "\"Run as administrator\".",
        )
        return False

    exe = app_dir() / DRIVER_EXE_NAME
    if not exe.is_file():
        QMessageBox.warning(
            parent, "Ocean Optics driver",
            f"{DRIVER_EXE_NAME} was not found in {app_dir()}.\n"
            "Reinstall FluoRaPressée to restore it.",
        )
        return False

    import ctypes

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(exe), None, str(app_dir()), _SW_SHOWNORMAL
    )
    if result <= 32:
        # Most often the UAC prompt was declined.
        QMessageBox.warning(
            parent, "Ocean Optics driver",
            f"The driver installer was not started (code {result}). It needs "
            "administrator rights; accept the Windows prompt to continue.",
        )
        return False
    return True
