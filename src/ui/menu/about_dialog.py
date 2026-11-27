"""Help > About FluoRaPressée."""

from __future__ import annotations

import html
import platform

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, Qt
from PyQt6.QtWidgets import QMessageBox

from src.core.app_logging import current_log_path
from src.core.app_paths import user_data_dir
from src.core.runtime_env import runtime_kind, version_details

REPOSITORY_URL = "https://github.com/khsacc/FluoraPressee"


def show_about_dialog(parent=None):
    log_path = current_log_path()
    rows = [
        ("Version", version_details()),
        ("Run mode", "installed build" if runtime_kind() == "frozen" else "source"),
        ("User data", str(user_data_dir())),
        # Which file to send along with a problem report (方針9).
        ("Log file", str(log_path) if log_path else "console (no log file)"),
        ("Python", platform.python_version()),
        ("Qt / PyQt", f"{QT_VERSION_STR} / {PYQT_VERSION_STR}"),
    ]
    table = "".join(
        f"<tr><td><b>{html.escape(label)}</b>&nbsp;&nbsp;</td>"
        f"<td>{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    text = (
        "<h3>FluoRaPressée</h3>"
        "<p>Spectrometer control &amp; analysis for high-pressure experiments<br>"
        "Hiroki Kobayashi, 2026</p>"
        f"<table>{table}</table>"
        f'<p><a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a></p>'
    )
    box = QMessageBox(parent)
    box.setWindowTitle("About FluoRaPressée")
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText(text)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    box.exec()
