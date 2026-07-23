import os
import numpy as np
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTableWidget, QTableWidgetItem,
                             QCheckBox, QComboBox, QHeaderView, QWidget,
                             QAbstractSpinBox, QDoubleSpinBox, QSplitter,
                             QScrollArea, QRadioButton, QMessageBox, QSlider,
                             QListWidget, QListWidgetItem, QButtonGroup, QMenu,
                             QCompleter)
from PyQt6.QtCore import Qt
import pyqtgraph as pg

from src.calibration import CalibrationCore
from src.calibration_reference import (
    find_match_candidates,
    load_reference_standards,
    match_from_seed_axis,
)
from src.configuration_catalog import format_configuration_label
from src.ui_theme import colored_button_style

class CustomDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    def wheelEvent(self, event):
        event.ignore()

class CalibrationWindow(QDialog):
    def __init__(self, camera_thread=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wavelength Calibration")
        self.resize(1100, 750)
        
        self.setStyleSheet("""
            QWidget { color: #000000; }
            QDialog { background-color: #FAFAFA; }
            QLabel { color: #000000; font-size: 13px; }
            QGroupBox { font-weight: bold; color: #000000; }
            QTableWidget { background-color: #FFFFFF; color: #000000; alternate-background-color: #F0F0F0; }
            QHeaderView::section { background-color: #E0E0E0; font-weight: bold; color: #000000; }
            QRadioButton { color: #000000; }
            QCheckBox { color: #000000; }
            QPushButton { background-color: #E0E0E0; color: #000000; border: 1px solid #999; border-bottom: 3px solid #666; border-radius: 4px; padding: 5px 10px; min-height: 16px; }
            QPushButton:hover:!pressed { background-color: #D0D0D0; border-color: #2196F3; border-bottom-color: #666; }
            QPushButton:pressed { background-color: #C8C8C8; border-style: inset; border-bottom-width: 1px; padding-top: 7px; padding-bottom: 5px; }
            QPushButton:disabled { background-color: #E8E8E8; color: #888; border-color: #AAA; }
            QComboBox { background-color: #FFFFFF; color: #000000; border: 1px solid #999; }
            QComboBox QAbstractItemView { background-color: #FFFFFF; color: #000000; selection-background-color: #2196F3; selection-color: #FFFFFF; }
            QDoubleSpinBox { background-color: #FFFFFF; color: #000000; border: 1px solid #999; }
            QSpinBox { background-color: #FFFFFF; color: #000000; border: 1px solid #999; }
        """)
        
        self.camera_thread = camera_thread
        self.calib_core = CalibrationCore()
        
        self.current_spectrum = None
        self.fitted_peaks = []
        self.peak_lines = []
        self.peak_texts = []
        self.peak_tick_items = []
        self.reference_overlay_items = []
        self.is_acquiring = False
        
        self.calib_coeffs = None 
        self.row_widgets = []
        # Assignments are independent of the reference-standard visibility.
        # Switching Ne/Ar must never silently discard a confirmed relationship.
        self.assignments = {}
        self.selected_peak_row = None
        self.match_candidates = []
        self.match_peak_rows = []
        self.initial_wavelength_axis = None
        self.reference_candidate_menu = QMenu(self)
        standards_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "calibrationStandards"
        )
        self.reference_standards = load_reference_standards(standards_dir)
        self.reference_lines_by_id = {
            line.line_id: line
            for standard in self.reference_standards.values()
            for line in standard.lines
        }
        
        self.init_ui()
        
        main_window = self.parent()
        if main_window and hasattr(main_window, 'radio_spec_mode_raman') and main_window.radio_spec_mode_raman.isChecked():
            self.radio_unit_raman.setChecked(True)
        else:
            self.radio_unit_wl.setChecked(True)
        
        self.update_table_header()
        
        if self.camera_thread:
            self.camera_thread.data_ready.connect(self.on_data_ready)

    def nm_to_raman(self, wl_nm, laser_wl):
        return self.calib_core.nm_to_raman(wl_nm, laser_wl)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        plot_splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setTitle("Full Spectrum", color='k')
        self.plot_widget.setBackground('w')
        self.plot_widget.getAxis('bottom').setPen('k')
        self.plot_widget.getAxis('left').setPen('k')
        self.plot_widget.setLabel('left', 'Intensity (Counts)', color='k')
        self.plot_widget.setLabel('bottom', 'Pixel', color='k')
        self.plot_widget.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self.plot_legend = self.plot_widget.addLegend(offset=(10, 10))
        if hasattr(self.plot_legend, "setLabelTextColor"):
            self.plot_legend.setLabelTextColor("k")
        self.plot_legend.addItem(
            pg.PlotDataItem(pen=pg.mkPen("#EF6C00", width=3)),
            "Detected peak",
        )
        self.plot_legend.addItem(
            pg.PlotDataItem(pen=pg.mkPen("#1565C0", width=3)),
            "Literature line",
        )
        self.plot_legend.addItem(
            pg.PlotDataItem(
                pen=pg.mkPen("#D32F2F", width=2, style=Qt.PenStyle.DashLine)
            ),
            "Used peak",
        )
        self.plot_scatter = self.plot_widget.plot(pen=None, symbol='o', symbolSize=3, symbolBrush='b')
        self.detected_select_scatter = pg.ScatterPlotItem(
            # Transparent hit targets preserve the tick-only visual design.
            symbol="s", size=13, pen=pg.mkPen(None),
            brush=pg.mkBrush(0, 0, 0, 0), hoverable=True,
            tip=self._detected_peak_tooltip,
        )
        self.detected_select_scatter.sigClicked.connect(
            self.on_measured_peak_clicked
        )
        self.plot_widget.addItem(self.detected_select_scatter)
        self.reference_select_scatter = pg.ScatterPlotItem(
            # Keep a transparent hit target over each literature tick so the
            # plain vertical bar remains clickable without looking like a
            # box-and-whisker marker.
            symbol="s", size=11, pen=pg.mkPen(None),
            brush=pg.mkBrush(0, 0, 0, 0), hoverable=True,
            tip=self._reference_line_tooltip,
        )
        self.reference_select_scatter.sigClicked.connect(self.on_reference_line_clicked)
        self.plot_widget.addItem(self.reference_select_scatter)
        plot_splitter.addWidget(self.plot_widget)
        
        self.bottom_scroll = QScrollArea()
        self.bottom_scroll.setFixedHeight(220)
        self.bottom_scroll.setWidgetResizable(True)
        self.bottom_content = QWidget()
        self.bottom_content.setStyleSheet("background-color: #FFFFFF;")
        self.bottom_layout = QHBoxLayout(self.bottom_content)
        self.bottom_scroll.setWidget(self.bottom_content)
        plot_splitter.addWidget(self.bottom_scroll)
        
        plot_splitter.setStretchFactor(0, 3)
        plot_splitter.setStretchFactor(1, 1)
        main_layout.addWidget(plot_splitter, stretch=2)
        
        controls_layout = QVBoxLayout()
        
        self.btn_acquire = QPushButton("Acquire a spectrum")
        self.btn_acquire.setAutoDefault(False)
        self.btn_acquire.setDefault(False)
        self.btn_acquire.clicked.connect(self.acquire_spectrum)
        self.btn_acquire.setStyleSheet("font-weight: bold; padding: 5px;")

        self.btn_use_displayed = QPushButton("Use displayed data")
        self.btn_use_displayed.setAutoDefault(False)
        self.btn_use_displayed.setDefault(False)
        self.btn_use_displayed.setToolTip("Use the spectrum currently shown in the main window's 1D plot instead of acquiring a new one.")
        self.btn_use_displayed.clicked.connect(self.use_displayed_data)
        self.btn_use_displayed.setStyleSheet("padding: 5px;")

        acq_time_layout = QHBoxLayout()
        acq_time_layout.addWidget(QLabel("Acquisition time (s):"))
        self.spin_acq_time = CustomDoubleSpinBox()
        self.spin_acq_time.setRange(0.001, 3600)
        self.spin_acq_time.setValue(0.1)
        self.spin_acq_time.setDecimals(3)
        self.spin_acq_time.editingFinished.connect(self.update_acq_time)
        acq_time_layout.addWidget(self.spin_acq_time)

        unit_layout = QHBoxLayout()
        self.radio_unit_wl = QRadioButton("Wavelength (nm)")
        self.radio_unit_raman = QRadioButton("Raman shift (cm⁻¹)")
        self.radio_unit_wl.setChecked(True)
        
        self.radio_unit_wl.toggled.connect(self.update_ui_units)
        self.radio_unit_raman.toggled.connect(self.update_ui_units)
        
        unit_layout.addWidget(QLabel("Calibration Unit:"))
        unit_layout.addWidget(self.radio_unit_wl)
        unit_layout.addWidget(self.radio_unit_raman)
        unit_layout.addStretch()
        
        find_peaks_layout = QHBoxLayout()
        self.btn_find_peaks = QPushButton("Find peaks")
        self.btn_find_peaks.setAutoDefault(False)
        self.btn_find_peaks.setDefault(False)
        self.btn_find_peaks.clicked.connect(self.find_peaks)
        self.btn_find_peaks.setStyleSheet("padding: 5px;")
        
        slider_layout = QVBoxLayout()
        self.slider_threshold_label = QLabel("Threshold: 7.5× noise")
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        # Stored as multiplier * 10 so the integer slider can represent one
        # decimal place.  A high ceiling is useful for spectra with strong
        # broadband/read noise while preserving the previous 7.5x default.
        self.slider_threshold.setRange(10, 500)
        self.slider_threshold.setValue(75)
        self.slider_threshold.valueChanged.connect(
            lambda value: self.slider_threshold_label.setText(
                f"Threshold: {value / 10.0:.1f}× noise"
            )
        )
        slider_layout.addWidget(self.slider_threshold_label)
        slider_layout.addWidget(self.slider_threshold)
        
        find_peaks_layout.addWidget(self.btn_find_peaks)
        find_peaks_layout.addLayout(slider_layout)

        reference_layout = QVBoxLayout()
        reference_layout.addWidget(QLabel("Emission standards (multiple selection):"))
        self.list_standards = QListWidget()
        self.list_standards.setMaximumHeight(76)
        for standard_id, standard in self.reference_standards.items():
            item = QListWidgetItem(standard.display_name)
            item.setData(Qt.ItemDataRole.UserRole, standard_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if standard_id == "Ne-I" else Qt.CheckState.Unchecked
            )
            self.list_standards.addItem(item)
        self.list_standards.itemChanged.connect(self.on_active_standards_changed)
        reference_layout.addWidget(self.list_standards)

        match_layout = QHBoxLayout()
        self.btn_auto_match = QPushButton("Find assignments")
        self.btn_auto_match.clicked.connect(self.find_assignment_candidates)
        self.combo_match_candidate = QComboBox()
        self.combo_match_candidate.setMinimumWidth(190)
        self.combo_match_candidate.currentIndexChanged.connect(
            lambda _index: self.update_reference_overlay()
        )
        self.btn_apply_candidate = QPushButton("Apply candidate")
        self.btn_apply_candidate.setEnabled(False)
        self.btn_apply_candidate.clicked.connect(self.apply_selected_candidate)
        self.btn_clear_assignment = QPushButton("Clear assignment")
        self.btn_clear_assignment.setEnabled(False)
        self.btn_clear_assignment.clicked.connect(self.clear_selected_assignment)
        match_layout.addWidget(self.btn_auto_match)
        match_layout.addWidget(self.combo_match_candidate, stretch=1)
        match_layout.addWidget(self.btn_apply_candidate)
        match_layout.addWidget(self.btn_clear_assignment)
        reference_layout.addLayout(match_layout)
        self.lbl_assignment_help = QLabel(
            "Select a detected tick, fit plot, or table row; then click a "
            "literature tick, or use an automatic candidate."
        )
        self.lbl_assignment_help.setWordWrap(True)
        self.lbl_assignment_help.setStyleSheet("color: #555; font-size: 11px;")
        reference_layout.addWidget(self.lbl_assignment_help)

        self.unit_button_group = QButtonGroup(self)
        self.unit_button_group.addButton(self.radio_unit_wl)
        self.unit_button_group.addButton(self.radio_unit_raman)

        self.table = QTableWidget(0, 5)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(self.on_table_peak_selected)
        
        self.btn_calibrate = QPushButton("Calibrate")
        self.btn_calibrate.setAutoDefault(False)
        self.btn_calibrate.setDefault(False)
        self.btn_calibrate.clicked.connect(self.calibrate)
        self.btn_calibrate.setStyleSheet(colored_button_style(
            "font-weight: bold; color: white; background-color: #2196F3;",
            "font-weight: bold; color: white; background-color: #A0A0A0;",
        ))
        
        self.lbl_calib_result = QLabel("y = c0 + c1*x + c2*x^2\nc0 = ...\nc1 = ...\nc2 = ...")
        self.lbl_calib_result.setStyleSheet("font-family: Consolas; background-color: #EEEEEE; padding: 10px; border: 1px solid #CCC; color: #000000;")
        
        self.btn_save_apply = QPushButton("Save and apply")
        self.btn_save_apply.setAutoDefault(False)
        self.btn_save_apply.setDefault(False)
        self.btn_save_apply.setEnabled(False)
        self.btn_save_apply.clicked.connect(self.save_and_apply)
        
        controls_layout.addWidget(self.btn_acquire)
        controls_layout.addWidget(self.btn_use_displayed)
        controls_layout.addLayout(acq_time_layout)
        controls_layout.addLayout(unit_layout) 
        controls_layout.addLayout(find_peaks_layout)
        controls_layout.addLayout(reference_layout)
        controls_layout.addWidget(self.table)
        controls_layout.addWidget(self.btn_calibrate)
        controls_layout.addWidget(self.lbl_calib_result)
        controls_layout.addWidget(self.btn_save_apply)
        
        main_layout.addLayout(controls_layout, stretch=1)

    def update_ui_units(self):
        self.update_table_header()
        self.update_table_value_widgets()

    def update_table_header(self):
        unit_str = "nm" if self.radio_unit_wl.isChecked() else "cm⁻¹"
        self.table.setHorizontalHeaderLabels(
            ["Peak pos. (px)", "Use", f"Reference ({unit_str})", "Species", "Status"]
        )

    def update_acq_time(self):
        if self.camera_thread:
            self.camera_thread.update_exposure(self.spin_acq_time.value())
            
    def acquire_spectrum(self):
        if self.camera_thread:
            self.update_acq_time()
            self.is_acquiring = True
            self.btn_acquire.setEnabled(False)
            self.btn_acquire.setText("Acquiring...")
            self.camera_thread.start_measuring()
            
    def on_data_ready(self, mode, data):
        if self.is_acquiring and mode == "1d":
            if self.parent() and hasattr(self.parent(), 'chk_flip_x') and self.parent().chk_flip_x.isChecked():
                data = data[::-1]
            self.current_spectrum = data
            self.plot_scatter.setData(data)
            self._apply_plot_data_limits(len(data))
            self._refresh_initial_wavelength_axis(len(data))
            self.assignments.clear()
            self.camera_thread.stop_measuring()
            self.is_acquiring = False
            self.btn_acquire.setEnabled(True)
            self.btn_acquire.setText("Acquire a spectrum")
            self.find_peaks()

    def use_displayed_data(self):
        # main_window.latest_1d_data already has background subtraction / X-flip applied, matching the on-screen plot.
        main_window = self.parent()
        if main_window is None or not hasattr(main_window, 'latest_1d_data'):
            QMessageBox.warning(self, "Warning", "No main window data available.")
            return
        if self.is_acquiring:
            QMessageBox.warning(self, "Warning", "An acquisition is already in progress.")
            return
        if (main_window.latest_1d_data is None
                or not hasattr(main_window, 'stacked_widget')
                or main_window.stacked_widget.currentIndex() != 0):
            QMessageBox.warning(self, "Warning", "No 1D spectrum is currently displayed in the main window.")
            return
        self.current_spectrum = main_window.latest_1d_data.copy()
        self.plot_scatter.setData(self.current_spectrum)
        self._apply_plot_data_limits(len(self.current_spectrum))
        self._refresh_initial_wavelength_axis(len(self.current_spectrum))
        self.assignments.clear()
        self.find_peaks()

    def _refresh_initial_wavelength_axis(self, number_pixels):
        """Get a backend-provided seed axis without treating it as final calibration."""
        axis = None
        native = getattr(self.camera_thread, "native_wavelengths", None)
        if native is not None and len(native) == number_pixels:
            axis = np.asarray(native, dtype=float).copy()
        else:
            main_window = self.parent()
            spec_ctrl = getattr(main_window, "spec_ctrl", None)
            getter = getattr(spec_ctrl, "get_calibration_seed_axis", None)
            pixel_width = getattr(
                self.camera_thread, "_metadata_pixel_pitch_um", {}
            ).get("width")
            if getter is not None:
                axis = getter(number_pixels, pixel_width)

        main_window = self.parent()
        if (
            axis is not None
            and main_window is not None
            and hasattr(main_window, "chk_flip_x")
            and main_window.chk_flip_x.isChecked()
        ):
            axis = axis[::-1]
        if (
            axis is not None
            and len(axis) == number_pixels
            and np.all(np.isfinite(axis))
        ):
            self.initial_wavelength_axis = np.asarray(axis, dtype=float)
        else:
            self.initial_wavelength_axis = None

    def _apply_plot_data_limits(self, number_pixels):
        """Keep calibration pan/zoom inside the acquired pixel domain."""
        if number_pixels <= 0:
            return
        x_min = 0.0
        x_max = float(max(0, number_pixels - 1))
        view_box = self.plot_widget.getViewBox()
        view_box.setLimits(xMin=x_min, xMax=x_max)
        view_box.setDefaultPadding(0)
        if number_pixels > 1:
            view_box.setXRange(x_min, x_max, padding=0)

    def active_standard_ids(self):
        return {
            self.list_standards.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.list_standards.count())
            if self.list_standards.item(index).checkState() == Qt.CheckState.Checked
        }

    def active_reference_lines(self):
        lines = []
        for standard_id in self.active_standard_ids():
            standard = self.reference_standards.get(standard_id)
            if standard is not None:
                lines.extend(
                    line for line in standard.lines
                    if line.enabled_for_calibration
                )
        return sorted(lines, key=lambda line: line.wavelength_nm)

    def _center_wavelength_nm(self):
        main_window = self.parent()
        value = getattr(main_window, "physical_center_wl", None)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if np.isfinite(value) and value > 0 else None

    def _tick_levels(self):
        """Return separated y ranges below the measured spectrum for peak ticks."""
        if self.current_spectrum is None or len(self.current_spectrum) == 0:
            return {
                "detected": (-0.08, -0.02),
                "literature": (-0.17, -0.11),
            }
        y_min = float(np.min(self.current_spectrum))
        y_max = float(np.max(self.current_spectrum))
        span = max(y_max - y_min, abs(y_max) * 0.1, 1.0)
        baseline = min(0.0, y_min)
        return {
            "detected": (
                baseline - 0.08 * span,
                baseline - 0.02 * span,
            ),
            "literature": (
                baseline - 0.17 * span,
                baseline - 0.11 * span,
            ),
        }

    def find_peaks(self):
        if self.current_spectrum is None:
            return
        self._apply_plot_data_limits(len(self.current_spectrum))
        previous = []
        for row, assignment in self.assignments.items():
            if row < len(self.row_widgets):
                previous.append((self.row_widgets[row]["px"], assignment))
        threshold_mult = self.slider_threshold.value() / 10.0
        fitted_peaks = self.calib_core.find_and_fit_peaks(self.current_spectrum, prominence_multiplier=threshold_mult)
        self.fitted_peaks = fitted_peaks
        self.table.setRowCount(0)
        self.row_widgets.clear()
        self.assignments = {}
        self.selected_peak_row = None
        self.match_candidates = []
        self.combo_match_candidate.clear()
        self.btn_apply_candidate.setEnabled(False)
        for item in self.peak_lines + self.peak_texts + self.peak_tick_items:
            self.plot_widget.removeItem(item)
        self.peak_lines.clear()
        self.peak_texts.clear()
        self.peak_tick_items.clear()
        while self.bottom_layout.count():
            child = self.bottom_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        detected_tick_low, detected_tick_high = self._tick_levels()["detected"]
        detected_spots = []
        for i, p_data in enumerate(fitted_peaks):
            center = p_data["center"]
            row = self.table.rowCount()
            self.table.insertRow(row)
            pos_item = QTableWidgetItem(f"{center:.2f}")
            pos_item.setFlags(pos_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, pos_item)
            chk = QCheckBox()
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.addWidget(chk)
            self.table.setCellWidget(row, 1, chk_widget)
            self.row_widgets.append({"check": chk, "input": None, "px": center})
            chk.checkStateChanged.connect(lambda state, r=row: self.on_use_toggled(state, r))
            self.table.setItem(row, 3, QTableWidgetItem(""))
            self.table.setItem(row, 4, QTableWidgetItem("Unassigned"))
            line = pg.InfiniteLine(
                pos=center,
                angle=90,
                pen=pg.mkPen("#D32F2F", width=2, style=Qt.PenStyle.DashLine),
            )
            line.setVisible(False)
            tick = pg.PlotDataItem(
                [center, center],
                [detected_tick_low, detected_tick_high],
                pen=pg.mkPen("#EF6C00", width=3),
            )
            text = pg.TextItem(f"#{i+1}", color="#EF6C00", anchor=(0.5, 1.0))
            text.setPos(center, detected_tick_low)
            self.plot_widget.addItem(line)
            self.plot_widget.addItem(tick)
            self.plot_widget.addItem(text)
            self.peak_lines.append(line)
            self.peak_tick_items.append(tick)
            self.peak_texts.append(text)
            detected_spots.append({
                "pos": (
                    center,
                    (detected_tick_low + detected_tick_high) / 2.0,
                ),
                "data": row,
            })
            small_plot = pg.PlotWidget()
            small_plot.setFixedSize(180, 180)
            small_plot.setBackground('w')
            small_plot.setTitle(f"Peak #{i + 1}", color="k", size="11pt")
            small_plot.plot(p_data["x_fit"], p_data["y_data"], pen=None, symbol='o', symbolSize=3, symbolBrush='b')
            small_plot.plot(p_data["x_curve"], p_data["y_curve"], pen=pg.mkPen('r', width=2))
            fitted_center_line = pg.InfiniteLine(
                pos=center,
                angle=90,
                pen=pg.mkPen(
                    "#555555", width=1.5, style=Qt.PenStyle.DashLine
                ),
            )
            small_plot.addItem(fitted_center_line)
            small_plot.scene().sigMouseClicked.connect(
                lambda _event, r=row: self.select_measured_peak(r)
            )
            self.row_widgets[row]["plot"] = small_plot
            self.bottom_layout.addWidget(small_plot)
        self.bottom_layout.addStretch()
        self.detected_select_scatter.setData(detected_spots)

        # Preserve confirmed assignments when only the peak threshold was changed.
        for old_pixel, assignment in previous:
            if not self.row_widgets:
                break
            distances = [
                abs(row_data["px"] - old_pixel) for row_data in self.row_widgets
            ]
            closest = int(np.argmin(distances))
            if distances[closest] <= 2.0 and closest not in self.assignments:
                self.assignments[closest] = assignment
                self.row_widgets[closest]["check"].setChecked(True)
        self._refresh_calibration_preview()
        self._refresh_peak_plot_styles()
        self.update_reference_overlay()

    def _laser_wavelength(self):
        main_window = self.parent()
        if main_window and hasattr(main_window, "spin_exc_wl"):
            return float(main_window.spin_exc_wl.value())
        return 532.0

    def _display_reference_value(self, wavelength_nm):
        if self.radio_unit_raman.isChecked():
            return self.nm_to_raman(wavelength_nm, self._laser_wavelength())
        return wavelength_nm

    def create_value_widget_for_row(self, row):
        val_widget = QComboBox()
        val_widget.setEditable(True)
        val_widget.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = val_widget.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        assigned = self.assignments.get(row)
        lines = self.active_reference_lines()
        if assigned and assigned.get("line_id"):
            assigned_line = self.reference_lines_by_id.get(assigned["line_id"])
            if assigned_line is not None and assigned_line not in lines:
                lines.append(assigned_line)
                lines.sort(key=lambda line: line.wavelength_nm)
        for line in lines:
            value = self._display_reference_value(line.wavelength_nm)
            val_widget.addItem(
                f"{value:.5f}  —  {line.species}",
                line.line_id,
            )
        val_widget.setCurrentIndex(-1)
        val_widget.setPlaceholderText("Select a line or type a value")
        if assigned:
            line_id = assigned.get("line_id")
            index = val_widget.findData(line_id) if line_id else -1
            if index >= 0:
                val_widget.setCurrentIndex(index)
            else:
                val_widget.setEditText(f"{assigned['value']:.5f}")
        val_widget.currentIndexChanged.connect(
            lambda _index, r=row: self.on_reference_combo_changed(r)
        )
        if val_widget.lineEdit() is not None:
            val_widget.lineEdit().editingFinished.connect(
                lambda r=row: self.on_reference_combo_changed(r)
            )
        self.table.setCellWidget(row, 2, val_widget)
        if row < len(self.row_widgets):
            self.row_widgets[row]["input"] = val_widget

    def on_reference_combo_changed(self, row):
        if row >= len(self.row_widgets):
            return
        combo = self.row_widgets[row].get("input")
        if combo is None:
            return
        line_id = combo.currentData()
        line = self.reference_lines_by_id.get(line_id)
        if line is not None:
            other_row = self._line_assigned_to_other_row(line.line_id, row)
            if other_row is not None:
                QMessageBox.warning(
                    self,
                    "Duplicate reference line",
                    f"{line.species} {line.wavelength_nm:.5f} nm is already "
                    f"assigned to peak #{other_row + 1}.",
                )
                self.create_value_widget_for_row(row)
                return
            value = self._display_reference_value(line.wavelength_nm)
            self.assignments[row] = {
                "line_id": line.line_id,
                "wavelength_nm": line.wavelength_nm,
                "value": value,
                "species": line.species,
                "locked": True,
            }
        else:
            text = combo.currentText().split("—", 1)[0].strip()
            try:
                value = float(text)
            except ValueError:
                return
            wavelength = (
                value
                if self.radio_unit_wl.isChecked()
                else self._raman_to_nm(value, self._laser_wavelength())
            )
            self.assignments[row] = {
                "line_id": None,
                "wavelength_nm": wavelength,
                "value": value,
                "species": "Custom",
                "locked": True,
            }
        self._update_assignment_row(row)
        self._refresh_calibration_preview()
        self.update_reference_overlay()

    @staticmethod
    def _raman_to_nm(shift_cm, laser_wl):
        denominator = 1e7 / laser_wl - shift_cm
        return 1e7 / denominator if denominator != 0 else np.nan

    def on_use_toggled(self, state, row):
        if state == Qt.CheckState.Checked:
            self.create_value_widget_for_row(row)
        else:
            self.table.removeCellWidget(row, 2)
            self.assignments.pop(row, None)
            if row < len(self.row_widgets):
                self.row_widgets[row]["input"] = None
            self._update_assignment_row(row)
            self._refresh_calibration_preview()
            self.update_reference_overlay()
        self._refresh_peak_plot_styles()

    def update_table_value_widgets(self):
        for row in range(self.table.rowCount()):
            chk_widget = self.table.cellWidget(row, 1)
            if chk_widget:
                chk = chk_widget.layout().itemAt(0).widget()
                if chk.isChecked():
                    assignment = self.assignments.get(row)
                    if assignment:
                        assignment["value"] = self._display_reference_value(
                            assignment["wavelength_nm"]
                        )
                    self.create_value_widget_for_row(row)
                    self._update_assignment_row(row)
        self._refresh_calibration_preview()
        self.update_reference_overlay()

    def _update_assignment_row(self, row):
        assignment = self.assignments.get(row)
        species_item = self.table.item(row, 3)
        status_item = self.table.item(row, 4)
        if species_item is None or status_item is None:
            return
        if assignment is None:
            species_item.setText("")
            status_item.setText("Unassigned")
        else:
            species_item.setText(assignment.get("species", ""))
            status_item.setText(
                "Locked" if assignment.get("locked", False) else "Suggested"
            )

    def on_table_peak_selected(self, row, _column):
        self.select_measured_peak(row)

    def _detected_peak_tooltip(self, *, x, y, data):
        try:
            row = int(data)
            center = self.row_widgets[row]["px"]
        except (IndexError, KeyError, TypeError, ValueError):
            return "Detected peak"
        return f"Detected peak #{row + 1}\nFitted center: {center:.3f} px"

    def _reference_line_tooltip(self, *, x, y, data):
        line = self.reference_lines_by_id.get(data)
        if line is None:
            return "Literature line"
        return f"{line.species} {line.wavelength_nm:.5f} nm"

    def on_measured_peak_clicked(self, _scatter, points, _event=None):
        if points:
            self.select_measured_peak(int(points[0].data()))

    def select_measured_peak(self, row):
        if not 0 <= row < len(self.row_widgets):
            return
        self.selected_peak_row = row
        self.table.selectRow(row)
        self.lbl_assignment_help.setText(
            f"Peak #{row + 1} selected. Click a literature marker to assign it."
        )
        self._refresh_peak_plot_styles()

    def clear_peak_selection(self):
        self.selected_peak_row = None
        self.table.clearSelection()
        self.lbl_assignment_help.setText(
            "Select a detected tick, fit plot, or table row; then click a "
            "literature tick."
        )
        self._refresh_peak_plot_styles()

    def clear_selected_assignment(self):
        row = self.selected_peak_row
        if row is None or not 0 <= row < len(self.row_widgets):
            return
        checkbox = self.row_widgets[row]["check"]
        if checkbox.isChecked():
            checkbox.setChecked(False)
        else:
            self.assignments.pop(row, None)
            self._update_assignment_row(row)
            self._refresh_calibration_preview()
            self.update_reference_overlay()
            self._refresh_peak_plot_styles()
        self.lbl_assignment_help.setText(f"Assignment cleared for peak #{row + 1}.")

    def _refresh_peak_plot_styles(self):
        if self.current_spectrum is None:
            return
        for index, row_data in enumerate(self.row_widgets):
            is_used = row_data["check"].isChecked()
            if index < len(self.peak_lines):
                self.peak_lines[index].setVisible(is_used)
            selected = index == self.selected_peak_row
            if index < len(self.peak_tick_items):
                self.peak_tick_items[index].setPen(
                    pg.mkPen(
                        "#FFB300" if selected else "#EF6C00",
                        width=5 if selected else 3,
                    )
                )
            if index < len(self.peak_texts):
                self.peak_texts[index].setColor(
                    "#FFB300" if selected else "#EF6C00"
                )
            small_plot = row_data.get("plot")
            if small_plot is not None:
                small_plot.setStyleSheet(
                    "border: 2px solid #FFB300;"
                    if selected else
                    "border: 2px solid transparent;"
                )
        self.btn_clear_assignment.setEnabled(
            self.selected_peak_row is not None
            and self.selected_peak_row in self.assignments
        )

    def on_reference_line_clicked(self, _scatter, points, event=None):
        if not points:
            return
        if self.selected_peak_row is None:
            self.lbl_assignment_help.setText(
                "Select a measured peak before selecting a literature line."
            )
            return
        lines = []
        seen_ids = set()
        for point in points:
            line = self.reference_lines_by_id.get(point.data())
            if line is not None and line.line_id not in seen_ids:
                lines.append(line)
                seen_ids.add(line.line_id)
        if not lines:
            return
        if len(lines) == 1:
            self.assign_reference_line(self.selected_peak_row, lines[0])
            return

        self.reference_candidate_menu.clear()
        title = self.reference_candidate_menu.addAction(
            f"Select line for peak #{self.selected_peak_row + 1}"
        )
        title.setEnabled(False)
        self.reference_candidate_menu.addSeparator()
        selected_row = self.selected_peak_row
        for line in sorted(lines, key=lambda item: item.wavelength_nm):
            action = self.reference_candidate_menu.addAction(
                f"{line.species}  {line.wavelength_nm:.5f} nm"
            )
            action.triggered.connect(
                lambda _checked=False, row=selected_row, selected=line:
                self.assign_reference_line(row, selected)
            )
        if event is not None and hasattr(event, "screenPos"):
            menu_position = event.screenPos().toPoint()
        else:
            menu_position = self.mapToGlobal(self.rect().center())
        self.reference_candidate_menu.popup(menu_position)

    def _line_assigned_to_other_row(self, line_id, row):
        for other_row, assignment in self.assignments.items():
            if other_row != row and assignment.get("line_id") == line_id:
                return other_row
        return None

    def assign_reference_line(self, row, line):
        other_row = self._line_assigned_to_other_row(line.line_id, row)
        if other_row is not None:
            self.lbl_assignment_help.setText(
                f"{line.species} {line.wavelength_nm:.5f} nm is already assigned "
                f"to peak #{other_row + 1}."
            )
            return
        value = self._display_reference_value(line.wavelength_nm)
        self.assignments[row] = {
            "line_id": line.line_id,
            "wavelength_nm": line.wavelength_nm,
            "value": value,
            "species": line.species,
            "locked": True,
        }
        checkbox = self.row_widgets[row]["check"]
        if not checkbox.isChecked():
            checkbox.setChecked(True)
        else:
            self.create_value_widget_for_row(row)
        self._update_assignment_row(row)
        self._refresh_calibration_preview()
        self.lbl_assignment_help.setText(
            f"Peak #{row + 1} → {line.species} {value:.5f}"
        )
        self.update_reference_overlay()
        self.selected_peak_row = None
        self.table.clearSelection()
        self._refresh_peak_plot_styles()

    def on_active_standards_changed(self, _item):
        # Rebuild the choices, but assignments (including lines from a now-hidden
        # standard) remain pinned and continue to participate in calibration.
        self.match_candidates = []
        self.combo_match_candidate.clear()
        self.btn_apply_candidate.setEnabled(False)
        for row, row_data in enumerate(self.row_widgets):
            if row_data["check"].isChecked():
                self.create_value_widget_for_row(row)
                self._update_assignment_row(row)
        self.update_reference_overlay()

    def find_assignment_candidates(self):
        lines = self.active_reference_lines()
        known_ids = {line.line_id for line in lines}
        for assignment in self.assignments.values():
            line = self.reference_lines_by_id.get(assignment.get("line_id"))
            if line is not None and line.line_id not in known_ids:
                lines.append(line)
                known_ids.add(line.line_id)
        lines.sort(key=lambda line: line.wavelength_nm)
        if len(self.row_widgets) < 2:
            QMessageBox.warning(self, "Automatic matching", "Find at least two measured peaks first.")
            return
        if len(lines) < 2:
            QMessageBox.warning(self, "Automatic matching", "Select at least one emission standard.")
            return

        # Limit only the hypothesis generator, not the displayed/assignable peaks.
        # Strong peaks plus every locked peak are retained, avoiding combinatorial
        # growth for noisy spectra with many weak detections.
        all_rows = list(range(len(self.row_widgets)))
        if len(all_rows) > 12:
            strengths = []
            for row in all_rows:
                pixel = self.row_widgets[row]["px"]
                index = int(np.clip(round(pixel), 0, len(self.current_spectrum) - 1))
                strengths.append((float(self.current_spectrum[index]), row))
            chosen = {row for _, row in sorted(strengths, reverse=True)[:12]}
            chosen.update(self.assignments)
            self.match_peak_rows = sorted(chosen)
        else:
            self.match_peak_rows = all_rows

        pixels = [self.row_widgets[row]["px"] for row in self.match_peak_rows]
        local_index = {row: index for index, row in enumerate(self.match_peak_rows)}
        locked = {
            local_index[row]: assignment["line_id"]
            for row, assignment in self.assignments.items()
            if row in local_index and assignment.get("line_id")
        }
        self.match_candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=self._center_wavelength_nm(),
            detector_midpoint_px=(len(self.current_spectrum) - 1) / 2.0,
            locked_assignments=locked,
            max_candidates=5,
            allow_reversed=True,
        )
        if self.initial_wavelength_axis is not None:
            seeded = match_from_seed_axis(
                pixels, lines, self.initial_wavelength_axis
            )
            if seeded is not None:
                duplicate = any(
                    candidate.assignments == seeded.assignments
                    for candidate in self.match_candidates
                )
                if not duplicate:
                    self.match_candidates.insert(0, seeded)
                    self.match_candidates = self.match_candidates[:5]
        self.combo_match_candidate.clear()
        for index, candidate in enumerate(self.match_candidates):
            center_text = (
                f", centre Δ {candidate.center_error_nm:.2f} nm"
                if candidate.center_error_nm is not None else ""
            )
            self.combo_match_candidate.addItem(
                f"Candidate {index + 1}: {candidate.matched_count} lines, "
                f"RMS {candidate.rms_nm:.4f} nm{center_text}"
            )
        self.btn_apply_candidate.setEnabled(bool(self.match_candidates))
        if self.match_candidates:
            self.lbl_assignment_help.setText(
                "Automatic candidates found. Review a candidate and click Apply candidate."
            )
            self.update_reference_overlay()
        else:
            self.lbl_assignment_help.setText(
                "No unambiguous pattern was found. Assign one peak manually and retry."
            )

    def apply_selected_candidate(self):
        index = self.combo_match_candidate.currentIndex()
        if not 0 <= index < len(self.match_candidates):
            return
        candidate = self.match_candidates[index]
        for local_peak, line_id in candidate.assignments:
            row = self.match_peak_rows[local_peak]
            existing = self.assignments.get(row)
            if existing and existing.get("locked"):
                continue
            line = self.reference_lines_by_id.get(line_id)
            if line is not None:
                self.assignments[row] = {
                    "line_id": line.line_id,
                    "wavelength_nm": line.wavelength_nm,
                    "value": self._display_reference_value(line.wavelength_nm),
                    "species": line.species,
                    "locked": True,
                }
                if not self.row_widgets[row]["check"].isChecked():
                    self.row_widgets[row]["check"].setChecked(True)
                else:
                    self.create_value_widget_for_row(row)
                self._update_assignment_row(row)
        self._refresh_calibration_preview()
        self.update_reference_overlay()
        self.lbl_assignment_help.setText(
            f"Candidate {index + 1} applied. Individual assignments remain editable."
        )

    def _refresh_calibration_preview(self):
        if len(self.assignments) < 2:
            self.calib_coeffs = None
            self.btn_save_apply.setEnabled(False)
            for row in range(len(self.row_widgets)):
                self._update_assignment_row(row)
            return
        self.calibrate()
        if self.calib_coeffs is None:
            return
        c0, c1, c2 = self.calib_coeffs
        unit = "cm⁻¹" if self.radio_unit_raman.isChecked() else "nm"
        for row, assignment in self.assignments.items():
            pixel = self.row_widgets[row]["px"]
            predicted = c0 + c1 * pixel + c2 * pixel**2
            residual = predicted - assignment["value"]
            status_item = self.table.item(row, 4)
            if status_item is not None:
                status_item.setText(f"Locked, Δ {residual:+.4g} {unit}")

    def _assignment_wavelength_coefficients(self):
        rows = sorted(self.assignments)
        if len(rows) < 2:
            return None
        pixels = [self.row_widgets[row]["px"] for row in rows]
        wavelengths = [self.assignments[row]["wavelength_nm"] for row in rows]
        result = self.calib_core.calibrate(pixels, wavelengths)
        if result is None:
            return None
        return result["c0"], result["c1"], result["c2"]

    def _projection_axis_nm(self):
        coefficients = self._assignment_wavelength_coefficients()
        spectrum_length = 0 if self.current_spectrum is None else len(self.current_spectrum)
        pixels = np.arange(spectrum_length, dtype=float)
        if coefficients is not None:
            c0, c1, c2 = coefficients
            return c0 + c1 * pixels + c2 * pixels**2
        if self.initial_wavelength_axis is not None:
            return self.initial_wavelength_axis
        index = self.combo_match_candidate.currentIndex()
        if 0 <= index < len(self.match_candidates):
            c0, c1, c2 = self.match_candidates[index].coefficients
            return c0 + c1 * pixels + c2 * pixels**2
        return None

    def update_reference_overlay(self):
        for item in self.reference_overlay_items:
            self.plot_widget.removeItem(item)
        self.reference_overlay_items.clear()
        self.reference_select_scatter.setData([])
        if self.current_spectrum is None or len(self.current_spectrum) == 0:
            return
        wavelength_axis = self._projection_axis_nm()
        if wavelength_axis is None or len(wavelength_axis) != len(self.current_spectrum):
            return
        wavelength_axis = np.asarray(wavelength_axis, dtype=float)
        if not np.all(np.isfinite(wavelength_axis)):
            return
        differences = np.diff(wavelength_axis)
        if not (np.all(differences > 0) or np.all(differences < 0)):
            return
        increasing = differences[0] > 0
        interpolation_axis = wavelength_axis if increasing else wavelength_axis[::-1]
        interpolation_pixels = (
            np.arange(len(wavelength_axis), dtype=float)
            if increasing else np.arange(len(wavelength_axis) - 1, -1, -1, dtype=float)
        )
        low, high = float(np.min(wavelength_axis)), float(np.max(wavelength_axis))
        assigned_ids = {
            assignment.get("line_id")
            for assignment in self.assignments.values()
            if assignment.get("line_id")
        }
        visible_lines = {
            line.line_id: line for line in self.active_reference_lines()
            if low <= line.wavelength_nm <= high
        }
        for line_id in assigned_ids:
            line = self.reference_lines_by_id.get(line_id)
            if line is not None:
                visible_lines[line_id] = line

        literature_tick_low, literature_tick_high = self._tick_levels()["literature"]
        spots = []
        for line in sorted(visible_lines.values(), key=lambda item: item.wavelength_nm):
            if not low <= line.wavelength_nm <= high:
                continue
            pixel = float(np.interp(
                line.wavelength_nm, interpolation_axis, interpolation_pixels
            ))
            assigned = line.line_id in assigned_ids
            color = "#0D47A1" if assigned else "#1565C0"
            marker = pg.PlotDataItem(
                [pixel, pixel],
                [literature_tick_low, literature_tick_high],
                pen=pg.mkPen(color, width=4 if assigned else 3),
            )
            self.plot_widget.addItem(marker)
            self.reference_overlay_items.append(marker)
            spots.append({
                "pos": (pixel, (literature_tick_low + literature_tick_high) / 2.0),
                "data": line.line_id,
            })
        self.reference_select_scatter.setData(spots)

    def calibrate(self):
        pixels, ref_values = [], []
        is_raman = self.radio_unit_raman.isChecked()

        for row, row_data in enumerate(self.row_widgets):
            assignment = self.assignments.get(row)
            if row_data["check"].isChecked() and assignment is not None:
                pixels.append(row_data["px"])
                ref_values.append(assignment["value"])
        if len(pixels) < 2:
            self.lbl_calib_result.setText("Please check at least 2 peaks.")
            self.btn_save_apply.setEnabled(False)
            return
        coeffs = self.calib_core.calibrate(pixels, ref_values)
        if coeffs:
            self.calib_coeffs = (coeffs["c0"], coeffs["c1"], coeffs["c2"])
            unit_str = "cm⁻¹" if is_raman else "nm"
            self.lbl_calib_result.setText(
                f"y = c0 + c1*x + c2*x^2  (pixel → {unit_str})\n"
                f"c0 = {coeffs['c0']:.6e}\nc1 = {coeffs['c1']:.6e}\nc2 = {coeffs['c2']:.6e}"
            )
            self.btn_save_apply.setEnabled(True)

    def _restore_main_window_settings(self):
        main_window = self.parent()
        if not main_window or not self.camera_thread:
            return
        if hasattr(main_window, 'spin_acq_time'):
            self.camera_thread.update_exposure(main_window.spin_acq_time.value())
        if hasattr(main_window, 'current_accum_count'):
            main_window.current_accum_count = 0
        if hasattr(main_window, 'accumulated_data'):
            main_window.accumulated_data = None
        if hasattr(main_window, 'accum_frames'):
            main_window.accum_frames = None

    def _disconnect_camera_thread(self):
        """Stop any in-flight acquisition started by this dialog and detach our
        data_ready slot so the (possibly not-yet-garbage-collected) dialog can't
        keep reacting to frames after it has closed."""
        if not self.camera_thread:
            return
        if self.is_acquiring:
            self.camera_thread.stop_measuring()
            self.is_acquiring = False
        try:
            self.camera_thread.data_ready.disconnect(self.on_data_ready)
        except TypeError:
            pass  # already disconnected

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.selected_peak_row is not None:
            self.clear_peak_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def done(self, result):
        self._disconnect_camera_thread()
        self._restore_main_window_settings()
        super().done(result)

    def closeEvent(self, event):
        super().closeEvent(event)

    def save_and_apply(self):
        if self.calib_coeffs is None: return
        main_window = self.parent()
        if main_window is None: return
        is_raman_unit = self.radio_unit_raman.isChecked()
        calibration_unit = "Wavelength" if not is_raman_unit else "Raman shift"
        try:
            calib_laser_wl = (
                main_window.spin_exc_wl.value() if is_raman_unit else None
            )
            record = main_window.register_current_configuration(
                self.calib_coeffs,
                calibration_unit=calibration_unit,
                excitation_wavelength_nm=calib_laser_wl,
            )
            label = format_configuration_label(record)
            main_window.apply_calibration(
                self.calib_coeffs,
                label,
                calib_unit=calibration_unit,
                calib_laser_wl=calib_laser_wl,
                axis_source="emission_standard_polynomial",
                configuration_id=record["configuration_id"],
                slot_id=record["slot_id"],
            )
            main_window.status_label.setText(
                f"Configuration saved and active: {label}"
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Configuration Error", str(e))
