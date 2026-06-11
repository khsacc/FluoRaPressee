import json
import os
from datetime import datetime
import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTableWidget, QTableWidgetItem,
                             QCheckBox, QComboBox, QHeaderView, QWidget,
                             QAbstractSpinBox, QDoubleSpinBox, QSplitter,
                             QScrollArea, QRadioButton, QFileDialog, QMessageBox, QSlider,
                             QListView, QButtonGroup)
from PyQt5.QtCore import Qt
import pyqtgraph as pg

from src.calibration import CalibrationCore
from src.calibration_helper import ReferenceHelperWindow

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
            QPushButton { background-color: #E0E0E0; color: #000000; border: 1px solid #999; border-radius: 3px; }
            QPushButton:hover { background-color: #D0D0D0; }
            QComboBox { background-color: #FFFFFF; color: #000000; border: 1px solid #999; }
            QComboBox QAbstractItemView { background-color: #FFFFFF; color: #000000; selection-background-color: #2196F3; selection-color: #FFFFFF; }
            QDoubleSpinBox { background-color: #FFFFFF; color: #000000; border: 1px solid #999; }
            QSpinBox { background-color: #FFFFFF; color: #000000; border: 1px solid #999; }
        """)
        
        self.camera_thread = camera_thread
        self.calib_core = CalibrationCore()
        
        self.current_spectrum = None
        self.peak_lines = []
        self.peak_texts = []
        self.is_acquiring = False
        
        self.calib_coeffs = None 
        self.row_widgets = []
        
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
        if wl_nm == 0: return 0.0
        return (1e7 / laser_wl) - (1e7 / wl_nm)

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
        self.plot_scatter = self.plot_widget.plot(pen=None, symbol='o', symbolSize=3, symbolBrush='b')
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
        slider_label = QLabel("Threshold:")
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_threshold.setRange(10, 100) 
        self.slider_threshold.setValue(75)
        slider_layout.addWidget(slider_label)
        slider_layout.addWidget(self.slider_threshold)
        
        find_peaks_layout.addWidget(self.btn_find_peaks)
        find_peaks_layout.addLayout(slider_layout)

        helper_layout = QHBoxLayout()
        helper_layout.addWidget(QLabel("Reference data:"))
        
        # --- 修正箇所: QComboBox の表示改善 ---
        self.combo_reference = QComboBox()
        # 1. ドロップダウンリスト内でテキストを折り返す設定
        view = QListView()
        view.setWordWrap(True)
        self.combo_reference.setView(view)
        # 2. ボックス自体の幅を内容（選択テキスト）に合わせて自動調整
        self.combo_reference.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_reference.setMinimumWidth(150)
        # ------------------------------------
        
        helper_layout.addWidget(self.combo_reference)
        self.btn_show_helper = QPushButton("Show")
        self.btn_show_helper.setAutoDefault(False)
        self.btn_show_helper.setDefault(False)
        self.btn_show_helper.clicked.connect(self.show_reference_helper)
        helper_layout.addWidget(self.btn_show_helper)
        
        self.load_reference_files()

        neon_layout = QHBoxLayout()
        neon_layout.addWidget(QLabel("Import neon peaks around 694 nm:"))
        self.radio_neon_yes = QRadioButton("Yes")
        self.radio_neon_no = QRadioButton("No")
        self.radio_neon_yes.setChecked(True)
        self.radio_neon_yes.toggled.connect(self.update_table_value_widgets)
        self.radio_neon_no.toggled.connect(self.update_table_value_widgets)
        neon_layout.addWidget(self.radio_neon_yes)
        neon_layout.addWidget(self.radio_neon_no)

        self.unit_button_group = QButtonGroup(self)
        self.unit_button_group.addButton(self.radio_unit_wl)
        self.unit_button_group.addButton(self.radio_unit_raman)

        self.neon_button_group = QButtonGroup(self)
        self.neon_button_group.addButton(self.radio_neon_yes)
        self.neon_button_group.addButton(self.radio_neon_no)
        
        self.table = QTableWidget(0, 3)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        
        self.btn_calibrate = QPushButton("Calibrate")
        self.btn_calibrate.setAutoDefault(False)
        self.btn_calibrate.setDefault(False)
        self.btn_calibrate.clicked.connect(self.calibrate)
        self.btn_calibrate.setStyleSheet("font-weight: bold; color: white; background-color: #2196F3; padding: 8px; border: none;")
        
        self.lbl_calib_result = QLabel("y = c0 + c1*x + c2*x^2\nc0 = ...\nc1 = ...\nc2 = ...")
        self.lbl_calib_result.setStyleSheet("font-family: Consolas; background-color: #EEEEEE; padding: 10px; border: 1px solid #CCC; color: #000000;")
        
        self.btn_save_apply = QPushButton("Save and apply")
        self.btn_save_apply.setAutoDefault(False)
        self.btn_save_apply.setDefault(False)
        self.btn_save_apply.setEnabled(False)
        self.btn_save_apply.clicked.connect(self.save_and_apply)
        
        controls_layout.addWidget(self.btn_acquire)
        controls_layout.addLayout(acq_time_layout)
        controls_layout.addLayout(unit_layout) 
        controls_layout.addLayout(find_peaks_layout)
        controls_layout.addLayout(helper_layout)
        controls_layout.addLayout(neon_layout)
        controls_layout.addWidget(self.table)
        controls_layout.addWidget(self.btn_calibrate)
        controls_layout.addWidget(self.lbl_calib_result)
        controls_layout.addWidget(self.btn_save_apply)
        
        main_layout.addLayout(controls_layout, stretch=1)

    def update_ui_units(self):
        self.update_table_header()
        self.load_reference_files()

    def load_reference_files(self):
        subdir = "calibrationHelper"
        if not os.path.exists(subdir):
            return
            
        current_idx = self.combo_reference.currentIndex()
        self.combo_reference.clear()
        
        is_raman = self.radio_unit_raman.isChecked()
        laser_wl = 532.0
        main_window = self.parent()
        if main_window and hasattr(main_window, 'spin_exc_wl'):
            laser_wl = main_window.spin_exc_wl.value()

        file_list = []
        for filename in os.listdir(subdir):
            if filename.endswith(".json"):
                path = os.path.join(subdir, filename)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        material = data.get("material", "Unknown")
                        approx_nm_str = data.get("approximate_range", "0")
                        approx_nm = float(approx_nm_str) if approx_nm_str.replace('.','',1).isdigit() else 0.0
                        
                        if is_raman:
                            approx_raman = self.nm_to_raman(approx_nm, laser_wl)
                            label = f"{material} around {approx_raman:.1f} cm-1"
                        else:
                            label = f"{material} around {approx_nm_str} nm"
                            
                        file_list.append({
                            "label": label,
                            "range_nm": approx_nm,
                            "data": data
                        })
                except Exception as e:
                    print(f"Error loading {filename}: {e}")

        file_list.sort(key=lambda x: x["range_nm"], reverse=True)

        for item in file_list:
            self.combo_reference.addItem(item["label"], item["data"])
        
        if current_idx >= 0 and current_idx < self.combo_reference.count():
            self.combo_reference.setCurrentIndex(current_idx)

    def show_reference_helper(self):
        json_data = self.combo_reference.currentData()
        if not json_data:
            QMessageBox.warning(self, "Warning", "No guidance data selected.")
            return

        is_raman = self.radio_unit_raman.isChecked()
        laser_wl = 532.0
        main_window = self.parent()
        if main_window and hasattr(main_window, 'spin_exc_wl'):
            laser_wl = main_window.spin_exc_wl.value()

        self.guide_window = ReferenceHelperWindow(json_data, is_raman, laser_wl, self)
        self.guide_window.show()

    def update_table_header(self):
        unit_str = "nm" if self.radio_unit_wl.isChecked() else "cm⁻¹"
        self.table.setHorizontalHeaderLabels(["Peak pos. (px)", "Use", f"Value ({unit_str})"])

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
            self.camera_thread.stop_measuring()
            self.is_acquiring = False
            self.btn_acquire.setEnabled(True)
            self.btn_acquire.setText("Acquire a spectrum")
            self.find_peaks()
            
    def find_peaks(self):
        if self.current_spectrum is None:
            return
        threshold_mult = self.slider_threshold.value() / 10.0
        fitted_peaks = self.calib_core.find_and_fit_peaks(self.current_spectrum, prominence_multiplier=threshold_mult)
        self.table.setRowCount(0)
        self.row_widgets.clear()
        for item in self.peak_lines + self.peak_texts:
            self.plot_widget.removeItem(item)
        self.peak_lines.clear()
        self.peak_texts.clear()
        while self.bottom_layout.count():
            child = self.bottom_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        max_y = np.max(self.current_spectrum)
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
            chk.stateChanged.connect(lambda state, r=row: self.on_use_toggled(state, r))
            line = pg.InfiniteLine(pos=center, angle=90, pen=pg.mkPen('r', style=Qt.PenStyle.DashLine))
            text = pg.TextItem(f"#{i+1}", color='r', anchor=(0, 1))
            text.setPos(center, max_y * 0.95)
            self.plot_widget.addItem(line)
            self.plot_widget.addItem(text)
            self.peak_lines.append(line)
            self.peak_texts.append(text)
            small_plot = pg.PlotWidget()
            small_plot.setFixedSize(180, 180)
            small_plot.setBackground('w')
            small_plot.plot(p_data["x_fit"], p_data["y_data"], pen=None, symbol='o', symbolSize=3, symbolBrush='b')
            small_plot.plot(p_data["x_curve"], p_data["y_curve"], pen=pg.mkPen('r', width=2))
            self.bottom_layout.addWidget(small_plot)
        self.bottom_layout.addStretch()

    def create_value_widget_for_row(self, row):
        if self.radio_neon_yes.isChecked():
            val_widget = QComboBox()
            if self.radio_unit_raman.isChecked():
                laser_wl = 532.0
                mw = self.parent()
                if mw and hasattr(mw, 'spin_exc_wl'):
                    laser_wl = mw.spin_exc_wl.value()
                neon_nm = [692.94673, 702.40504, 703.24131]
                items = [f"{1e7/laser_wl - 1e7/nm:.2f}" for nm in neon_nm]
                val_widget.addItems(items)
            else:
                val_widget.addItems(["692.94673", "702.40504", "703.24131"])
        else:
            val_widget = CustomDoubleSpinBox()
            val_widget.setRange(-10000, 20000)
            val_widget.setDecimals(5)
        self.table.setCellWidget(row, 2, val_widget)
        if row < len(self.row_widgets):
            self.row_widgets[row]["input"] = val_widget

    def on_use_toggled(self, state, row):
        if state == Qt.CheckState.Checked:
            self.create_value_widget_for_row(row)
        else:
            self.table.removeCellWidget(row, 2)
            if row < len(self.row_widgets): self.row_widgets[row]["input"] = None

    def update_table_value_widgets(self):
        for row in range(self.table.rowCount()):
            chk_widget = self.table.cellWidget(row, 1)
            if chk_widget:
                chk = chk_widget.layout().itemAt(0).widget()
                if chk.isChecked(): self.create_value_widget_for_row(row)

    def calibrate(self):
        pixels, ref_values = [], []
        is_raman = self.radio_unit_raman.isChecked()

        for row_data in self.row_widgets:
            if row_data["check"].isChecked() and row_data["input"] is not None:
                px = row_data["px"]
                input_widget = row_data["input"]
                val = float(input_widget.currentText()) if isinstance(input_widget, QComboBox) else input_widget.value()
                pixels.append(px)
                ref_values.append(val)
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

    def done(self, result):
        self._restore_main_window_settings()
        super().done(result)

    def closeEvent(self, event):
        super().closeEvent(event)

    def save_and_apply(self):
        if self.calib_coeffs is None: return
        main_window = self.parent()
        if main_window is None: return
        grating = main_window.combo_grating.currentText() if hasattr(main_window, 'combo_grating') else "Unknown"
        # Always save the physical center wavelength in nm, regardless of display mode
        center_wl = main_window.physical_center_wl if hasattr(main_window, 'physical_center_wl') else (
            main_window.spin_centre_wl.value() if hasattr(main_window, 'spin_centre_wl') else 0.0)
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        is_raman_unit = self.radio_unit_raman.isChecked()
        unit_sym = "nm" if not is_raman_unit else "cm-1"
        calibration_unit = "Wavelength" if not is_raman_unit else "Raman shift"
        if is_raman_unit:
            laser_wl = main_window.spin_exc_wl.value() if hasattr(main_window, 'spin_exc_wl') else 532.0
            center_display = self.nm_to_raman(center_wl, laser_wl)
        else:
            center_display = center_wl
        display_mode = "Raman shift" if (hasattr(main_window, 'radio_spec_mode_raman') and main_window.radio_spec_mode_raman.isChecked()) else "Wavelength"
        if main_window.radio_2d.isChecked():
            mode = "2D Image"
        else:
            mode = "1D Spectrum (Custom ROI)" if main_window.radio_1d_roi.isChecked() else "1D Spectrum (Full Range Binning)"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Config", f"config_{grating}_{center_display:.1f}{unit_sym}_{date_str}.json", "JSON (*.json)")
        if not file_path: return
        c0, c1, c2 = self.calib_coeffs
        data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "spectrometer_settings": {
                "grating_grooves_per_mm": grating,
                "center_wavelength_nm": center_wl,
                "calibration_unit": calibration_unit,
                "display_mode": display_mode,
                "excitation_wavelength_nm": main_window.spin_exc_wl.value() if hasattr(main_window, 'spin_exc_wl') else None,
            },
            "detector_settings": {
                "mode": mode,
                "roi_start": main_window.spin_vstart.value(),
                "roi_end": main_window.spin_vend.value()
            },
            "calibration_coefficients": {"c0": c0, "c1": c1, "c2": c2}
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            if hasattr(main_window, 'apply_calibration'):
                is_raman_calib = self.radio_unit_raman.isChecked()
                calib_laser_wl = (main_window.spin_exc_wl.value()
                                  if (is_raman_calib and hasattr(main_window, 'spin_exc_wl'))
                                  else None)
                main_window.apply_calibration(
                    self.calib_coeffs,
                    os.path.basename(file_path),
                    calib_unit="Raman shift" if is_raman_calib else "Wavelength",
                    calib_laser_wl=calib_laser_wl
                )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))