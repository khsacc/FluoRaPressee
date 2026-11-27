import sys
import os

# First of all: a windowed build has no console (sys.stdout is None), so stdout and
# stderr go to this process's own log file (work/work_updater.md 方針9). Qt-free.
from src.core.app_logging import setup_stdio
setup_stdio("live")

os.environ["QT_OPENGL"] = "software"
import gc
gc.enable()

from PyQt6.QtWidgets import QApplication, QMessageBox

# Import the required classes and functions from ui.py
from src.app_bootstrap import (
    apply_window_icon,
    check_and_create_config,
    instrument_startup_refusal,
    print_software_and_author_info,
    run_smoke_test,
)
from src.core.app_paths import prepare_user_data
from src.core.runtime_env import hold_installer_mutex
from src.ui.theme import apply_application_style

def main():
    if "--smoke-test" in sys.argv:
        sys.exit(run_smoke_test("live"))

    print_software_and_author_info()
    # Before anything reads a setting (方針4).
    prepare_user_data()
    # Lets the installer ask for this app to be closed before updating (方針6).
    hold_installer_mutex()

    debug_mode = "--debug" in sys.argv
    print("debug_mode ", debug_mode)

    # Reuse the existing QApplication instance if one is already running, otherwise create one
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    apply_application_style(app)

    # Only one hardware-mode live GUI may drive the instrument on this PC (方針13).
    refusal = instrument_startup_refusal(debug_mode)
    if refusal:
        QMessageBox.critical(None, "FluoRaPressée is already running", refusal)
        sys.exit(1)

    check_and_create_config()

    # Imported only now: SpectrometerGUI pulls in the hardware layer, which the
    # smoke test above must be able to report on rather than crash in.
    from src.ui import SpectrometerGUI

    # SpectrometerGUI builds its own GuiBridge (see its __init__).
    window = SpectrometerGUI(debug=debug_mode)
    apply_window_icon(app, window)
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
