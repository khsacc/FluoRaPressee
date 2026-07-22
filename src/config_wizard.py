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

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QCheckBox, QFileDialog, QGroupBox,
    QRadioButton, QButtonGroup, QStackedWidget, QWidget,
    QMessageBox, QSizePolicy, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.ui_widgets import CustomSpinBox

# Default cooler target temperature (°C) pre-filled in the wizard and used as the
# fallback in spectrometerConfig.json / SpectrometerGUI when the key is absent.
DEFAULT_TEMPERATURE = -65
# Default cooling fan mode (Andor SDK2 only) pre-filled in the wizard and used as the
# fallback in spectrometerConfig.json / camera_andor.py when the key is absent.
DEFAULT_FAN_MODE = "full"

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


# ── Background grating auto-detect (Princeton Instruments only) ───────────────

class _GratingDetectThread(QThread):
    """Best-effort ``?GRATINGS`` query against a Princeton Instruments spectrometer,
    used to pre-fill the grating page instead of requiring manual entry.

    Any failure (pyserial not installed, no device on the port, unparseable
    response) yields an empty list rather than raising -- manual entry remains
    the fallback, exactly as before this existed.
    """
    detected = pyqtSignal(list)  # [{"index": int, "grooves": int}, ...]

    def __init__(self, com_port):
        super().__init__()
        self.com_port = com_port

    def run(self):
        gratings = []
        try:
            from src.spectrometer_princeton import SpectrometerControllerPI
            ctrl = SpectrometerControllerPI(config={"com_port": self.com_port}, debug=False)
            if ctrl.initialize():
                gratings = ctrl.get_gratings()
            ctrl.close()
        except Exception as e:
            print(f"Grating auto-detect failed: {e}")
        self.detected.emit(gratings)


