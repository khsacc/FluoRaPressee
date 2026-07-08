import sys
import os
import json
from PyQt5.QtWidgets import QApplication, QInputDialog, QMessageBox

def print_software_and_author_info():
    print(
        "\n================================================================================\n================================================================================\n"\
        "FluoraPressée: Spectrometer Control & Analysis for high-pressure experiments\nHiroki Kobayashi (The University of Tokyo), 2026\n"\
        "https://github.com/khsacc/AndorPy\n"\
        "================================================================================\n================================================================================\n"
    )

def check_and_create_config():
    config_path = "spectrometerConfig.json"
    default_config = {
        "model": "Andor",
        "com_port": "COM3",
        "grating": [
            {
                "index": 1,
                "grooves": 600,
                "defaultROI": {"from": 100, "to": 140}
            },
            {
                "index": 2,
                "grooves": 1200,
                "defaultROI": {"from": 100, "to": 140}
            },
            {
                "index": 3,
                "grooves": 1800,
                "defaultROI": {"from": 100, "to": 140}
            }
        ],
        "flip_x": False
    }

    if not os.path.exists(config_path):
        app_temp = QApplication.instance()
        if not app_temp:
            app_temp = QApplication(sys.argv)

        text, ok = QInputDialog.getText(
            None,
            "Spectrometer Configuration",
            "spectrometerConfig.json not found.\nPlease enter the gratings (grooves/mm) separated by commas\n(e.g., 600, 1200, 1800):"
        )

        gratings_int = []
        if ok and text:
            gratings_str = [g.strip() for g in text.split(",") if g.strip()]
            for g in gratings_str:
                try:
                    gratings_int.append(int(g))
                except ValueError:
                    pass

        if gratings_int:
            new_grating = []
            for i, g_val in enumerate(gratings_int):
                new_grating.append({
                    "index": i + 1,
                    "grooves": g_val,
                    "defaultROI": {"from": 100, "to": 140}
                })
            default_config["grating"] = new_grating

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
        except Exception as e:
            QMessageBox.warning(None, "Warning", f"Failed to save config file:\n{e}")
