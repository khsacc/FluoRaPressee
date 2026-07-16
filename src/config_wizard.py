"""
Configuration wizard shown when spectrometerConfig.json is missing.

Pages:
  0 — Supplier selection
  1 — Supplier-specific paths / connection settings
  2 — Grating configuration

Future note (breaking change): Princeton Instruments will be split into
  "PrincetonInstruments_USB"  — current behaviour (PVCAM/PICam over USB)
  "PrincetonInstruments_GigE" — GigE transport, requires additional config keys
When that split happens, rename model="PrincetonInstruments" accordingly and
add the GigE-specific keys to the wizard's _PagePaths._build_pi_gige().
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QFileDialog, QGroupBox,
    QRadioButton, QButtonGroup, QStackedWidget, QWidget,
    QMessageBox, QSizePolicy, QLineEdit,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from src.ui_widgets import CustomSpinBox

# Default cooler target temperature (°C) pre-filled in the wizard and used as the
# fallback in spectrometerConfig.json / SpectrometerGUI when the key is absent.
DEFAULT_TEMPERATURE = -65

# ── Supplier model strings ────────────────────────────────────────────────────
SUPPLIER_ANDOR = "Andor"
SUPPLIER_PI    = "PrincetonInstruments"
# Future: SUPPLIER_PI_USB  = "PrincetonInstruments_USB"
#         SUPPLIER_PI_GIGE = "PrincetonInstruments_GigE"

# ── Path search specs ─────────────────────────────────────────────────────────
# {config_key: (filename | None, [candidate_root_dirs])}
# filename=None  → the directory itself is the result (existence check only)
_SEARCH_SPECS: dict[str, tuple[Optional[str], list[str]]] = {
    "dll_path": (
        "ShamrockCIF.dll",
        [
            r"C:\Program Files\Andor SDK",
            r"C:\Program Files (x86)\Andor SDK",
            r"C:\Program Files\Andor SOLIS",
            r"C:\Program Files\Andor",
            r"C:\Windows\System32",
            r"C:\Windows\SysWOW64",
        ],
    ),
    "PIcam_dll_path": (
        None,
        [
            r"C:\Program Files\Princeton Instruments\PICam\Runtime",
            r"C:\Program Files (x86)\Princeton Instruments\PICam\Runtime",
            r"C:\Program Files\Princeton Instruments\PICam",
            r"C:\Program Files\Princeton Instruments",
        ],
    ),
}

_FALLBACK_DEFAULTS = {
    "dll_path":       "",
    "PIcam_dll_path": r"C:\Program Files\Princeton Instruments\PICam\Runtime",
}


# ── Background path search ────────────────────────────────────────────────────

class _PathSearchThread(QThread):
    """Searches common install locations for each config key; emits results one at a time."""
    found = pyqtSignal(str, list)   # (config_key, [directory_paths])

    def run(self):
        for key, (filename, roots) in _SEARCH_SPECS.items():
            results: list[str] = []
            for root in roots:
                if not os.path.isdir(root):
                    continue
                if filename is None:
                    results.append(root)
                    continue
                if os.path.isfile(os.path.join(root, filename)) and root not in results:
                    results.append(root)
                try:
                    for dirpath, dirnames, files in os.walk(root):
                        rel = os.path.relpath(dirpath, root)
                        depth = 0 if rel == "." else rel.count(os.sep) + 1
                        if depth >= 4:
                            dirnames.clear()
                            continue
                        if filename in files and dirpath not in results:
                            results.append(dirpath)
                except PermissionError:
                    pass
            self.found.emit(key, results)


# ── Reusable path-picker widget (with inline validation indicator) ─────────────

class _PathField(QWidget):
    """
    Editable combo (for suggestions) + Browse button + ✓/✗ status indicator.

    expected_files: list of filenames to look for inside the chosen directory.
                    If empty/None, only directory existence is checked.
    validation_desc: human-readable description used in error messages.
    """

    _SEARCHING = "(searching…)"

    def __init__(
        self,
        placeholder: str = "",
        expected_files: Optional[list[str]] = None,
        validation_desc: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._key = ""
        self._expected_files: list[str] = expected_files or []
        self._validation_desc = validation_desc

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setInsertPolicy(QComboBox.NoInsert)
        self._combo.lineEdit().setPlaceholderText(placeholder)
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        btn = QPushButton("Browse…")
        btn.setFixedWidth(80)
        btn.clicked.connect(self._browse)

        self._status = QLabel("–")
        self._status.setFixedWidth(20)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color: gray; font-weight: bold;")

        layout.addWidget(self._combo)
        layout.addWidget(btn)
        layout.addWidget(self._status)

        self._combo.currentTextChanged.connect(self._update_status)

    # ── search integration ────────────────────────────────────────────────────

    def begin_search(self):
        if self._combo.findText(self._SEARCHING) < 0:
            self._combo.insertItem(0, self._SEARCHING)
        self._combo.setCurrentText(self._SEARCHING)
        self._status.setText("…")
        self._status.setStyleSheet("color: gray;")

    def apply_results(self, paths: list[str]):
        saved = self._combo.currentText()
        if saved == self._SEARCHING:
            saved = ""
        idx = self._combo.findText(self._SEARCHING)
        if idx >= 0:
            self._combo.removeItem(idx)
        for p in paths:
            if self._combo.findText(p) < 0:
                self._combo.addItem(p)
        if saved:
            self._combo.setCurrentText(saved)
        elif paths:
            self._combo.setCurrentText(paths[0])
        elif _FALLBACK_DEFAULTS.get(self._key, ""):
            self._combo.setCurrentText(_FALLBACK_DEFAULTS[self._key])
        # setCurrentText triggers currentTextChanged → _update_status

    # ── key / value ──────────────────────────────────────────────────────────

    def set_key(self, key: str):
        self._key = key

    def set_value(self, text: str):
        """Pre-fill with a known value (e.g. when editing an existing config), bypassing search."""
        if text and self._combo.findText(text) < 0:
            self._combo.insertItem(0, text)
        self._combo.setCurrentText(text)

    def value(self) -> str:
        return self._combo.currentText().strip()

    # ── validation ───────────────────────────────────────────────────────────

    def is_valid(self) -> bool:
        path = self.value()
        if not path or path == self._SEARCHING:
            return False
        if not os.path.isdir(path):
            return False
        if not self._expected_files:
            return True
        return any(os.path.isfile(os.path.join(path, f)) for f in self._expected_files)

    def _update_status(self, text: str):
        if not text or text == self._SEARCHING:
            self._status.setText("–")
            self._status.setStyleSheet("color: gray; font-weight: bold;")
            return
        if self.is_valid():
            self._status.setText("✓")
            self._status.setStyleSheet("color: green; font-weight: bold;")
        else:
            self._status.setText("✗")
            self._status.setStyleSheet("color: red; font-weight: bold;")

    def validation_error(self) -> Optional[str]:
        """Return a human-readable error string if invalid, else None."""
        if self.is_valid():
            return None
        path = self.value() or "(empty)"
        if self._expected_files:
            files = " / ".join(self._expected_files)
            return f"{self._validation_desc}: {files} not found in\n  {path}"
        return f"{self._validation_desc}: directory not found:\n  {path}"

    # ── browse ────────────────────────────────────────────────────────────────

    def _browse(self):
        start = self.value() or "C:\\"
        path = QFileDialog.getExistingDirectory(self, "Select directory", start)
        if path:
            norm = os.path.normpath(path)
            if self._combo.findText(norm) < 0:
                self._combo.insertItem(0, norm)
            self._combo.setCurrentText(norm)


# ── Page 0: Supplier selection ────────────────────────────────────────────────

class _PageSupplier(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Step 1 / 3 — Select spectrometer supplier</b>"))
        layout.addSpacing(16)

        self._grp = QButtonGroup(self)
        self._rb_andor = QRadioButton("Andor  (Kymera / Shamrock)")
        self._rb_pi    = QRadioButton("Princeton Instruments  (Acton SP series)")
        self._rb_andor.setChecked(True)
        for rb in (self._rb_andor, self._rb_pi):
            self._grp.addButton(rb)
            layout.addWidget(rb)

        layout.addStretch()

    def supplier(self) -> str:
        return SUPPLIER_ANDOR if self._rb_andor.isChecked() else SUPPLIER_PI


# ── Page 1: Paths / connection ────────────────────────────────────────────────

class _PagePaths(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("<b>Step 2 / 3 — Connection &amp; path settings</b>"))
        root.addSpacing(4)
        root.addWidget(QLabel(
            '<span style="color: gray; font-size: small;">'
            "✓ = file found   ✗ = not found   – = not yet checked"
            "</span>"
        ))
        root.addSpacing(6)

        self._stack = QStackedWidget()
        self._andor_panel = self._build_andor()
        self._pi_panel    = self._build_pi()
        self._stack.addWidget(self._andor_panel)   # index 0
        self._stack.addWidget(self._pi_panel)      # index 1
        root.addWidget(self._stack)
        root.addStretch()

        # path fields indexed by config key
        self._fields: dict[str, _PathField] = {
            "dll_path":       self._andor_dll,
            "PIcam_dll_path": self._pi_picam,
        }
        for key, field in self._fields.items():
            field.set_key(key)

        self._search_thread: Optional[_PathSearchThread] = None

    # ── sub-panels ───────────────────────────────────────────────────────────

    def _build_andor(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        grp = QGroupBox("Andor Shamrock / Kymera")
        gl = QVBoxLayout(grp)
        gl.addWidget(QLabel("Directory containing ShamrockCIF.dll:"))
        self._andor_dll = _PathField(
            placeholder="e.g. C:\\Program Files\\Andor SDK\\Shamrock SDK",
            expected_files=["ShamrockCIF.dll"],
            validation_desc="Andor Shamrock DLL",
        )
        gl.addWidget(self._andor_dll)
        vbox.addWidget(grp)
        return w

    def _build_pi(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)

        # Serial port for the Acton spectrometer grating controller
        com_grp = QGroupBox("Spectrometer grating controller  (Acton SP — serial)")
        com_h = QHBoxLayout(com_grp)
        com_h.addWidget(QLabel("COM port:"))
        self._pi_com = QComboBox()
        self._pi_com.setEditable(True)
        self._pi_com.setFixedWidth(110)
        self._populate_com_ports()
        com_h.addWidget(self._pi_com)
        com_h.addStretch()
        vbox.addWidget(com_grp)

        # Camera SDK path + camera selection
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
        vbox.addWidget(sdk_grp)
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
        if self._pi_com.findText("COM3") >= 0:
            self._pi_com.setCurrentText("COM3")

    # ── search ───────────────────────────────────────────────────────────────

    def start_search(self):
        """Launch background path search for all fields (Andor + PI)."""
        if self._search_thread and self._search_thread.isRunning():
            return
        for field in self._fields.values():
            field.begin_search()
        self._search_thread = _PathSearchThread()
        self._search_thread.found.connect(self._on_found)
        self._search_thread.start()

    def _on_found(self, key: str, paths: list[str]):
        if key in self._fields:
            self._fields[key].apply_results(paths)

    # ── supplier switch ───────────────────────────────────────────────────────

    def show_supplier(self, supplier: str):
        self._stack.setCurrentIndex(0 if supplier == SUPPLIER_ANDOR else 1)

    # ── validation ───────────────────────────────────────────────────────────

    def get_validation_errors(self, supplier: str) -> list[str]:
        """Return list of human-readable error strings for the active supplier's fields."""
        if supplier == SUPPLIER_ANDOR:
            fields = [self._andor_dll]
        else:
            # When GigE is added, branch here on supplier == SUPPLIER_PI_GIGE
            # and check additional GigE-specific fields.
            fields = [self._pi_picam]
        return [e for f in fields if (e := f.validation_error()) is not None]

    # ── result collection ─────────────────────────────────────────────────────

    def values(self, supplier: str) -> dict:
        if supplier == SUPPLIER_ANDOR:
            return {"dll_path": self._andor_dll.value()}
        return {
            "com_port":            self._pi_com.currentText().strip(),
            "PIcam_dll_path":      self._pi_picam.value(),
            "camera_serial_number": self._pi_serial.text().strip(),
        }


