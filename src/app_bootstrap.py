import sys
import os
import json
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from src.ui.theme import apply_application_style

def print_software_and_author_info():
    print(
        "\n================================================================================\n================================================================================\n"\
        "FluoRaPressée: Spectrometer Control & Analysis for high-pressure experiments\nHiroki Kobayashi (The University of Tokyo), 2026\n"\
        "https://github.com/khsacc/FluoraPressee\n"\
        "================================================================================\n================================================================================\n"
    )

def check_and_create_config():
    """Run ConfigWizard to create spectrometerConfig.json, but only on first launch.

    This runs **before SpectrometerGUI is constructed**, so the measurement-rights
    exclusion gate (SpectrometerGUI._acquisition_gate) does not exist yet. The API
    server is not running at this point either, so there is no competitor to
    exclude. ConfigWizard is therefore deliberately out of scope for the exclusion
    gate (work_API_standby.md 方針2 "対象外"). Do not "fix" this later by making it
    take the gate.
    """
    config_path = "spectrometerConfig.json"
    if os.path.exists(config_path):
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
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print(f"spectrometerConfig.json created: model={config.get('model')}")
    except Exception as e:
        QMessageBox.warning(None, "Warning", f"Failed to save config file:\n{e}")


def apply_window_icon(app, window):
    """Set the title-bar/taskbar icon, shared by main.py and analysis_main.py.

    Looks for logo/app_icon.ico (preferred) or logo/app_icon.png at the repo root;
    if neither exists yet this is a no-op so the app keeps running with the default
    Python icon until an icon file is added.

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

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in ("logo/app_icon.ico", "logo/app_icon.png"):
        icon_path = os.path.join(repo_root, candidate)
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            app.setWindowIcon(icon)
            window.setWindowIcon(icon)
            return
