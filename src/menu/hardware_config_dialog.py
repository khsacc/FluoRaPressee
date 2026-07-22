"""Hardware > Hardware Configuration dialog — lets the operator edit spectrometerConfig.json
from a running app.

Edits happen on a private working copy; nothing touches the caller's config dict or
spectrometerConfig.json until Apply/OK. Cancel discards the working copy untouched.

On a successful Apply/OK, `applied` is emitted with the merged config and the set of tabs
whose keys actually changed ("hardware", "grating", "display"). The caller (see
ConfigMixin.on_open_hardware_config_clicked in src/ui_mixins/config_mixin.py) uses that set to
decide what can be refreshed live vs. what needs an app restart: "model"/"com_port"/"dll_path"/
"PIcam_dll_path"/"camera_serial_number" are only ever read once, when CameraThread/
SpectrometerController are constructed at startup (see src/camera.py, src/spectrometer.py), so
changes to those always require a restart to take effect — grating/display changes don't.
"""
from __future__ import annotations

import copy

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
    QComboBox, QLineEdit, QCheckBox, QPushButton, QStackedWidget,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QDialogButtonBox, QMessageBox, QAbstractItemView,
)
from PyQt6.QtCore import pyqtSignal

from src.ui_widgets import CustomSpinBox
from src.config_wizard import _PathField, SUPPLIER_ANDOR, SUPPLIER_PI, DEFAULT_TEMPERATURE


# ── Tab: Hardware / Connection ────────────────────────────────────────────────

