"""AnalysisWindow: load previously-saved spectra and re-run fitting / pressure
calculation on them, with no spectrometer/camera connection required.

Usable both as a standalone top-level window (see analysis_main.py) and as an
independent sub-window opened from the live SpectrometerGUI (src/ui.py). It shares
only backend classes with the live GUI (DataAnalyzer, PressureCalculator, DataFileIO,
PressureCalculatorWindow) -- its Qt widgets are built fresh here so the live
acquisition GUI code is untouched.

The x-axis column saved by DataFileIO.save_spectrum_1d is already fully resolved
(nm / cm-1 / pixel) at save time, so loading a file here never needs calibration,
grating, or ROI state -- just plot the columns and feed them to DataAnalyzer.
"""

import os

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QFileSystemWatcher
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QRadioButton, QButtonGroup,
    QTextEdit, QFileDialog, QMessageBox,
)

from src.analysis import DataAnalyzer
from src.file_io import DataFileIO
from src.pressureCalc_ui import PressureCalculatorWindow
from src.ui_widgets import CustomDoubleSpinBox, CustomComboBox
from src.local_cache import load_local_cache, save_local_cache

_LAST_DIR_CACHE_KEY = "last_analysis_dir"


class AnalysisWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FluoraPressée: Analysis Mode")
        self.resize(1400, 900)

        self.analyzer = DataAnalyzer()
        self.file_io = DataFileIO()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.refresh_file_list)

        self.current_dir = ""
        self.current_file_path = None
        self.current_x = None
        self.current_y_sub = None
        self.current_y_raw = None
        self.current_y_bg = None
        self.current_metadata = None
        self.current_unit = None
        self.latest_fit_res = None
        self.latest_fit_func = None
        self.pressure_window = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        layout.addWidget(self._build_left_panel(), stretch=1)
        layout.addWidget(self._build_center_panel(), stretch=3)
        layout.addWidget(self._build_right_panel(), stretch=1)

        cache = load_local_cache()
        last_dir = cache.get(_LAST_DIR_CACHE_KEY, "")
        if last_dir and os.path.isdir(last_dir):
            self._set_watched_directory(last_dir)

    # ---- left: file browser -------------------------------------------------
    def _build_left_panel(self):
        panel = QGroupBox("Load Data")
        layout = QVBoxLayout()

        self.btn_choose_dir = QPushButton("Choose folder…")
        self.btn_choose_dir.clicked.connect(self.on_choose_dir_clicked)
        layout.addWidget(self.btn_choose_dir)

        self.lbl_watched_dir = QLabel("Watching: (none)")
        self.lbl_watched_dir.setWordWrap(True)
        self.lbl_watched_dir.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.lbl_watched_dir)

        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        layout.addWidget(self.file_list, stretch=1)

        self.btn_open_file = QPushButton("Open file…")
        self.btn_open_file.clicked.connect(self.on_open_file_clicked)
        layout.addWidget(self.btn_open_file)

        panel.setLayout(layout)
        return panel

    def on_choose_dir_clicked(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose folder to watch", self.current_dir)
        if directory:
            self._set_watched_directory(directory)

    def _set_watched_directory(self, directory):
        if self.current_dir and self.current_dir in self.watcher.directories():
            self.watcher.removePath(self.current_dir)
        self.current_dir = directory
        self.watcher.addPath(directory)
        display_path = directory if len(directory) < 40 else "…" + directory[-37:]
        self.lbl_watched_dir.setText(f"Watching: {display_path}")
        save_local_cache(_LAST_DIR_CACHE_KEY, directory)
        self.refresh_file_list()

    def refresh_file_list(self):
        self.file_list.blockSignals(True)
        self.file_list.clear()
        if self.current_dir and os.path.isdir(self.current_dir):
            entries = []
            for name in os.listdir(self.current_dir):
                if not name.lower().endswith(".txt"):
                    continue
                full_path = os.path.join(self.current_dir, name)
                if not os.path.isfile(full_path):
                    continue
                if not self.file_io.looks_like_spectrum_file(full_path):
                    continue
                entries.append((os.path.getmtime(full_path), name, full_path))
            entries.sort(reverse=True)
            for _, name, full_path in entries:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, full_path)
                self.file_list.addItem(item)
        self.file_list.blockSignals(False)

    def on_file_selected(self):
        items = self.file_list.selectedItems()
        if not items:
            return
        self.load_file(items[0].data(Qt.ItemDataRole.UserRole))

    def on_open_file_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Spectrum", self.current_dir, "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            self.load_file(file_path)

    # ---- center: plot + fitting results --------------------------------------
    def _build_center_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.lbl_loaded_file = QLabel("Loaded: (none)")
        self.lbl_loaded_file.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_loaded_file)

        display_row = QHBoxLayout()
        display_row.addWidget(QLabel("Displayed:"))
        self.radio_display_sub = QRadioButton("Subtracted")
        self.radio_display_raw = QRadioButton("Raw")
        self.radio_display_sub.setChecked(True)
        self._display_group = QButtonGroup(self)
        self._display_group.addButton(self.radio_display_sub)
        self._display_group.addButton(self.radio_display_raw)
        self.radio_display_sub.toggled.connect(self.update_plot_and_fit)
        display_row.addWidget(self.radio_display_sub)
        display_row.addWidget(self.radio_display_raw)
        display_row.addStretch()
        self.display_toggle_widget = QWidget()
        self.display_toggle_widget.setLayout(display_row)
        self.display_toggle_widget.setVisible(False)
        layout.addWidget(self.display_toggle_widget)

        plot_and_results = QHBoxLayout()

        self.plot_widget = pg.PlotWidget(title="Loaded Spectrum")
        self.plot_widget.setLabel('left', 'Intensity (Counts)')
        self.plot_widget.setLabel('bottom', 'Pixel')
        self.plot_line = self.plot_widget.plot(pen=pg.mkPen('w', width=1))
        self.fit_baseline_curve = self.plot_widget.plot(
            pen=pg.mkPen('#9E9E9E', width=1, style=Qt.PenStyle.DashLine)
        )
        self.fit_curve = self.plot_widget.plot(pen=pg.mkPen('y', width=2))
        self.fit_curve_sub1 = self.plot_widget.plot(pen=pg.mkPen('y', width=1, style=Qt.PenStyle.DashLine))
        self.fit_curve_sub2 = self.plot_widget.plot(pen=pg.mkPen('y', width=1, style=Qt.PenStyle.DashLine))
        plot_and_results.addWidget(self.plot_widget, stretch=3)

        self.fitting_text = QTextEdit()
        self.fitting_text.setReadOnly(True)
        self.fitting_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.fitting_text.setFixedWidth(240)
        plot_and_results.addWidget(self.fitting_text, stretch=1)

        layout.addLayout(plot_and_results, stretch=1)
        return panel

    # ---- right: fitting config + pressure -------------------------------------
    def _build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        fit_group = QGroupBox("Fitting Configurations")
        fit_layout = QGridLayout()

        self.radio_fit_on = QRadioButton("ON")
        self.radio_fit_off = QRadioButton("OFF")
        self.radio_fit_on.setChecked(True)
        fit_radio_layout = QHBoxLayout()
        fit_radio_layout.addWidget(self.radio_fit_on)
        fit_radio_layout.addWidget(self.radio_fit_off)

        self.combo_fit_func = CustomComboBox()
        self.combo_fit_func.addItems(["Pseudo Voigt", "Moffat", "Gauss", "Lorentz"])
        self.combo_fit_func.setCurrentText("Pseudo Voigt")

        self.combo_fit_peak_count = CustomComboBox()
        for count in range(1, 6):
            self.combo_fit_peak_count.addItem(str(count), count)
        self.combo_fit_peak_count.setCurrentIndex(self.combo_fit_peak_count.findData(2))

        self.combo_peak_sort = CustomComboBox()
        self.combo_peak_sort.addItem("x descending", "x_desc")
        self.combo_peak_sort.addItem("x ascending", "x_asc")
        self.combo_peak_sort.addItem("intensity descending", "intensity_desc")
        self.combo_peak_sort.addItem("intensity ascending", "intensity_asc")

        self.combo_baseline_model = CustomComboBox()
        self.combo_baseline_model.addItem("Constant", "Constant")
        self.combo_baseline_model.addItem("Linear", "Linear")
        self.combo_baseline_model.addItem("Quadratic", "Quadratic")
        self.combo_baseline_model.addItem("Auto Polynomial", "Auto Polynomial")
        self.combo_baseline_model.setCurrentIndex(self.combo_baseline_model.findData("Constant"))

        self.spin_fit_start = CustomDoubleSpinBox()
        self.spin_fit_start.setRange(-10000, 20000)
        self.spin_fit_start.setDecimals(2)

        self.spin_fit_end = CustomDoubleSpinBox()
        self.spin_fit_end.setRange(-10000, 20000)
        self.spin_fit_end.setValue(4000.0)
        self.spin_fit_end.setDecimals(2)

        fit_layout.addWidget(QLabel("Fitting:"), 0, 0)
        fit_layout.addLayout(fit_radio_layout, 0, 1)
        fit_layout.addWidget(QLabel("Function:"), 1, 0)
        fit_layout.addWidget(self.combo_fit_func, 1, 1)
        fit_layout.addWidget(QLabel("Fit Peaks:"), 2, 0)
        fit_layout.addWidget(self.combo_fit_peak_count, 2, 1)
        fit_layout.addWidget(QLabel("Sort peaks:"), 3, 0)
        fit_layout.addWidget(self.combo_peak_sort, 3, 1)
        fit_layout.addWidget(QLabel("Baseline:"), 4, 0)
        fit_layout.addWidget(self.combo_baseline_model, 4, 1)
        fit_layout.addWidget(QLabel("Range Start:"), 5, 0)
        fit_layout.addWidget(self.spin_fit_start, 5, 1)
        fit_layout.addWidget(QLabel("Range End:"), 6, 0)
        fit_layout.addWidget(self.spin_fit_end, 6, 1)
        fit_group.setLayout(fit_layout)
        layout.addWidget(fit_group)

        self.radio_fit_on.toggled.connect(self.update_plot_and_fit)
        self.radio_fit_off.toggled.connect(self.update_plot_and_fit)
        self.combo_fit_func.currentTextChanged.connect(self.update_plot_and_fit)
        self.combo_fit_peak_count.currentIndexChanged.connect(self.on_fit_peak_count_changed)
        self.combo_peak_sort.currentIndexChanged.connect(self.update_plot_and_fit)
        self.combo_baseline_model.currentIndexChanged.connect(self.update_plot_and_fit)
        self.spin_fit_start.valueChanged.connect(self.update_plot_and_fit)
        self.spin_fit_end.valueChanged.connect(self.update_plot_and_fit)

        self.btn_save_fit = QPushButton("Save fitting results…")
        self.btn_save_fit.setEnabled(False)
        self.btn_save_fit.clicked.connect(self.on_save_fit_clicked)
        layout.addWidget(self.btn_save_fit)

        press_group = QGroupBox("Pressure Calculation")
        press_layout = QVBoxLayout()
        self.btn_open_pressure = QPushButton("Open Pressure Calculator")
        self.btn_open_pressure.clicked.connect(self.open_pressure_calculator)
        press_layout.addWidget(self.btn_open_pressure)
        press_group.setLayout(press_layout)
        layout.addWidget(press_group)

        layout.addStretch()
        return panel

    # ---- data loading + fitting -----------------------------------------------
    @staticmethod
    def _unit_for_metadata(metadata):
        """"nm" / "cm-1" / "pixel". A file saved without a calibration loaded has its
        x column as a raw pixel index regardless of what spec_mode's header says
        (spec_mode defaults to "Wavelength" even when uncalibrated) -- calib_coeffs
        being present is what actually indicates the axis is nm/cm-1.
        """
        if metadata is None or metadata.get("calib_coeffs") is None:
            return "pixel"
        return "cm-1" if metadata.get("spec_mode") == "Raman shift" else "nm"

    def load_file(self, file_path):
        try:
            x, y, y_raw, y_bg, metadata = self.file_io.load_spectrum_1d(file_path)
        except ValueError as e:
            QMessageBox.warning(self, "Failed to load spectrum", str(e))
            return

        self.current_file_path = file_path
        self.current_x = x
        self.current_y_sub = y
        self.current_y_raw = y_raw
        self.current_y_bg = y_bg
        self.current_metadata = metadata

        self.lbl_loaded_file.setText(f"Loaded: {os.path.basename(file_path)}")
        self.display_toggle_widget.setVisible(y_raw is not None)

        self.current_unit = self._unit_for_metadata(metadata)
        if self.current_unit == "cm-1":
            x_label = 'Raman shift (cm⁻¹)'
        elif self.current_unit == "nm":
            x_label = 'Wavelength (nm)'
        else:
            x_label = 'Pixel'
        self.plot_widget.setLabel('bottom', x_label)
        if self.pressure_window is not None and self.current_unit != "pixel":
            self.pressure_window.update_mode(self.current_unit)

        min_x, max_x = float(np.min(x)), float(np.max(x))
        self.spin_fit_start.blockSignals(True)
        self.spin_fit_end.blockSignals(True)
        self.spin_fit_start.setValue(min_x)
        self.spin_fit_end.setValue(max_x)
        self.spin_fit_start.blockSignals(False)
        self.spin_fit_end.blockSignals(False)

        self.update_plot_and_fit()

    def on_fit_peak_count_changed(self):
        if self.pressure_window is not None:
            self.pressure_window.set_fit_peak_count(self.combo_fit_peak_count.currentData(), reset_selection=True)
        self.update_plot_and_fit()

    def update_plot_and_fit(self):
        if self.current_x is None:
            return

        y_display = self.current_y_raw if self.radio_display_raw.isChecked() and self.current_y_raw is not None else self.current_y_sub
        self.plot_line.setData(self.current_x, y_display)

        self.btn_save_fit.setEnabled(False)
        if not self.radio_fit_on.isChecked():
            self._clear_fit_curves()
            self.fitting_text.setHtml("")
            self.latest_fit_res = None
            if self.pressure_window is not None:
                self.pressure_window.set_fit_peaks([])
            return

        func = self.combo_fit_func.currentText()
        peak_count = self.combo_fit_peak_count.currentData()
        peak_sort_order = self.combo_peak_sort.currentData()
        baseline_model = self.combo_baseline_model.currentData()
        fit_start = self.spin_fit_start.value()
        fit_end = self.spin_fit_end.value()

        x_fit, y_fit, res = self.analyzer.fit_spectrum(
            self.current_x, y_display, func, fit_start, fit_end,
            peak_count=peak_count, peak_sort_order=peak_sort_order,
            baseline_model=baseline_model,
        )

        if x_fit is None:
            self._clear_fit_curves()
            self.latest_fit_res = None
            if self.pressure_window is not None:
                self.pressure_window.set_fit_peaks([])
            self.fitting_text.setHtml("<span>Fitting failed or out of range.</span>")
            return

        self.latest_fit_res = res.copy()
        self.latest_fit_func = func
        self.btn_save_fit.setEnabled(True)

        self.fit_curve.setData(x_fit, y_fit)
        self.fit_baseline_curve.setData(x_fit, res["y_baseline"])
        if res.get("peak_count", 1) > 1 and "y_fit1" in res:
            self.fit_curve_sub1.setData(x_fit, res["y_fit1"])
            if "y_fit2" in res:
                self.fit_curve_sub2.setData(x_fit, res["y_fit2"])
            else:
                self.fit_curve_sub2.clear()
        else:
            self.fit_curve_sub1.clear()
            self.fit_curve_sub2.clear()

        if self.pressure_window is not None:
            # Never feed pixel positions into the pressure calculator, even if it was
            # left open from a previously-loaded calibrated file -- clear it instead so
            # it can't silently report a bogus pressure computed from pixel indices.
            self.pressure_window.set_fit_peaks(res["peaks"] if self.current_unit != "pixel" else [])

        text = (
            f"<span><b>Function:</b> {func}<br>"
            f"<b>Fit Peaks:</b> {peak_count}<br>"
            f"<b>Sort peaks:</b> {self.combo_peak_sort.currentText()}<br>"
        )
        baseline = res["baseline"]
        baseline_text = baseline["requested"]
        if baseline["requested"] != baseline["selected"]:
            baseline_text += f" &rarr; {baseline['selected']}"
        text += f"<b>Baseline:</b> {baseline_text}<br><br>"
        for peak in res["peaks"]:
            i = peak["index"]
            text += f"<u>Peak {i}</u><br>"
            text += f" Pos: {peak['position']:.3f} &plusmn; {peak['position_err']:.3f}<br>"
            text += f" Width: {peak['width']:.3f} &plusmn; {peak['width_err']:.3f}<br><br>"
        text += f"<b>R-value:</b><br> {res['R2']:.4f}</span>"

        if self.current_unit != "pixel" and self.pressure_window is not None and self.pressure_window.isVisible():
            p = self.pressure_window.current_pressure
            p_err = self.pressure_window.current_pressure_err
            if p is not None and p_err is not None:
                text += f"<br><br><span>Calculated Pressure:<br>{p:.3f} &plusmn; {p_err:.3f} GPa</span>"

        self.fitting_text.setHtml(text)

    def _clear_fit_curves(self):
        self.fit_curve.clear()
        self.fit_baseline_curve.clear()
        self.fit_curve_sub1.clear()
        self.fit_curve_sub2.clear()

    def on_save_fit_clicked(self):
        if self.latest_fit_res is None or self.current_file_path is None:
            return
        default_path = self.current_file_path.rsplit('.', 1)[0] + "_fitting_results.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Fitting Results", default_path, "Text Files (*.txt)"
        )
        if not file_path:
            return

        pressure_info = None
        pw = self.pressure_window
        if self.current_unit != "pixel" and pw is not None and pw.isVisible() and pw.current_pressure is not None:
            lam0_value = pw.current_zero_peak_at_current_t
            if lam0_value is None:
                lam0_value = pw.spin_lam0_t0.value() if pw.radio_on.isChecked() else pw.spin_lam0.value()
            pressure_info = {
                "pressure": pw.current_pressure,
                "pressure_err": pw.current_pressure_err,
                "scale": pw.combo_p_scale.currentText(),
                "sensor": pw.combo_sensor.currentText(),
                "lam0": lam0_value,
                "lam0_unit": pw.unit,
            }

        try:
            self.file_io.save_fitting_results(
                file_path, self.latest_fit_res, self.latest_fit_func, pressure_info=pressure_info
            )
            QMessageBox.information(self, "Success", f"Fitting results saved to:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save fitting results:\n{e}")

    # ---- pressure calculator ---------------------------------------------------
    def open_pressure_calculator(self):
        if self.radio_fit_off.isChecked():
            QMessageBox.warning(self, "Fitting required", "Please activate peak fitting to calculate pressure.")
            return
        if self.current_unit is None:
            QMessageBox.warning(self, "No spectrum loaded", "Load a spectrum first.")
            return
        if self.current_unit == "pixel":
            QMessageBox.warning(
                self, "Calibration required",
                "This spectrum has no wavelength/Raman-shift calibration (pixel axis only); "
                "pressure cannot be calculated from pixel positions."
            )
            return

        unit = self.current_unit
        if self.pressure_window is None:
            self.pressure_window = PressureCalculatorWindow(self, mode=unit)
        else:
            self.pressure_window.update_mode(unit)

        self.pressure_window.show()
        self.pressure_window.raise_()
        self.pressure_window.activateWindow()
        if self.latest_fit_res is not None and self.latest_fit_res.get("peaks"):
            self.pressure_window.set_fit_peaks(self.latest_fit_res["peaks"])
        else:
            self.pressure_window.set_fit_peak_count(self.combo_fit_peak_count.currentData())
