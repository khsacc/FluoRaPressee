"""Help > Check for Updates... (work/work_updater.md 方針7).

Shared by the live GUI and Analysis Mode. It only tells the user about a newer
release and opens URLs in the browser; downloading and running the installer is
left to the user, who decides when (e.g. not in the middle of a measurement).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
)

from src.core.runtime_env import display_version, is_frozen

_CLOSE_FIRST_NOTE = (
    "Close FluoRaPressée before running the downloaded installer. If it is still "
    "running, the installer will ask you to close it."
)
_SOURCE_NOTE = (
    "This copy runs from source. Update it with <code>git pull</code>, then "
    "<code>pip install -r requirements.txt</code>."
)


class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Check for Updates")
        self.resize(560, 440)
        self._info = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Current version: {display_version()}"))

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._status)

        self._notes = QTextBrowser()
        self._notes.setOpenExternalLinks(True)
        self._notes.setVisible(False)
        layout.addWidget(self._notes, stretch=1)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setVisible(False)
        layout.addWidget(self._hint)

        buttons = QDialogButtonBox()
        self._btn_download = QPushButton("Download installer")
        self._btn_release = QPushButton("Open release page")
        self._btn_download.clicked.connect(self._open_installer)
        self._btn_release.clicked.connect(self._open_release_page)
        for button in (self._btn_download, self._btn_release):
            button.setVisible(False)
            buttons.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.set_checking()

    def set_checking(self):
        self._status.setText("Checking for updates…")

    def set_error(self, message):
        self._status.setText(f"Could not check for updates.\n{message}")

    def set_result(self, info):
        self._info = info
        if info is None:
            self._status.setText("You are using the latest version.")
            return
        kind = " (pre-release)" if info.prerelease else ""
        self._status.setText(f"A new version is available: {info.version}{kind}")
        self._notes.setMarkdown(info.notes or "(No release notes.)")
        self._notes.setVisible(True)
        self._hint.setVisible(True)
        if is_frozen():
            # Separate download button: GitHub also attaches "Source code (zip)" to
            # every release page, which is easy to download by mistake.
            self._hint.setText(_CLOSE_FIRST_NOTE)
            self._btn_download.setText(f"Download {info.installer_name}")
            self._btn_download.setVisible(True)
            self._btn_release.setVisible(bool(info.release_url))
        else:
            self._hint.setText(_SOURCE_NOTE)

    def _open_installer(self):
        if self._info is not None:
            QDesktopServices.openUrl(QUrl(self._info.installer_url))

    def _open_release_page(self):
        if self._info is not None and self._info.release_url:
            QDesktopServices.openUrl(QUrl(self._info.release_url))