class _HardwareTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Camera / spectrometer model:"))
        self._combo_model = QComboBox()
        self._combo_model.addItems([SUPPLIER_ANDOR, SUPPLIER_PI])
        self._combo_model.currentTextChanged.connect(
            lambda text: self._stack.setCurrentIndex(0 if text == SUPPLIER_ANDOR else 1)
        )
        model_row.addWidget(self._combo_model)
        model_row.addStretch()
        layout.addLayout(model_row)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_andor())  # index 0
        self._stack.addWidget(self._build_pi())      # index 1
        layout.addWidget(self._stack)
        layout.addStretch()

    def _build_andor(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        grp = QGroupBox("Andor Shamrock / Kymera")
        gl = QVBoxLayout(grp)
        gl.addWidget(QLabel("Directory containing ShamrockCIF.dll:"))
        self._andor_dll = _PathField(
            placeholder=r"e.g. C:\Program Files\Andor SDK\Shamrock SDK",
            expected_files=["ShamrockCIF.dll"],
            validation_desc="Andor Shamrock DLL",
        )
        gl.addWidget(self._andor_dll)
        v.addWidget(grp)
        return w

    def _build_pi(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        com_grp = QGroupBox("Spectrometer grating controller  (Acton SP — serial)")
        com_h = QHBoxLayout(com_grp)
        com_h.addWidget(QLabel("COM port:"))
        self._pi_com = QComboBox()
        self._pi_com.setEditable(True)
        self._pi_com.setFixedWidth(110)
        self._populate_com_ports()
        com_h.addWidget(self._pi_com)
        com_h.addStretch()
        v.addWidget(com_grp)

        sdk_grp = QGroupBox("Camera (PICam)")
        sdk_v = QVBoxLayout(sdk_grp)
        sdk_v.addWidget(QLabel("PICam Runtime directory  (picam.dll / picam64.dll):"))
        self._pi_picam = _PathField(
            placeholder=r"e.g. C:\Program Files\Princeton Instruments\PICam\Runtime",
            expected_files=["picam.dll", "picam64.dll"],
            validation_desc="PICam Runtime",
        )
        sdk_v.addWidget(self._pi_picam)
        sdk_v.addSpacing(6)
        sdk_v.addWidget(QLabel(
            "Camera serial number  (leave blank to auto-select if only one camera is connected):"
        ))
        self._pi_serial = QLineEdit()
        self._pi_serial.setPlaceholderText("e.g. 0412060001")
        sdk_v.addWidget(self._pi_serial)
        v.addWidget(sdk_grp)
        return w

    def _populate_com_ports(self):
        self._pi_com.clear()
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []
        for p in (ports or [f"COM{i}" for i in range(1, 9)]):
            self._pi_com.addItem(p)

    def load(self, config: dict):
        model = config.get("model", SUPPLIER_ANDOR)
        self._combo_model.setCurrentText(model)
        self._stack.setCurrentIndex(0 if model == SUPPLIER_ANDOR else 1)
        self._andor_dll.set_value(config.get("dll_path", ""))
        self._pi_com.setCurrentText(config.get("com_port", "COM3"))
        self._pi_picam.set_value(config.get("PIcam_dll_path", ""))
        self._pi_serial.setText(config.get("camera_serial_number", ""))

    def collect(self) -> dict:
        model = self._combo_model.currentText()
        result = {"model": model}
        if model == SUPPLIER_ANDOR:
            result["dll_path"] = self._andor_dll.value()
        else:
            result["com_port"] = self._pi_com.currentText().strip()
            result["PIcam_dll_path"] = self._pi_picam.value()
            result["camera_serial_number"] = self._pi_serial.text().strip()
        return result

    def validation_warning(self) -> str | None:
        """Non-blocking: the active model's path field, if invalid."""
        field = self._andor_dll if self._combo_model.currentText() == SUPPLIER_ANDOR else self._pi_picam
        return field.validation_error()


# ── Tab: Grating ───────────────────────────────────────────────────────────────

class _GratingTab(QWidget):
    _COLUMNS = ("Index", "Grooves (/mm)", "ROI from", "ROI to")

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "One row per grating slot. Index is the physical turret slot number sent to the\n"
            "spectrometer — it does not have to match the row's position in this table.\n"
            "ROI from/to are the default vertical-binning rows applied when this grating is selected."
        ))

        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add slot")
        btn_remove = QPushButton("Remove selected slot")
        btn_add.clicked.connect(lambda: self._add_row())
        btn_remove.clicked.connect(self._remove_selected_row)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _add_row(self, index=None, grooves=600, roi_from=100, roi_to=140):
        row = self._table.rowCount()
        if index is None:
            index = row + 1
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(str(index)))
        self._table.setItem(row, 1, QTableWidgetItem(str(grooves)))
        self._table.setItem(row, 2, QTableWidgetItem(str(roi_from)))
        self._table.setItem(row, 3, QTableWidgetItem(str(roi_to)))

    def _remove_selected_row(self):
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def load(self, config: dict):
        self._table.setRowCount(0)
        for i, g in enumerate(config.get("grating", [])):
            roi = g.get("defaultROI", {})
            self._add_row(g.get("index", i + 1), g.get("grooves", 600), roi.get("from", 100), roi.get("to", 140))

    def validation_errors(self) -> list[str]:
        errors = []
        if self._table.rowCount() == 0:
            errors.append("At least one grating slot is required.")
        seen_indices = set()
        for row in range(self._table.rowCount()):
            try:
                index = int(self._table.item(row, 0).text())
                grooves = int(self._table.item(row, 1).text())
                roi_from = int(self._table.item(row, 2).text())
                roi_to = int(self._table.item(row, 3).text())
            except (ValueError, AttributeError):
                errors.append(f"Row {row + 1}: index/grooves/ROI must be integers.")
                continue
            if index <= 0:
                errors.append(f"Row {row + 1}: index must be positive.")
            elif index in seen_indices:
                errors.append(f"Row {row + 1}: index {index} is used by more than one row.")
            else:
                seen_indices.add(index)
            if grooves <= 0:
                errors.append(f"Row {row + 1}: grooves must be positive.")
            if roi_from >= roi_to:
                errors.append(f"Row {row + 1}: ROI 'from' must be less than 'to'.")
        return errors

    def collect(self) -> list[dict]:
        result = []
        for row in range(self._table.rowCount()):
            result.append({
                "index": int(self._table.item(row, 0).text()),
                "grooves": int(self._table.item(row, 1).text()),
                "defaultROI": {
                    "from": int(self._table.item(row, 2).text()),
                    "to": int(self._table.item(row, 3).text()),
                },
            })
        return result


