"""Hardware > Check Camera Status dialog.

Reads a snapshot of PICam camera parameters (identification, exposure/acquisition,
readout amplifier/ADC/EM gain, shutter, temperature/cooling) and lists them in a simple
two-column table. Only meaningful for Princeton Instruments (PICam) cameras — the button
is disabled with an explanatory message for any camera thread that doesn't expose
`request_status()`/`status_ready` (e.g. the Andor backend).

Fetching a status snapshot touches hardware, so it must only run while the camera is
idle: the button is disabled whenever the camera thread reports `is_measuring`, and the
dialog polls that flag on a timer since it stays open (non-modal) while the operator
keeps using the main window.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QBrush, QColor

_POLL_INTERVAL_MS = 500


class CameraStatusDialog(QDialog):
    def __init__(self, camera_thread, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Check Camera Status")
        self.resize(480, 560)

        self._thread = camera_thread
        self._supported = hasattr(camera_thread, "request_status") and hasattr(camera_thread, "status_ready")
        if self._supported:
            camera_thread.status_ready.connect(self._on_status_ready)

        layout = QVBoxLayout(self)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._btn_get_status = QPushButton("Get current camera status")
        self._btn_get_status.clicked.connect(self._on_get_status_clicked)
        layout.addWidget(self._btn_get_status)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.close)
        layout.addWidget(buttons)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh_button_state)

        self._refresh_button_state()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_button_state()
        self._poll_timer.start()

    def hideEvent(self, event):
        self._poll_timer.stop()
        super().hideEvent(event)

    def _refresh_button_state(self):
        if not self._supported:
            self._btn_get_status.setEnabled(False)
            self._status_label.setText(
                "Camera status reporting is not available for this camera model."
            )
            return

        is_measuring = getattr(self._thread, "is_measuring", False)
        if is_measuring:
            self._btn_get_status.setEnabled(False)
            self._status_label.setText(
                "A measurement is currently running. Stop the measurement to check camera status."
            )
        else:
            self._btn_get_status.setEnabled(True)
            self._status_label.setText("")

    def _on_get_status_clicked(self):
        if not self._supported or getattr(self._thread, "is_measuring", False):
            self._refresh_button_state()
            return
        self._btn_get_status.setEnabled(False)
        self._status_label.setText("Fetching camera status...")
        self._thread.request_status()

    def _on_status_ready(self, snapshot):
        self._table.setRowCount(0)
        for section, rows in snapshot.items():
            self._add_section_header(section)
            for label, value in rows:
                self._add_row(label, value)
        self._table.resizeRowsToContents()
        self._refresh_button_state()

    def _add_section_header(self, title):
        row = self._table.rowCount()
        self._table.insertRow(row)
        item = QTableWidgetItem(title)
        font = QFont()
        font.setBold(True)
        item.setFont(font)
        item.setBackground(QBrush(QColor("#e0e0e0")))
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        self._table.setItem(row, 0, item)
        self._table.setSpan(row, 0, 1, 2)

    def _add_row(self, label, value):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(str(label)))
        self._table.setItem(row, 1, QTableWidgetItem(str(value)))