class _HardwareProbeThread(QThread):
    """Run the first-connection hardware inventory without blocking the dialog."""
    detected = pyqtSignal(dict)

    def __init__(self, supplier, config):
        super().__init__()
        self.supplier = supplier
        self.config = dict(config)

    def run(self):
        from src.hardware_probe import probe_initial_hardware

        try:
            result = probe_initial_hardware(self.supplier, self.config)
        except Exception as exc:
            result = {
                "supplier": self.supplier,
                "config": {},
                "detected_hardware": {},
                "camera_candidates": [],
                "successes": [],
                "errors": [f"Hardware probe failed: {exc}"],
            }
        self.detected.emit(result)


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
        self._combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._combo.lineEdit().setPlaceholderText(placeholder)
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        btn = QPushButton("Browse…")
        btn.setFixedWidth(80)
        btn.clicked.connect(self._browse)

        self._status = QLabel("–")
        self._status.setFixedWidth(20)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
    probe_requested = pyqtSignal()

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

        self._probe_button = QPushButton("Read parameters from connected hardware")
        self._probe_button.clicked.connect(self.probe_requested.emit)
        root.addWidget(self._probe_button)
        self._probe_status = QLabel("")
        self._probe_status.setWordWrap(True)
        self._probe_status.setStyleSheet("color: gray; font-size: small;")
        root.addWidget(self._probe_status)
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
        self._pi_serial = QComboBox()
        self._pi_serial.setEditable(True)
        self._pi_serial.lineEdit().setPlaceholderText("e.g. 0412060001")
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
        self._probe_button.setEnabled(False)
        self._probe_status.setText("Searching for installed SDK files...")
        for field in self._fields.values():
            field.begin_search()
        self._search_thread = _PathSearchThread()
        self._search_thread.found.connect(self._on_found)
        self._search_thread.finished.connect(self._on_search_finished)
        self._search_thread.start()

    def _on_found(self, key: str, paths: list[str]):
        if key in self._fields:
            self._fields[key].apply_results(paths)

    def _on_search_finished(self):
        self._probe_button.setEnabled(True)
        if self._probe_status.text() == "Searching for installed SDK files...":
            self._probe_status.clear()

    # ── supplier switch ───────────────────────────────────────────────────────

    def show_supplier(self, supplier: str):
        self._stack.setCurrentIndex(0 if supplier == SUPPLIER_ANDOR else 1)
        self._probe_status.clear()

    def set_probe_busy(self, busy: bool):
        self._probe_button.setEnabled(not busy)
        self._probe_button.setText(
            "Reading connected hardware..."
            if busy else "Read parameters from connected hardware"
        )
        if busy:
            self._probe_status.setText("Connecting to the camera and spectrograph...")
            self._probe_status.setStyleSheet("color: gray; font-size: small;")

    def show_probe_result(self, result: dict):
        successes = result.get("successes", [])
        errors = result.get("errors", [])
        if successes and not errors:
            text = "Read successfully: " + ", ".join(successes)
            color = "green"
        elif successes:
            text = "Read partially: " + ", ".join(successes)
            if errors:
                text += f". {errors[0]}"
            color = "#9a6700"
        else:
            text = "No hardware parameters could be read."
            if errors:
                text += f" {errors[0]}"
            color = "#b42318"
        self._probe_status.setText(text)
        self._probe_status.setToolTip("\n".join(errors))
        self._probe_status.setStyleSheet(f"color: {color}; font-size: small;")

    def apply_probe_result(self, result: dict):
        candidates = result.get("camera_candidates", [])
        selected_serial = result.get("config", {}).get("camera_serial_number")
        current = selected_serial or self._pi_serial.currentText().strip()
        for candidate in candidates:
            serial = str(candidate.get("serial_number") or "")
            label = f"{serial} ({candidate.get('model')})" if serial else ""
            if serial and self._pi_serial.findData(serial) < 0:
                self._pi_serial.addItem(label, serial)
        if current:
            index = self._pi_serial.findData(current)
            if index >= 0:
                self._pi_serial.setCurrentIndex(index)
            else:
                self._pi_serial.setEditText(current)

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
            "camera_serial_number": (
                str(self._pi_serial.currentData())
                if self._pi_serial.currentData() is not None
                else self._pi_serial.currentText().strip()
            ),
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

        self._detect_status = QLabel("")
        self._detect_status.setStyleSheet("color: gray; font-size: small;")
        layout.addWidget(self._detect_status)
        layout.addSpacing(12)

        self._detect_thread = None
        self._detect_started = False
        self._detected_gratings = []

        self._flip_x = QCheckBox("Flip spectrum horizontally  (flip_x)")
        layout.addWidget(self._flip_x)
        layout.addSpacing(12)

        layout.addWidget(QLabel("Default cooler target temperature (°C):"))
        self._default_temp = CustomSpinBox()
        self._default_temp.setRange(-100, 20)
        self._default_temp.setValue(DEFAULT_TEMPERATURE)
        layout.addWidget(self._default_temp)
        layout.addSpacing(12)

        # Fan mode is an Andor SDK2 concept (set_fan_mode/get_fan_mode); hidden for
        # Princeton Instruments via show_supplier().
        self._fan_mode_label = QLabel("Default cooling fan mode:")
        self._fan_mode = QComboBox()
        self._fan_mode.addItems(["full", "low", "off"])
        self._fan_mode.setCurrentText(DEFAULT_FAN_MODE)
        layout.addWidget(self._fan_mode_label)
        layout.addWidget(self._fan_mode)
        layout.addStretch()

    def show_supplier(self, supplier: str):
        is_andor = supplier == SUPPLIER_ANDOR
        self._fan_mode_label.setVisible(is_andor)
        self._fan_mode.setVisible(is_andor)

    def start_detection(self, com_port: str):
        """Try ?GRATINGS against com_port once and pre-fill the field on success.

        Never overwrites text the user already typed, and silently falls back to
        manual entry (leaving the field as-is) on any failure.
        """
        if self._detect_started or not com_port:
            return
        self._detect_started = True
        self._detect_status.setText("Detecting installed gratings from spectrometer...")
        self._detect_status.setStyleSheet("color: gray; font-size: small;")
        self._detect_thread = _GratingDetectThread(com_port)
        self._detect_thread.detected.connect(self._on_detected)
        self._detect_thread.start()

    def _on_detected(self, gratings: list[dict]):
        if gratings:
            if not self._edit.text().strip():
                self._edit.setText(", ".join(str(g["grooves"]) for g in gratings))
            self._detect_status.setText(
                f"Auto-detected {len(gratings)} grating(s) from the spectrometer "
                "(edit above if needed)."
            )
            self._detect_status.setStyleSheet("color: green; font-size: small;")
        else:
            self._detect_status.setText(
                "Could not auto-detect gratings (no response / not connected) -- "
                "please enter them manually."
            )
            self._detect_status.setStyleSheet("color: gray; font-size: small;")

    def apply_probe_result(self, config: dict):
        gratings = config.get("grating") or []
        if gratings:
            self._detected_gratings = [dict(grating) for grating in gratings]
            self._edit.setText(", ".join(str(g["grooves"]) for g in gratings))
            self._detect_started = True
            self._detect_status.setText(
                f"Read {len(gratings)} installed grating(s) from the connected hardware."
            )
            self._detect_status.setStyleSheet("color: green; font-size: small;")
        if config.get("default_temperature") is not None:
            self._default_temp.setValue(int(config["default_temperature"]))
        if config.get("default_fan_mode") in ("full", "low", "off"):
            self._fan_mode.setCurrentText(config["default_fan_mode"])

    def reset_detected_parameters(self):
        self._detected_gratings = []
        self._detect_started = False
        self._edit.clear()
        self._detect_status.clear()
        self._default_temp.setValue(DEFAULT_TEMPERATURE)
        self._fan_mode.setCurrentText(DEFAULT_FAN_MODE)

    def grating_list(self) -> list[dict]:
        result = []
        for i, token in enumerate(self._edit.text().split(","), start=1):
            token = token.strip()
            try:
                grooves = int(token)
                detected = next(
                    (
                        dict(grating)
                        for grating in self._detected_gratings
                        if grating.get("index") == i and grating.get("grooves") == grooves
                    ),
                    {},
                )
                detected.update({
                    "index": i,
                    "grooves": grooves,
                })
                detected.setdefault("defaultROI", {"from": 100, "to": 140})
                result.append(detected)
            except ValueError:
                pass
        return result

    def flip_x(self) -> bool:
        return self._flip_x.isChecked()

    def default_temperature(self) -> int:
        return self._default_temp.value()

    def fan_mode(self) -> str:
        return self._fan_mode.currentText()


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
        self._probe_thread = None
        self._detected_config = {}
        self._detected_supplier = None
        self._shown_supplier = None
        self._p_paths.probe_requested.connect(self._probe_hardware)

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
            if self._shown_supplier is not None and supplier != self._shown_supplier:
                self._p_grating.reset_detected_parameters()
            self._shown_supplier = supplier
            self._p_paths.show_supplier(supplier)
            self._p_grating.show_supplier(supplier)
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
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.No:
                    return
            if supplier == SUPPLIER_PI:
                com_port = self._p_paths.values(SUPPLIER_PI).get("com_port", "")
                self._p_grating.start_detection(com_port)
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
        self._btn_next.setEnabled(True)
        self._btn_next.setText("Finish" if page == 2 else "Next >")

    def _probe_hardware(self):
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return
        supplier = self._p_supplier.supplier()
        if self._detected_supplier != supplier:
            self._detected_config = {}
        self._detected_supplier = supplier
        config = {"model": supplier, **self._p_paths.values(supplier)}
        self._p_paths.set_probe_busy(True)
        self._btn_back.setEnabled(False)
        self._btn_next.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._probe_thread = _HardwareProbeThread(supplier, config)
        self._probe_thread.detected.connect(self._on_hardware_probed)
        self._probe_thread.start()

    def _on_hardware_probed(self, result: dict):
        self._p_paths.set_probe_busy(False)
        self._btn_cancel.setEnabled(True)
        self._refresh_buttons()
        self._p_paths.apply_probe_result(result)
        self._p_paths.show_probe_result(result)
        patch = result.get("config", {})
        _merge_dict(self._detected_config, patch)
        self._p_grating.apply_probe_result(patch)

    def closeEvent(self, event):
        if self._probe_thread is not None and self._probe_thread.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return
        super().reject()

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
            "hardware_identity": {
                "spectrometer": {"model": None, "serial_number": None},
                "camera": {"model": None, "serial_number": None},
            },
        }
        if self._detected_supplier == supplier:
            _merge_dict(
                self._result["hardware_identity"],
                self._detected_config.get("hardware_identity", {}),
            )
        if supplier == SUPPLIER_ANDOR:
            self._result["default_fan_mode"] = self._p_grating.fan_mode()
        self.accept()

    def result_config(self) -> Optional[dict]:
        return self._result


def _merge_dict(target: dict, source: dict) -> dict:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[key] = value
    return target