# ── Tab: Display / Defaults ───────────────────────────────────────────────────

class _DisplayTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._flip_x = QCheckBox("Flip spectrum horizontally  (flip_x)")
        layout.addWidget(self._flip_x)
        layout.addSpacing(8)

        layout.addWidget(QLabel("Default cooler target temperature (°C):"))
        self._default_temp = CustomSpinBox()
        self._default_temp.setRange(-100, 20)
        layout.addWidget(self._default_temp)
        layout.addStretch()

    def load(self, config: dict):
        self._flip_x.setChecked(config.get("flip_x", False))
        self._default_temp.setValue(config.get("default_temperature", DEFAULT_TEMPERATURE))

    def collect(self) -> dict:
        return {
            "flip_x": self._flip_x.isChecked(),
            "default_temperature": self._default_temp.value(),
        }


# ── Main dialog ────────────────────────────────────────────────────────────────

class HardwareConfigDialog(QDialog):
    """Edits a copy of spectrometerConfig.json; writes nothing until Apply/OK.

    applied(new_config, changed_tabs): emitted on a successful Apply/OK, where
    changed_tabs is a subset of {"hardware", "grating", "display"} — whichever
    tabs actually had a key change relative to the last-applied state.
    """

    HARDWARE_KEYS = ("model", "com_port", "dll_path", "PIcam_dll_path", "camera_serial_number")

    applied = pyqtSignal(dict, set)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hardware Configuration")
        self.resize(520, 440)

        self._base_config = copy.deepcopy(config)

        self._tab_hardware = _HardwareTab()
        self._tab_grating = _GratingTab()
        self._tab_display = _DisplayTab()
        for tab in (self._tab_hardware, self._tab_grating, self._tab_display):
            tab.load(self._base_config)

        tabs = QTabWidget()
        tabs.addTab(self._tab_hardware, "Hardware / Connection")
        tabs.addTab(self._tab_grating, "Grating")
        tabs.addTab(self._tab_display, "Display / Defaults")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _collect_and_validate(self) -> dict | None:
        grating_errors = self._tab_grating.validation_errors()
        if grating_errors:
            QMessageBox.warning(self, "Invalid input", "\n".join(grating_errors))
            return None

        hw_warning = self._tab_hardware.validation_warning()
        if hw_warning:
            reply = QMessageBox.warning(
                self, "Path verification failed",
                f"{hw_warning}\n\n"
                "Save anyway? (the app will fall back to debug mode for unresolved\n"
                "hardware the next time it starts).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return None

        new_config = copy.deepcopy(self._base_config)
        new_config.update(self._tab_hardware.collect())
        new_config["grating"] = self._tab_grating.collect()
        new_config.update(self._tab_display.collect())
        return new_config

    def _diff_changed_tabs(self, new_config: dict) -> set:
        changed = set()
        if any(self._base_config.get(k) != new_config.get(k) for k in self.HARDWARE_KEYS):
            changed.add("hardware")
        if self._base_config.get("grating") != new_config.get("grating"):
            changed.add("grating")
        if (self._base_config.get("flip_x") != new_config.get("flip_x")
                or self._base_config.get("default_temperature") != new_config.get("default_temperature")):
            changed.add("display")
        return changed

    def _apply(self) -> bool:
        new_config = self._collect_and_validate()
        if new_config is None:
            return False
        changed = self._diff_changed_tabs(new_config)
        self._base_config = new_config
        if changed:
            self.applied.emit(new_config, changed)
        return True

    def _on_ok(self):
        if self._apply():
            self.accept()
