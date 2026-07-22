import sys
import os
import json
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from src.ui_theme import apply_application_style

def print_software_and_author_info():
    print(
        "\n================================================================================\n================================================================================\n"\
        "FluoraPressée: Spectrometer Control & Analysis for high-pressure experiments\nHiroki Kobayashi (The University of Tokyo), 2026\n"\
        "https://github.com/khsacc/FluoraPressee\n"\
        "================================================================================\n================================================================================\n"
    )

_FALLBACK_CONFIG = {
    "model": "Andor",
    "grating": [
        {"index": 1, "grooves": 600,  "defaultROI": {"from": 100, "to": 140}},
        {"index": 2, "grooves": 1200, "defaultROI": {"from": 100, "to": 140}},
        {"index": 3, "grooves": 1800, "defaultROI": {"from": 100, "to": 140}},
    ],
    "flip_x": False,
    "default_temperature": -65,
    "default_fan_mode": "full",
    "hardware_identity": {
        "spectrometer": {"model": None, "serial_number": None},
        "camera": {"model": None, "serial_number": None},
    },
}

def check_and_create_config():
    config_path = "spectrometerConfig.json"
    if os.path.exists(config_path):
        return

    app_temp = QApplication.instance()
    if not app_temp:
        app_temp = QApplication(sys.argv)
    apply_application_style(app_temp)

    from src.config_wizard import ConfigWizard
    wizard = ConfigWizard()
    if wizard.exec() == QDialog.DialogCode.Accepted:
        config = wizard.result_config()
    else:
        QMessageBox.information(
            None,
            "Using default configuration",
            "Setup wizard was cancelled.\n"
            "A default Andor configuration will be used.\n"
            "You can edit spectrometerConfig.json manually to adjust settings.",
        )
        config = _FALLBACK_CONFIG

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print(f"spectrometerConfig.json created: model={config.get('model')}")
    except Exception as e:
        QMessageBox.warning(None, "Warning", f"Failed to save config file:\n{e}")
