import sys
import os

# First of all: a windowed build has no console (sys.stdout is None), so stdout and
# stderr go to this process's own log file (work/work_updater.md 方針9). Qt-free.
from src.core.app_logging import setup_stdio
setup_stdio("analysis")

os.environ["QT_OPENGL"] = "software"
import gc
gc.enable()

from PyQt6.QtWidgets import QApplication

# Deliberately does not import src.ui / src.hardware.camera / src.hardware.spectrometer / src.api --
# Analysis Mode never touches hardware, so this entry point stays independent of
# the Andor SDK (pylablib/pyserial/ShamrockCIF.dll) and spectrometerConfig.json.
from src.app_bootstrap import apply_window_icon, run_smoke_test
from src.core.app_paths import prepare_user_data
from src.core.runtime_env import hold_installer_mutex
from src.ui.theme import apply_application_style


def main():
    if "--smoke-test" in sys.argv:
        sys.exit(run_smoke_test("analysis"))

    # Analysis Mode reads local_cache.json too, so it migrates as well (方針4).
    prepare_user_data()
    # Lets the installer ask for this app to be closed before updating (方針6).
    hold_installer_mutex()

    from src.ui.analysis_ui import AnalysisWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    apply_application_style(app)

    window = AnalysisWindow()
    apply_window_icon(app, window)
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
