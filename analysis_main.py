import sys
import os

sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

os.environ["QT_OPENGL"] = "software"
import gc
gc.enable()

from PyQt6.QtWidgets import QApplication

# Deliberately does not import src.ui / src.hardware.camera / src.hardware.spectrometer / src.api --
# Analysis Mode never touches hardware, so this entry point stays independent of
# the Andor SDK (pylablib/pyserial/ShamrockCIF.dll) and spectrometerConfig.json.
from src.ui.analysis_ui import AnalysisWindow
from src.ui.theme import apply_application_style
from src.app_bootstrap import apply_window_icon


def main():
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
