"""Qt selector for active, hardware-compatible configuration records."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ConfigurationBrowserDialog(QDialog):
    """Display the same selectable summaries intended for the future API."""

    def __init__(self, catalog, hardware_context, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.hardware_context = hardware_context
        self.selected_configuration_id = None
        self.selected_slot_id = None

        self.setWindowTitle("Load Configuration")
        self.resize(780, 430)

        layout = QVBoxLayout(self)
        description = QLabel(
            "Only configurations compatible with the connected spectrometer, "
            "camera, grating, and detector ROI are shown."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        controls = QHBoxLayout()
        self.chk_history = QCheckBox("Show version history")
        self.chk_history.toggled.connect(self.refresh)
        controls.addWidget(self.chk_history)
        controls.addStretch()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        controls.addWidget(self.btn_refresh)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Grating", "Centre (nm)", "ROI", "Calibration", "Created"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_load_button)
        self.table.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666;")
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_load = self.buttons.addButton(
            "Load and Apply", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._accept_selection)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.refresh()

    @staticmethod
    def _roi_text(roi):
        if roi["mode"] == "1d_roi":
            return f"Custom {roi['start']}–{roi['end']}"
        if roi["mode"] == "1d_full":
            return "Full range"
        return "2D image"

    @staticmethod
    def _created_text(value):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(value)

    def refresh(self):
        result = self.catalog.list_selectable(
            self.hardware_context,
            active_only=not self.chk_history.isChecked(),
            limit=200,
        )
        self.table.setRowCount(0)
        for summary in result["items"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            grating = summary["grating"]
            values = [
                f"{grating['grooves_per_mm']} g/mm (slot {grating['index']})",
                f"{summary['center_wavelength_nm']:.3f}",
                self._roi_text(summary["roi"]),
                summary["calibration"]["unit"],
                self._created_text(summary["created_at"]),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, summary["configuration_id"])
                    item.setData(Qt.ItemDataRole.UserRole + 1, summary["slot_id"])
                    if not summary["active"]:
                        item.setToolTip("Archived version")
                self.table.setItem(row, column, item)

        if result["items"]:
            kind = "versions" if self.chk_history.isChecked() else "active configurations"
            self.status_label.setText(
                f"{result['total']} compatible {kind} "
                f"(catalog revision {result['catalog_revision']})"
            )
            self.table.selectRow(0)
        else:
            self.status_label.setText(
                "No compatible configuration is available. Calibrate this grating, "
                "centre position, and ROI first."
            )
        self._update_load_button()

    def _update_load_button(self):
        self.btn_load.setEnabled(bool(self.table.selectionModel().selectedRows()))

    def _accept_selection(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        first_item = self.table.item(rows[0].row(), 0)
        self.selected_configuration_id = first_item.data(Qt.ItemDataRole.UserRole)
        self.selected_slot_id = first_item.data(Qt.ItemDataRole.UserRole + 1)
        self.accept()