# ── Page 2: Grating configuration ────────────────────────────────────────────

class _PageGrating(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Step 3 / 3 — Grating &amp; detector configuration</b>"))
        layout.addSpacing(8)

        layout.addWidget(QLabel(
            "Enter grating grooves/mm in slot order, separated by commas\n"
            "  e.g.  600, 1200, 1800"
        ))
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("600, 1200, 1800")
        layout.addWidget(self._edit)
        layout.addSpacing(12)

        self._flip_x = QCheckBox("Flip spectrum horizontally  (flip_x)")
        layout.addWidget(self._flip_x)
        layout.addSpacing(12)

        layout.addWidget(QLabel("Default cooler target temperature (°C):"))
        self._default_temp = CustomSpinBox()
        self._default_temp.setRange(-100, 20)
        self._default_temp.setValue(DEFAULT_TEMPERATURE)
        layout.addWidget(self._default_temp)
        layout.addStretch()

    def grating_list(self) -> list[dict]:
        result = []
        for i, token in enumerate(self._edit.text().split(","), start=1):
            token = token.strip()
            try:
                result.append({
                    "index": i,
                    "grooves": int(token),
                    "defaultROI": {"from": 100, "to": 140},
                })
            except ValueError:
                pass
        return result

    def flip_x(self) -> bool:
        return self._flip_x.isChecked()

    def default_temperature(self) -> int:
        return self._default_temp.value()


# ── Main wizard dialog ────────────────────────────────────────────────────────

class ConfigWizard(QDialog):
    """3-step wizard that collects enough information to write spectrometerConfig.json."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spectrometer Setup Wizard")
        self.setMinimumWidth(540)
        self.resize(580, 400)

        self._p_supplier = _PageSupplier()
        self._p_paths    = _PagePaths()
        self._p_grating  = _PageGrating()
        self._search_started = False

        self._stack = QStackedWidget()
        for page in (self._p_supplier, self._p_paths, self._p_grating):
            self._stack.addWidget(page)

        self._btn_back   = QPushButton("< Back")
        self._btn_next   = QPushButton("Next >")
        self._btn_cancel = QPushButton("Cancel")
        self._btn_back.clicked.connect(self._go_back)
        self._btn_next.clicked.connect(self._go_next)
        self._btn_cancel.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_back)
        btn_row.addWidget(self._btn_next)

        main = QVBoxLayout(self)
        main.addWidget(self._stack)
        main.addLayout(btn_row)

        self._refresh_buttons()
        self._result: Optional[dict] = None

    # ── navigation ───────────────────────────────────────────────────────────

    def _go_next(self):
        page = self._stack.currentIndex()
        if page == 0:
            supplier = self._p_supplier.supplier()
            self._p_paths.show_supplier(supplier)
            if not self._search_started:
                self._p_paths.start_search()
                self._search_started = True
            self._stack.setCurrentIndex(1)

        elif page == 1:
            supplier = self._p_supplier.supplier()
            errors = self._p_paths.get_validation_errors(supplier)
            if errors:
                detail = "\n\n".join(errors)
                reply = QMessageBox.warning(
                    self,
                    "Path verification failed",
                    f"The following paths could not be verified:\n\n{detail}\n\n"
                    "You can go back and correct them, or proceed anyway\n"
                    "(the app will fall back to debug mode for unresolved hardware).\n\n"
                    "Proceed to the next step?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return
            self._stack.setCurrentIndex(2)

        elif page == 2:
            self._finish()
            return

        self._refresh_buttons()

    def _go_back(self):
        page = self._stack.currentIndex()
        if page > 0:
            self._stack.setCurrentIndex(page - 1)
        self._refresh_buttons()

    def _refresh_buttons(self):
        page = self._stack.currentIndex()
        self._btn_back.setEnabled(page > 0)
        self._btn_next.setText("Finish" if page == 2 else "Next >")

    # ── finish ───────────────────────────────────────────────────────────────

    def _finish(self):
        supplier = self._p_supplier.supplier()
        gratings = self._p_grating.grating_list()
        if not gratings:
            QMessageBox.warning(self, "Input required",
                                "Please enter at least one grating (grooves/mm).")
            return
        self._result = {
            "model": supplier,
            **self._p_paths.values(supplier),
            "grating": gratings,
            "flip_x": self._p_grating.flip_x(),
            "default_temperature": self._p_grating.default_temperature(),
        }
        self.accept()

    def result_config(self) -> Optional[dict]:
        return self._result
