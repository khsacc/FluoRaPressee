"""AnalysisWindow: load previously-saved spectra and re-run fitting / pressure
calculation on them, with no spectrometer/camera connection required.

Usable both as a standalone top-level window (see analysis_main.py) and as an
independent sub-window opened from the live SpectrometerGUI (src/ui.py). It shares
the fitting-configuration widget and pressure-calculator UI with the live GUI, as
well as the hardware-independent DataAnalyzer and DataFileIO backends. Plot and
loaded-file widgets remain specific to Analysis Mode.

The x-axis column saved by DataFileIO.save_spectrum_1d is already fully resolved
(nm / cm-1 / pixel) at save time, so loading a file here never needs calibration,
grating, or ROI state -- just plot the columns and feed them to DataAnalyzer.
"""

import os

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QFileSystemWatcher
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QScrollArea,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QRadioButton, QButtonGroup,
    QTextEdit, QFileDialog, QMessageBox,
)

from src.core.analysis import DataAnalyzer
from src.core.file_io import DataFileIO
from src.ui.fitting_config_widget import FittingConfigWidget
from src.ui.fit_range_context_menu import FitRangeContextMenu
from src.ui.pressureCalc_ui import PressureCalculatorWindow
from src.ui.local_cache import load_local_cache, save_local_cache

_LAST_DIR_CACHE_KEY = "last_analysis_dir"

# Analysis Mode's plot is meant to be publication-ready as-is (white background,
# Arial/Helvetica, labelled axes, legend) rather than match the live GUI's dark
# monitoring view -- kept local to this module/widget instance rather than via
# pg.setConfigOption, which is process-global and would also repaint the live
# GUI's plot if Analysis Mode is opened as a sub-window in the same process.
_PLOT_FONT_FAMILIES = ["Arial", "Helvetica"]
_PLOT_LABEL_STYLE = {
    "color": "#000000",
    "font-size": "12pt",
    "font-family": "Arial, Helvetica, sans-serif",
}


def _axis_tick_font():
    font = QFont()
    if hasattr(font, "setFamilies"):
        font.setFamilies(_PLOT_FONT_FAMILIES)
    else:
        font.setFamily(_PLOT_FONT_FAMILIES[0])
    return font


class AnalysisWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FluoraPressée: Analysis Mode")
        self.resize(1650, 900)

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
        layout.addWidget(self._build_right_panel(), stretch=2)

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

    # ---- center: plot ---------------------------------------------------------
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

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')

        # LabelItem (used for the title) takes different option keys than AxisItem's
        # CSS-passthrough labelStyle -- "family"/"size"/"bold", not "font-family" etc.
        self.plot_widget.setTitle(
            "Loaded Spectrum", color="#000000",
            family="Arial, Helvetica, sans-serif", size="13pt", bold=True,
        )
        self.plot_widget.setLabel('left', 'Intensity (Counts)', **_PLOT_LABEL_STYLE)
        self.plot_widget.setLabel('bottom', 'Pixel', **_PLOT_LABEL_STYLE)

        tick_font = _axis_tick_font()
        for axis_name in ('left', 'bottom'):
            axis = self.plot_widget.getAxis(axis_name)
            axis.setPen('k')
            axis.setTextPen('k')
            axis.setStyle(tickFont=tick_font)

        self.plot_widget.addLegend(offset=(10, 10), pen='k', brush='w', labelTextColor='k')

        self.plot_line = self.plot_widget.plot(
            pen=None, symbol='o', symbolSize=5, symbolBrush='k', symbolPen=None, name="Data"
        )
        self.fit_baseline_curve = self.plot_widget.plot(
            pen=pg.mkPen('#757575', width=1, style=Qt.PenStyle.DashLine), name="Baseline"
        )
        self.fit_curve = self.plot_widget.plot(pen=pg.mkPen('r', width=2), name="Fit")
        self.fit_curve_sub1 = self.plot_widget.plot(
            pen=pg.mkPen('#1976D2', width=1, style=Qt.PenStyle.DashLine), name="Peak 1"
        )
        self.fit_curve_sub2 = self.plot_widget.plot(
            pen=pg.mkPen('#7B1FA2', width=1, style=Qt.PenStyle.DashLine), name="Peak 2"
        )
        self.edge_marker = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen('#00838F', width=2, style=Qt.PenStyle.DashLine)
        )
        self.edge_marker.hide()
        self.plot_widget.addItem(self.edge_marker)

        # LegendItem.addItem() builds its row labels with hardcoded style keys that
        # don't include "family", so the legend text needs a second pass to pick up
        # the same Arial/Helvetica styling as the rest of the plot.
        legend = self.plot_widget.getPlotItem().legend
        for _, label in legend.items:
            label.setText(label.text, color="#000000", family="Arial, Helvetica, sans-serif", size="10pt")

        layout.addWidget(self.plot_widget, stretch=1)
        return panel

    # ---- right: fitting config + pressure, as two independent columns ---------
    def _build_right_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        panel = QWidget()
        layout = QHBoxLayout(panel)

        fitting_column = QVBoxLayout()
        self.fitting_config = FittingConfigWidget(fitting_enabled=True, parent=panel)
        self.fitting_config.expose_controls_on(self)
        fitting_column.addWidget(self.fitting_config)

        self.radio_fit_on.toggled.connect(self.update_plot_and_fit)
        self.radio_fit_off.toggled.connect(self.update_plot_and_fit)
        self.combo_fit_func.currentTextChanged.connect(self.update_plot_and_fit)
        self.combo_fit_peak_count.currentIndexChanged.connect(self.on_fit_peak_count_changed)
        self.combo_peak_sort.currentIndexChanged.connect(self.update_plot_and_fit)
        self.combo_baseline_model.currentIndexChanged.connect(self.update_plot_and_fit)
        self.spin_fit_start.valueChanged.connect(self.update_plot_and_fit)
        self.spin_fit_end.valueChanged.connect(self.update_plot_and_fit)
        self.fit_range_context_menu = FitRangeContextMenu(
            self.plot_widget,
            self.spin_fit_start,
            self.spin_fit_end,
            lambda: self.current_x is not None,
        )

        self.fitting_results_group = QGroupBox("Fitting Results")
        fitting_results_layout = QVBoxLayout(self.fitting_results_group)
        self.fitting_text = QTextEdit()
        self.fitting_text.setReadOnly(True)
        self.fitting_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.fitting_text.setMinimumHeight(220)
        fitting_results_layout.addWidget(self.fitting_text)
        fitting_column.addWidget(self.fitting_results_group, stretch=1)

        self.btn_save_fit = QPushButton("Save fitting results…")
        self.btn_save_fit.setEnabled(False)
        self.btn_save_fit.clicked.connect(self.on_save_fit_clicked)
        fitting_column.addWidget(self.btn_save_fit)
        layout.addLayout(fitting_column, stretch=1)

        # Wrapped in its own titled QGroupBox (mirroring FittingConfigWidget's own
        # border/title) purely so the two columns read as clearly independent panels
        # side by side, rather than one flowing into the other.
        self.pressure_group = QGroupBox("Pressure Calculation")
        pressure_group_layout = QVBoxLayout(self.pressure_group)
        self.pressure_window = PressureCalculatorWindow(
            self.pressure_group,
            mode="nm",
            embedded=True,
            fit_controls_owner=self,
        )
        self.pressure_window.setEnabled(False)
        self.pressure_window.setToolTip("Load a calibrated spectrum to calculate pressure.")
        pressure_group_layout.addWidget(self.pressure_window)

        pressure_margins = pressure_group_layout.contentsMargins()
        pressure_frame_allowance = 6
        self.pressure_group_natural_width = (
            self.pressure_window.unconstrained_width
            + pressure_margins.left() + pressure_margins.right()
            + pressure_frame_allowance
        )
        self.pressure_group_max_width = round(self.pressure_group_natural_width * 0.8)
        self.pressure_group.setMaximumWidth(self.pressure_group_max_width)

        pressure_column = QVBoxLayout()
        pressure_column.addWidget(self.pressure_group)
        pressure_column.addStretch()
        layout.addLayout(pressure_column, stretch=1)

        margins = layout.contentsMargins()
        scroll.setMinimumWidth(
            self.fitting_config.minimumSizeHint().width()
            + self.pressure_group_max_width
            + margins.left() + margins.right() + layout.spacing()
            + scroll.verticalScrollBar().sizeHint().width()
        )

        scroll.setWidget(panel)
        return scroll

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
        self.plot_widget.setLabel('bottom', x_label, **_PLOT_LABEL_STYLE)
        if self.current_unit == "pixel":
            self.pressure_window.set_fit_peaks([])
            self.pressure_window.setEnabled(False)
            self.pressure_window.setToolTip(
                "This spectrum has a pixel axis only; pressure calculation requires calibration."
            )
        else:
            self.pressure_window.update_mode(self.current_unit)
            self.pressure_window.setEnabled(self.radio_fit_on.isChecked())
            self.pressure_window.setToolTip("")

        min_x, max_x = float(np.min(x)), float(np.max(x))
        view_box = self.plot_widget.getViewBox()
        view_box.setLimits(xMin=min_x, xMax=max_x)
        view_box.setDefaultPadding(0)
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

        pressure_available = self.current_unit != "pixel" and self.radio_fit_on.isChecked()
        self.pressure_window.setEnabled(pressure_available)

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
        is_edge = res.get("analysis_type") == "diamond_raman_edge"
        if is_edge:
            self.fit_baseline_curve.clear()
            self.edge_marker.setValue(res["edge_position"])
            self.edge_marker.show()
        else:
            self.fit_baseline_curve.setData(x_fit, res["y_baseline"])
            self.edge_marker.hide()
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
        )
        if is_edge:
            text += "<b>Method:</b> -dI/dν, pseudo-Voigt + linear baseline<br><br>"
        else:
            text += (
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
            text += f"<u>{'Diamond edge' if is_edge else f'Peak {i}'}</u><br>"
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
        self.edge_marker.hide()

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
