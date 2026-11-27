import sys
import os
import traceback
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from src.core.app_logging import current_log_path
from src.core.app_paths import (
    bundled_resource_path,
    spectrometer_config_path,
    user_data_dir,
    write_json_atomic,
)
from src.core.runtime_env import (
    INSTRUMENT_BUSY,
    INSTRUMENT_BUSY_OTHER_USER,
    acquire_instrument_mutex,
    version_details,
)
from src.ui.theme import apply_application_style

def print_software_and_author_info():
    print(
        "\n================================================================================\n================================================================================\n"\
        "FluoRaPressée: Spectrometer Control & Analysis for high-pressure experiments\nHiroki Kobayashi, 2026\n"\
        "https://github.com/khsacc/FluoraPressee\n"\
        f"Version: {version_details()}\n"\
        "================================================================================\n================================================================================\n"
    )
    print(f"User data: {user_data_dir()}")
    log_path = current_log_path()
    if log_path is not None:
        print(f"Log file: {log_path}")


def instrument_startup_refusal(debug, acquire=acquire_instrument_mutex):
    """Return a message if another process already uses the instrument, else None.

    Only a hardware-mode live GUI takes the PC-wide instrument mutex (work_updater.md
    方針13); --debug and Analysis Mode never touch the instrument and are never
    refused. An unverifiable result lets start-up continue.
    """
    if debug:
        return None
    result = acquire()
    if result == INSTRUMENT_BUSY:
        return (
            "Another FluoRaPressée is already using the instrument on this PC.\n\n"
            "Close it first, or start this one in debug mode."
        )
    if result == INSTRUMENT_BUSY_OTHER_USER:
        return (
            "Another user on this PC is already running FluoRaPressée with the "
            "instrument.\n\nOnly one FluoRaPressée can control the instrument at a time."
        )
    return None


def run_smoke_test(kind="live"):
    """Import everything a build needs, touch no hardware, return an exit code.

    Used by packaging/build_windows.ps1 before and after PyInstaller and by the
    release workflow after installing, to catch modules PyInstaller missed. Each
    step is printed (to the log file in a windowed build).
    """
    steps = [
        ("PyQt6 widgets", lambda: __import__("PyQt6.QtWidgets")),
        ("pyqtgraph", lambda: __import__("pyqtgraph")),
        ("scipy.optimize", lambda: __import__("scipy.optimize")),
        ("Analysis Mode", lambda: __import__("src.ui.analysis_ui")),
    ]
    if kind == "live":
        steps += [
            ("Andor backend", lambda: __import__("src.hardware.camera_andor")),
            ("Andor spectrometer", lambda: __import__("src.hardware.spectrometer_andor")),
            ("Princeton Instruments backend", lambda: __import__("src.hardware.camera_princeton")),
            ("Princeton Instruments spectrometer", lambda: __import__("src.hardware.spectrometer_princeton")),
            ("Ocean Optics backend", lambda: __import__("src.hardware.camera_oceanoptics")),
            ("Ocean Optics spectrometer", lambda: __import__("src.hardware.spectrometer_oceanoptics")),
            # The backends above swallow ImportError (debug mode must work without
            # an SDK), so import pyLabLib's device layer directly to catch a build
            # that is missing it. Importing loads no vendor DLL.
            ("pyLabLib Andor", lambda: _smoke_pylablib("pylablib.devices.Andor")),
            ("pyLabLib PICam", lambda: _smoke_pylablib("pylablib.devices.PrincetonInstruments.picam")),
            ("seabreeze", _smoke_seabreeze),
            ("pythonnet", lambda: __import__("pythonnet")),
            ("API server", _smoke_api_server),
            ("Live GUI", lambda: __import__("src.ui.main_window")),
        ]
    failures = 0
    print(f"Smoke test ({kind}), version {version_details()}")
    for label, step in steps:
        try:
            step()
        except Exception:
            failures += 1
            print(f"FAILED: {label}")
            traceback.print_exc()
        else:
            print(f"ok: {label}")
    print("Smoke test passed." if not failures else f"Smoke test failed ({failures}).")
    sys.stdout.flush()
    return 0 if failures == 0 else 1


def _smoke_pylablib(module_name):
    from src.hardware.pylablib_loader import import_pylablib_module

    import_pylablib_module(module_name)


def _smoke_seabreeze():
    # Selecting the backend and importing spectrometers loads cseabreeze and its
    # libusb DLL - what a build most often misses - without opening any device.
    import seabreeze

    seabreeze.use("cseabreeze")
    import seabreeze.spectrometers  # noqa: F401


def _smoke_api_server():
    # Config.load() imports uvicorn's loop/protocol/lifespan modules - the hidden
    # imports PyInstaller tends to miss - without binding a socket.
    import uvicorn

    from src.api.server import create_app

    app = create_app(object(), None)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    config.load()

def check_and_create_config():
    """Run ConfigWizard to create spectrometerConfig.json, but only on first launch.

    This runs **before SpectrometerGUI is constructed**, so the measurement-rights
    exclusion gate (SpectrometerGUI._acquisition_gate) does not exist yet. The API
    server is not running at this point either, so there is no competitor to
    exclude. ConfigWizard is therefore deliberately out of scope for the exclusion
    gate (work_API_standby.md 方針2 "対象外"). Do not "fix" this later by making it
    take the gate.
    """
    config_path = spectrometer_config_path()
    if config_path.exists():
        return

    app_temp = QApplication.instance()
    if not app_temp:
        app_temp = QApplication(sys.argv)
    apply_application_style(app_temp)

    from src.ui.config_wizard import ConfigWizard
    wizard = ConfigWizard()
    if wizard.exec() == QDialog.DialogCode.Accepted:
        config = wizard.result_config()
    else:
        QMessageBox.information(
            None,
            "Setup cancelled",
            "Setup wizard was cancelled.\n"
            "The application will now close without creating spectrometerConfig.json.",
        )
        sys.exit(0)

    try:
        write_json_atomic(config_path, config)
        print(f"spectrometerConfig.json created at {config_path}: model={config.get('model')}")
    except Exception as e:
        QMessageBox.warning(None, "Warning", f"Failed to save config file:\n{e}")


def apply_window_icon(app, window):
    """Set the title-bar/taskbar icon, shared by main.py and analysis_main.py.

    Looks for logo/app_icon.ico (preferred) or logo/app_icon.png among the bundled
    files (the repo root from source); if neither exists yet this is a no-op so the
    app keeps running with the default Python icon until an icon file is added.

    On Windows, the taskbar groups windows by the launching executable (python.exe),
    so setWindowIcon alone is not enough to replace the Python icon there -
    SetCurrentProcessExplicitAppUserModelID gives this app its own identity first.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "FluoraPressee.SpectrometerGUI"
            )
        except Exception:
            pass

    from PyQt6.QtGui import QIcon

    for candidate in ("logo/app_icon.ico", "logo/app_icon.png"):
        icon_path = str(bundled_resource_path(candidate))
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            app.setWindowIcon(icon)
            window.setWindowIcon(icon)
            return
