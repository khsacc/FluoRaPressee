import sys
import os
import json
import time
import csv
from datetime import datetime
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                             QHBoxLayout, QWidget, QLabel, QRadioButton, QGroupBox, 
                             QSpinBox, QDoubleSpinBox, QStackedWidget, QComboBox, 
                             QScrollArea, QFileDialog, QButtonGroup, QGridLayout,
                             QDialog, QTextEdit, QAbstractSpinBox, QInputDialog, QCheckBox, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg

# ---- 分割したモジュールのインポート ----
from src.camera import CameraThread
from src.spectrometer import SpectrometerController, SpectrometerMoveThread
from src.analysis import DataAnalyzer
from src.calibration_ui import CalibrationWindow
from src.pressureCalc import PressureCalculator
from src.pressureCalc_ui import PressureCalculatorWindow
# ----------------------------------------

class CustomSpinBox(QSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    def wheelEvent(self, event):
        event.ignore()

class CustomDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    def wheelEvent(self, event):
        event.ignore()

class CustomComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

class SpectrometerGUI(QMainWindow):
    def __init__(self, debug=False):
        super().__init__()
        self.debug = debug
        self.setWindowTitle("FluoraPressée: Spectrometer Live View" + (" [DEBUG MODE]" if self.debug else ""))
        self.resize(1400, 900)

        self.config = self.load_spectrometer_config()

        self.raw_1d_data = None 
        self.raw_2d_data = None
        self.latest_1d_data = None
        self.latest_2d_data = None
        
        self.calib_coeffs = None
        self.calib_file_name = "None"
        self.current_w_peak1 = None
        
        self.loaded_bg_data = None
        self.loaded_bg_metadata = None
        self.is_single_shot = False
        self._ignore_next_frames = False
        
        self.latest_fit_res = None
        self.latest_fit_func = None

        self.current_accum_count = 0
        self.accumulated_data = None

        self.seq_dir = ""
        self.is_sequential_running = False
        self.seq_count = 0
        self.current_skip_count = 0
        self.seq_start_time_dt = None
        self.seq_log_data = []
        self._seq_fit_failed = False
        self.seq_fitting_summary_path = None

        self.spec_ctrl = SpectrometerController(config=self.config, debug=self.debug)
        self.analyzer = DataAnalyzer()

        first_grating = self.config.get("grating", [{}])[0].get("grooves", 600)
        self.physical_grating = str(first_grating)
        self.physical_center_wl = 694.0

        self.pressure_window = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        plot_layout = QVBoxLayout()
        
        status_coord_layout = QHBoxLayout()
        self.status_label = QLabel("Initializing camera...")
        self.coord_label = QLabel("Cursor Position: --")
        self.coord_label.setStyleSheet("font-weight: bold; color: #0078D7; font-size: 14px;")
        status_coord_layout.addWidget(self.status_label)
        status_coord_layout.addStretch()
        status_coord_layout.addWidget(self.coord_label)
        plot_layout.addLayout(status_coord_layout)

        self.lbl_accum_status = QLabel("")
        self.lbl_accum_status.setStyleSheet("color: #E91E63; font-weight: bold; font-size: 14px;")
        self.lbl_accum_status.setVisible(False)
        plot_layout.addWidget(self.lbl_accum_status)

        self.plot_content_layout = QHBoxLayout()

        self.fitting_panel = QGroupBox("Fitting Results")
        self.fitting_panel.setFixedWidth(240)
        self.fitting_text = QTextEdit()
        self.fitting_text.setReadOnly(True)
        self.fitting_text.setStyleSheet("font-family: Consolas; font-size: 11px; border: none;")
        fit_p_layout = QVBoxLayout()
        fit_p_layout.addWidget(self.fitting_text)
        self.fitting_panel.setLayout(fit_p_layout)
        self.fitting_panel.setVisible(False)
        self.plot_content_layout.addWidget(self.fitting_panel)

        self.stacked_widget = QStackedWidget()
        
        self.plot_widget = pg.PlotWidget(title="1D Spectrum")
        self.plot_widget.setLabel('left', 'Intensity (Counts)')
        self.plot_widget.setLabel('bottom', 'Pixel')
        self.plot_widget.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        
        self.plot_scatter = self.plot_widget.plot(pen=None, symbol='o', symbolSize=4, symbolBrush='w')
        self.fit_curve = self.plot_widget.plot(pen=pg.mkPen('y', width=2))
        self.fit_curve_sub1 = self.plot_widget.plot(pen=pg.mkPen('y', width=1, style=Qt.PenStyle.DashLine))
        self.fit_curve_sub2 = self.plot_widget.plot(pen=pg.mkPen('y', width=1, style=Qt.PenStyle.DashLine))
        
        self.stacked_widget.addWidget(self.plot_widget) 

        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide() 
        self.image_view.ui.menuBtn.hide()
        self.stacked_widget.addWidget(self.image_view) 

        self.plot_content_layout.addWidget(self.stacked_widget)
        plot_layout.addLayout(self.plot_content_layout)
        
        plot_controls_layout = QHBoxLayout()
        self.chk_rescale_x = QCheckBox("Rescale X automatically")
        self.chk_rescale_y = QCheckBox("Rescale Y automatically")
        self.chk_rescale_x.setChecked(True)
        self.chk_rescale_y.setChecked(True)
        plot_controls_layout.addStretch()
        plot_controls_layout.addWidget(self.chk_rescale_x)
        plot_controls_layout.addWidget(self.chk_rescale_y)
        plot_layout.addLayout(plot_controls_layout)

        self.plot_widget.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.image_view.getView().scene().sigMouseMoved.connect(self.on_mouse_moved)

        main_layout.addLayout(plot_layout, stretch=3)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(400)
        
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)

        meas_group = QGroupBox("Measurement")
        meas_layout = QVBoxLayout()
        
        self.btn_single = QPushButton("Take single spectrum")
        self.btn_single.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        
        self.btn_commence = QPushButton("Commence Measurement")
        self.btn_commence.setEnabled(False)
        self.btn_commence.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.btn_terminate = QPushButton("Terminate Measurement")
        self.btn_terminate.setEnabled(False)
        self.btn_terminate.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        
        self.btn_save_data = QPushButton("Save data")
        self.btn_save_data.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
        
        self.chk_save_fitting = QCheckBox("Save fitting results")
        self.chk_save_fitting.setEnabled(False)
        
        meas_layout.addWidget(self.btn_single)
        meas_layout.addWidget(self.btn_commence)
        meas_layout.addWidget(self.btn_terminate)
        meas_layout.addWidget(self.btn_save_data)
        meas_layout.addWidget(self.chk_save_fitting)

        det_sub_group = QGroupBox("Detector Configurations")
        det_layout = QGridLayout()
        self.spin_acq_time = CustomDoubleSpinBox()
        self.spin_acq_time.setRange(0.001, 3600)
        self.spin_acq_time.setValue(0.1)
        self.spin_acq_time.setDecimals(3)
        
        self.spin_accumulate = CustomSpinBox()
        self.spin_accumulate.setRange(1, 99999)
        self.spin_accumulate.setValue(1)
        
        self.spin_cooler_temp = CustomSpinBox()
        self.spin_cooler_temp.setRange(-100, 20)
        self.spin_cooler_temp.setValue(-65)
        self.btn_read_temp = QPushButton("Read current temperature")
        self.label_current_temp = QLabel("-- °C")
        self.label_current_temp.setStyleSheet("font-weight: bold; color: #E91E63;")
        
        det_layout.addWidget(QLabel("Acquisition time (s):"), 0, 0)
        det_layout.addWidget(self.spin_acq_time, 0, 1)
        det_layout.addWidget(QLabel("Accumulations:"), 1, 0)
        det_layout.addWidget(self.spin_accumulate, 1, 1)
        det_layout.addWidget(QLabel("Cooler target temp (°C):"), 2, 0)
        det_layout.addWidget(self.spin_cooler_temp, 2, 1)
        det_layout.addWidget(self.btn_read_temp, 3, 0)
        det_layout.addWidget(self.label_current_temp, 3, 1)
        det_sub_group.setLayout(det_layout)
        meas_layout.addWidget(det_sub_group)

        self.seq_toggle_btn = QPushButton("▶ Sequential measurements")
        self.seq_toggle_btn.setCheckable(True)
        self.seq_toggle_btn.setStyleSheet("text-align: left; font-weight: bold; border: none; padding: 5px;")
        
        self.seq_content = QWidget()
        self.seq_content.setVisible(False)
        seq_layout = QGridLayout(self.seq_content)
        
        self.btn_choose_dir = QPushButton("Choose directory")
        self.lbl_seq_dir = QLabel("Dir: Not selected")
        self.lbl_seq_dir.setStyleSheet("color: #666; font-size: 11px;")
        
        skip_label_layout = QHBoxLayout()
        skip_label = QLabel("Skip frames:")
        self.link_how_skip_works = QLabel('<a href="#how" style="color: #2196F3; text-decoration: none;">how this works?</a>')
        self.link_how_skip_works.linkActivated.connect(self.show_skip_frames_info)
        skip_label_layout.addWidget(skip_label)
        skip_label_layout.addWidget(self.link_how_skip_works)
        skip_label_layout.addStretch()
        
        self.spin_skip_frames = CustomSpinBox()
        self.spin_skip_frames.setRange(0, 99999)
        self.spin_skip_frames.setValue(0)
        self.spin_max_num = CustomSpinBox()
        self.spin_max_num.setRange(1, 99999)
        self.spin_max_num.setValue(9999)
        
        self.lbl_seq_progress = QLabel("")
        self.lbl_seq_progress.setStyleSheet("color: #2196F3; font-weight: bold;")
        self.lbl_seq_progress.setVisible(False)
        
        self.btn_start_seq = QPushButton("Start Sequential")
        self.btn_start_seq.setEnabled(False)
        self.btn_start_seq.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.btn_stop_seq = QPushButton("Stop Sequential")
        self.btn_stop_seq.setEnabled(False)
        self.btn_stop_seq.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        
        seq_layout.addWidget(self.btn_choose_dir, 0, 0, 1, 2)
        seq_layout.addWidget(self.lbl_seq_dir, 1, 0, 1, 2)
        seq_layout.addLayout(skip_label_layout, 2, 0)
        seq_layout.addWidget(self.spin_skip_frames, 2, 1)
        seq_layout.addWidget(QLabel("Max. number:"), 3, 0)
        seq_layout.addWidget(self.spin_max_num, 3, 1)
        seq_layout.addWidget(self.lbl_seq_progress, 4, 0, 1, 2)
        seq_layout.addWidget(self.btn_start_seq, 5, 0)
        seq_layout.addWidget(self.btn_stop_seq, 5, 1)
        
        meas_layout.addWidget(self.seq_toggle_btn)
        meas_layout.addWidget(self.seq_content)

        meas_group.setLayout(meas_layout)
        controls_layout.addWidget(meas_group)

        spec_group = QGroupBox("Spectrometer Configurations")
        spec_layout = QGridLayout()

        self.btn_load_calib = QPushButton("Load previous configuration")
        self.btn_load_calib.setStyleSheet("""
            background-color: #673AB7; 
            color: white; 
            font-weight: bold; 
        """)
        self.lbl_notes_calib_loading = QLabel('Loading a configuration will change the grating, centre, ROI, and pixel-wavelength calibration.')
        self.lbl_notes_calib_loading.setStyleSheet("font-style: italic;")
        self.lbl_notes_calib_loading.setWordWrap(True) # テキストの折り返しを有効にしてレイアウト崩れを防ぐ
        
        self.lbl_loaded_calib = QLabel("Loaded: None")
        self.lbl_loaded_calib.setStyleSheet("color: #333; font-size: 12px; font-weight: bold; margin-bottom: 10px;")
        self.lbl_loaded_calib.setWordWrap(True)
        
        self.grating_list = [str(g.get("grooves")) for g in self.config.get("grating", [])]
        self.combo_grating = CustomComboBox()
        self.combo_grating.addItems(self.grating_list)
        
        spec_radio_layout = QHBoxLayout()
        self.radio_spec_mode_wl = QRadioButton("Wavelength")
        self.radio_spec_mode_raman = QRadioButton("Raman shift")
        self.radio_spec_mode_wl.setChecked(True)
        spec_radio_layout.addWidget(self.radio_spec_mode_wl)
        spec_radio_layout.addWidget(self.radio_spec_mode_raman)
        
        self.lbl_centre = QLabel("Centre (nm):")
        self.spin_centre_wl = CustomDoubleSpinBox()
        self.spin_centre_wl.setRange(-10000, 20000)
        self.spin_centre_wl.setValue(694.0)
        
        self.lbl_exc_wl = QLabel("Excitation wavelength (nm):")
        self.spin_exc_wl = CustomDoubleSpinBox()
        self.spin_exc_wl.setRange(0.01, 2000)
        self.spin_exc_wl.setValue(532.0)
        self.spin_exc_wl.setEnabled(False)
        
        self.btn_apply_spec = QPushButton("Apply")
        self.btn_apply_spec.setEnabled(False)
        self.btn_apply_spec.setStyleSheet("font-weight: bold; color: #2196F3;")
        
        self.btn_calib_neon = QPushButton("Calibrate x-axis")
        
        spec_layout.addWidget(self.btn_load_calib, 0, 0, 1, 2)
        spec_layout.addWidget(self.lbl_notes_calib_loading, 1, 0, 1, 2)
        spec_layout.addWidget(self.lbl_loaded_calib, 2, 0, 1, 2)
        
        spec_layout.addWidget(QLabel("Grating (grooves/mm):"), 3, 0)
        spec_layout.addWidget(self.combo_grating, 3, 1)
        spec_layout.addLayout(spec_radio_layout, 4, 0, 1, 2)
        spec_layout.addWidget(self.lbl_centre, 5, 0)
        spec_layout.addWidget(self.spin_centre_wl, 5, 1)
        spec_layout.addWidget(self.lbl_exc_wl, 6, 0)
        spec_layout.addWidget(self.spin_exc_wl, 6, 1)
        spec_layout.addWidget(self.btn_apply_spec, 7, 0, 1, 2)
        spec_layout.addWidget(self.btn_calib_neon, 8, 0, 1, 2)
        
        spec_group.setLayout(spec_layout)
        controls_layout.addWidget(spec_group)

        roi_group = QGroupBox("Display ROI Settings")
        roi_layout = QVBoxLayout()
        self.radio_2d = QRadioButton("2D Image View")
        self.radio_1d_full = QRadioButton("1D Spectrum (Full Range Binning)")
        self.radio_1d_roi = QRadioButton("1D Spectrum (Custom ROI)")
        self.radio_1d_roi.setChecked(True)
        roi_layout.addWidget(self.radio_2d)
        roi_layout.addWidget(self.radio_1d_full)
        roi_layout.addWidget(self.radio_1d_roi)
        
        self.chk_flip_x = QCheckBox("Flip X-axis")
        self.chk_flip_x.setChecked(self.config.get("flip_x", False))
        roi_layout.addWidget(self.chk_flip_x)
        
        roi_spin_layout = QHBoxLayout()
        roi_spin_layout.addWidget(QLabel("Start Row:"))
        self.spin_vstart = CustomSpinBox()
        self.spin_vstart.setMaximum(4000) 
        roi_spin_layout.addWidget(self.spin_vstart)
        
        roi_spin_layout.addWidget(QLabel("End Row:"))
        self.spin_vend = CustomSpinBox()
        self.spin_vend.setMaximum(4000) 
        roi_spin_layout.addWidget(self.spin_vend)
        roi_layout.addLayout(roi_spin_layout)
        roi_group.setLayout(roi_layout)
        controls_layout.addWidget(roi_group)

        bg_group = QGroupBox("Background")
        bg_layout = QGridLayout()
        
        bg_radio_layout = QHBoxLayout()
        self.radio_bg_on = QRadioButton("ON")
        self.radio_bg_off = QRadioButton("OFF")
        self.radio_bg_off.setChecked(True)
        bg_radio_layout.addWidget(self.radio_bg_on)
        bg_radio_layout.addWidget(self.radio_bg_off)

        self.btn_acq_bg = QPushButton("Acquire and save background")
        self.btn_load_bg = QPushButton("Load background")
        self.lbl_loaded_bg = QLabel("Loaded: None")
        self.lbl_loaded_bg.setStyleSheet("color: #666; font-size: 11px;")

        bg_layout.addWidget(QLabel("Subtract background:"), 0, 0)
        bg_layout.addLayout(bg_radio_layout, 0, 1)
        bg_layout.addWidget(self.btn_acq_bg, 1, 0, 1, 2)
        bg_layout.addWidget(self.btn_load_bg, 2, 0, 1, 2)
        bg_layout.addWidget(self.lbl_loaded_bg, 3, 0, 1, 2)
        bg_group.setLayout(bg_layout)
        controls_layout.addWidget(bg_group)

        fit_group = QGroupBox("Fitting Configurations")
        fit_layout = QGridLayout()
        self.radio_fit_on = QRadioButton("ON")
        self.radio_fit_off = QRadioButton("OFF")
        self.radio_fit_off.setChecked(True)
        fit_radio_layout = QHBoxLayout()
        fit_radio_layout.addWidget(self.radio_fit_on)
        fit_radio_layout.addWidget(self.radio_fit_off)
        self.combo_fit_func = CustomComboBox()
        self.combo_fit_func.addItems(["Gauss", "Lorentz", "Pseudo Voigt", "Double Gauss", "Double Lorentz", "Double pseudo Voigt"])
        self.combo_fit_func.setCurrentText("Double pseudo Voigt")
        
        self.spin_fit_start = CustomDoubleSpinBox()
        self.spin_fit_start.setRange(-10000, 20000)
        self.spin_fit_start.setValue(0.0)
        self.spin_fit_start.setDecimals(2)
        
        self.spin_fit_end = CustomDoubleSpinBox()
        self.spin_fit_end.setRange(-10000, 20000)
        self.spin_fit_end.setValue(4000.0)
        self.spin_fit_end.setDecimals(2)
        
        fit_layout.addWidget(QLabel("Fitting:"), 0, 0)
        fit_layout.addLayout(fit_radio_layout, 0, 1)
        fit_layout.addWidget(QLabel("Function:"), 1, 0)
        fit_layout.addWidget(self.combo_fit_func, 1, 1)
        fit_layout.addWidget(QLabel("Range Start:"), 2, 0)
        fit_layout.addWidget(self.spin_fit_start, 2, 1)
        fit_layout.addWidget(QLabel("Range End:"), 3, 0)
        fit_layout.addWidget(self.spin_fit_end, 3, 1)
        fit_group.setLayout(fit_layout)
        controls_layout.addWidget(fit_group)

        self.pressure_window = None  # ウィンドウのインスタンスを保持する変数を初期化

        self.press_group = QGroupBox("Pressure Calculation")
        press_layout = QVBoxLayout()
        
        self.btn_open_pressure = QPushButton("Open Pressure Calculator")
        self.btn_open_pressure.setStyleSheet("font-weight: bold; padding: 10px; background-color: #E91E63; color: white;")
        self.btn_open_pressure.clicked.connect(self.open_pressure_calculator)
        
        press_layout.addWidget(self.btn_open_pressure)
        self.press_group.setLayout(press_layout)
        
        controls_layout.addWidget(self.press_group)
                    

        controls_layout.addStretch()
        scroll_area.setWidget(controls_widget)
        main_layout.addWidget(scroll_area, stretch=1)

        self.btn_single.clicked.connect(self.check_bg_and_take_single)
        self.btn_save_data.clicked.connect(self.on_save_data_clicked)
        self.btn_commence.clicked.connect(self.check_bg_and_start_meas)
        self.btn_start_seq.clicked.connect(self.check_bg_and_start_seq)
        
        self.radio_spec_mode_wl.toggled.connect(self.on_spec_mode_changed)
        self.radio_spec_mode_raman.toggled.connect(self.on_spec_mode_changed)
        
        self.seq_toggle_btn.toggled.connect(self.toggle_sequential)
        self.btn_choose_dir.clicked.connect(self.on_choose_seq_dir)
        self.btn_stop_seq.clicked.connect(self.stop_sequential)
        
        self.radio_2d.toggled.connect(self.apply_roi_settings)
        self.radio_1d_full.toggled.connect(self.apply_roi_settings)
        self.radio_1d_roi.toggled.connect(self.apply_roi_settings)
        self.spin_vstart.valueChanged.connect(self.on_roi_spin_changed)
        self.spin_vend.valueChanged.connect(self.on_roi_spin_changed)
        
        self.btn_acq_bg.clicked.connect(self.on_acq_bg_clicked)
        self.btn_load_bg.clicked.connect(self.on_load_bg_clicked)
        self.radio_bg_on.toggled.connect(self.on_fit_settings_changed)
        self.radio_bg_off.toggled.connect(self.on_fit_settings_changed)
        
        self.btn_terminate.clicked.connect(self.stop_measurement)
        
        self.chk_flip_x.toggled.connect(self.on_flip_x_changed)
        
        self.chk_rescale_x.toggled.connect(self.on_fit_settings_changed)
        self.chk_rescale_y.toggled.connect(self.on_fit_settings_changed)
        
        self.btn_read_temp.clicked.connect(self.request_temperature_read)

        self.radio_fit_on.toggled.connect(self.toggle_fitting_panel)
        self.radio_fit_off.toggled.connect(self.toggle_fitting_panel)
        self.combo_fit_func.currentTextChanged.connect(self.on_fit_settings_changed)
        self.spin_fit_start.valueChanged.connect(self.on_fit_settings_changed)
        self.spin_fit_end.valueChanged.connect(self.on_fit_settings_changed)
        
        
        
        


        self.spin_acq_time.editingFinished.connect(self.on_exposure_changed)
        self.spin_cooler_temp.editingFinished.connect(self.on_temperature_changed)
        
        self.combo_grating.currentIndexChanged.connect(self.check_spectrometer_changes)
        self.spin_centre_wl.valueChanged.connect(self.check_spectrometer_changes)
        self.spin_exc_wl.valueChanged.connect(self.on_exc_wl_changed)

        self.btn_apply_spec.clicked.connect(self.on_apply_spectrometer)
        self.btn_calib_neon.clicked.connect(self.on_calibrate_neon)
        self.btn_load_calib.clicked.connect(self.on_load_calibration) 
        
        self.seq_timer = QTimer(self)
        self.seq_timer.timeout.connect(self.update_seq_progress)
        
        self.update_plot_labels()
        self.radio_spec_mode_wl.toggled.connect(self.sync_pressure_calculator_mode)
        self.radio_spec_mode_raman.toggled.connect(self.sync_pressure_calculator_mode)
        
        self.spec_ctrl.initialize()
        
        current_wl = self.spec_ctrl.get_wavelength()
        self.physical_center_wl = current_wl
        self.spin_centre_wl.setValue(current_wl)
        
        current_grating_idx = self.spec_ctrl.get_grating()
        target_cb_idx = 0
        for i, g in enumerate(self.config.get("grating", [])):
            if g.get("index") == current_grating_idx:
                target_cb_idx = i
                break
                
        if 0 <= target_cb_idx < len(self.grating_list):
            self.combo_grating.setCurrentIndex(target_cb_idx)
        else:
            self.combo_grating.setCurrentIndex(0)
            
        self.physical_grating = self.combo_grating.currentText()
        self.btn_apply_spec.setEnabled(False)
        
        roi_f, roi_t = self.get_roi_for_grating(self.physical_grating)
        self.spin_vstart.blockSignals(True)
        self.spin_vend.blockSignals(True)
        self.spin_vstart.setValue(roi_f)
        self.spin_vend.setValue(roi_t)
        self.spin_vstart.blockSignals(False)
        self.spin_vend.blockSignals(False)

        self.centralWidget().setEnabled(False)
        self.init_dialog = QDialog(self)
        self.init_dialog.setWindowTitle("Please Wait")
        self.init_dialog.setModal(True)
        self.init_dialog.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Initializing camera and cooler...\nPlease wait until the operation is completed."))
        self.init_dialog.setLayout(layout)
        self.init_dialog.show()

        self.thread = CameraThread(config=self.config, debug=self.debug)
        self.thread.data_ready.connect(self.on_data_ready)
        self.thread.init_finished.connect(self.on_camera_initialized)
        self.thread.temperature_ready.connect(self.on_temperature_read)
        
        self.thread.exposure_set_finished.connect(lambda: self.spin_acq_time.setEnabled(True))
        self.thread.temperature_set_finished.connect(lambda: self.spin_cooler_temp.setEnabled(True))
        
        self.thread.start()

    def get_roi_for_grating(self, grating_str):
        for g in self.config.get("grating", []):
            if str(g.get("grooves")) == str(grating_str):
                r = g.get("defaultROI", {})
                return r.get("from", 100), r.get("to", 140)
        return 100, 140

    def save_config_to_file(self):
        try:
            with open("spectrometerConfig.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def on_roi_spin_changed(self):
        self.apply_roi_settings()
        
        for g in self.config.get("grating", []):
            if str(g.get("grooves")) == self.physical_grating:
                g.setdefault("defaultROI", {})["from"] = self.spin_vstart.value()
                g.setdefault("defaultROI", {})["to"] = self.spin_vend.value()
                break
        self.save_config_to_file()

    def show_skip_frames_info(self, link):
        dialog = QDialog(self)
        dialog.setWindowTitle("How Skip frames works")
        dialog.setModal(True)
        layout = QVBoxLayout()
        info_text = (
            "If you set 'Skip frames' to N, the system will save 1 frame and then ignore the next N frames.<br><br>"
            "For example, if you set it to 9 with an exposure time of 0.1 s, the system will save 1 frame every 1 second<br>"
            "(1 saved + 9 skipped = 10 frames = 1.0 s)."
        )
        lbl = QLabel(info_text)
        layout.addWidget(lbl)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.setLayout(layout)
        dialog.exec()

    def update_seq_progress(self):
        if not self.is_sequential_running:
            return
        self.lbl_seq_progress.setText(f"Progress: Acquired {self.seq_count} / {self.spin_max_num.value()}")

    def set_ui_enabled_during_seq(self, enabled):
        self.btn_single.setEnabled(enabled)
        self.btn_commence.setEnabled(enabled)
        self.btn_terminate.setEnabled(enabled)
        self.btn_save_data.setEnabled(enabled)
        
        self.spin_acq_time.setEnabled(enabled)
        self.spin_accumulate.setEnabled(enabled)
        self.spin_cooler_temp.setEnabled(enabled)
        self.btn_read_temp.setEnabled(enabled)
        
        self.btn_choose_dir.setEnabled(enabled)
        self.spin_skip_frames.setEnabled(enabled)
        self.spin_max_num.setEnabled(enabled)
        
        self.radio_bg_on.setEnabled(enabled)
        self.radio_bg_off.setEnabled(enabled)
        self.btn_acq_bg.setEnabled(enabled)
        self.btn_load_bg.setEnabled(enabled)
        
        self.radio_2d.setEnabled(enabled)
        self.radio_1d_full.setEnabled(enabled)
        self.radio_1d_roi.setEnabled(enabled)
        self.spin_vstart.setEnabled(enabled)
        self.spin_vend.setEnabled(enabled)
        self.chk_flip_x.setEnabled(enabled)
        
        self.combo_grating.setEnabled(enabled)
        self.radio_spec_mode_wl.setEnabled(enabled)
        self.radio_spec_mode_raman.setEnabled(enabled)
        self.spin_centre_wl.setEnabled(enabled)
        if self.radio_spec_mode_raman.isChecked():
            self.spin_exc_wl.setEnabled(enabled)
        self.btn_apply_spec.setEnabled(enabled)
        self.btn_calib_neon.setEnabled(enabled)
        self.btn_load_calib.setEnabled(enabled)
        
        self.radio_fit_on.setEnabled(enabled)
        self.radio_fit_off.setEnabled(enabled)
        self.combo_fit_func.setEnabled(enabled)
        self.spin_fit_start.setEnabled(enabled)
        self.spin_fit_end.setEnabled(enabled)
        
        
        
        if enabled:
            self.toggle_fitting_panel()
            self.apply_roi_settings()

    def on_choose_seq_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory for Sequential Data")
        if dir_path:
            self.seq_dir = dir_path
            display_path = dir_path if len(dir_path) < 25 else "..." + dir_path[-22:]
            self.lbl_seq_dir.setText(f"Dir: {display_path}")
            if not self.is_sequential_running:
                self.btn_start_seq.setEnabled(True)
                self.btn_start_seq.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")

    def on_spec_mode_changed(self):
        is_raman = self.radio_spec_mode_raman.isChecked()
        self.spin_exc_wl.setEnabled(is_raman)
        
        if is_raman:
            self.lbl_centre.setText("Centre (cm⁻¹):")
            ex_wl = self.spin_exc_wl.value()
            if ex_wl > 0 and self.physical_center_wl > 0:
                new_center = (1e7 / ex_wl) - (1e7 / self.physical_center_wl)
            else:
                new_center = 0.0
        else:
            self.lbl_centre.setText("Centre (nm):")
            new_center = self.physical_center_wl
            
        self.spin_centre_wl.blockSignals(True)
        self.spin_centre_wl.setValue(new_center)
        self.spin_centre_wl.blockSignals(False)
        
        self.check_spectrometer_changes()
        self.update_plot_labels()
        self.on_fit_settings_changed()

    def on_exc_wl_changed(self):
        if self.radio_spec_mode_raman.isChecked():
            ex_wl = self.spin_exc_wl.value()
            if ex_wl > 0 and self.physical_center_wl > 0:
                new_center = (1e7 / ex_wl) - (1e7 / self.physical_center_wl)
            else:
                new_center = 0.0
            self.spin_centre_wl.blockSignals(True)
            self.spin_centre_wl.setValue(new_center)
            self.spin_centre_wl.blockSignals(False)
            self.check_spectrometer_changes()

    def update_plot_labels(self):
        if self.calib_coeffs is not None:
            if self.radio_spec_mode_raman.isChecked():
                self.plot_widget.setLabel('bottom', 'Raman shift (cm⁻¹)')
            else:
                self.plot_widget.setLabel('bottom', 'Wavelength (nm)')
        else:
            self.plot_widget.setLabel('bottom', 'Pixel')

    def check_spectrometer_changes(self, *args):
        curr_g = self.combo_grating.currentText()
        val = self.spin_centre_wl.value()
        
        if self.radio_spec_mode_raman.isChecked():
            ex_wl = self.spin_exc_wl.value()
            if ex_wl > 0:
                try:
                    target_wl = 1e7 / (1e7 / ex_wl - val)
                except ZeroDivisionError:
                    target_wl = val
            else:
                target_wl = val
        else:
            target_wl = val
            
        if curr_g == self.physical_grating and abs(target_wl - self.physical_center_wl) < 1e-4:
            self.btn_apply_spec.setEnabled(False)
        else:
            self.btn_apply_spec.setEnabled(True)

    def check_bg_mismatch(self):
        if not self.radio_bg_on.isChecked() or getattr(self, 'loaded_bg_metadata', None) is None:
            return False
        
        bg_meta = self.loaded_bg_metadata
        curr_acq = self.spin_acq_time.value()
        curr_accum = self.spin_accumulate.value()
        curr_mode = "1D Spectrum (Custom ROI)" if self.radio_1d_roi.isChecked() else "1D Spectrum (Full Range Binning)"
        
        mismatch = False
        if abs(curr_acq - bg_meta.get("acquisition_time", 0)) > 1e-4:
            mismatch = True
        if curr_accum != bg_meta.get("accumulations", 1):
            mismatch = True
        if curr_mode != bg_meta.get("mode"):
            mismatch = True
        if curr_mode == "1D Spectrum (Custom ROI)":
            curr_start = self.spin_vstart.value()
            curr_end = self.spin_vend.value()
            if curr_start != bg_meta.get("roi_start") or curr_end != bg_meta.get("roi_end"):
                mismatch = True
        return mismatch

    def handle_bg_mismatch_and_run(self, callback):
        if not self.check_bg_mismatch():
            callback()
            return
            
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Icon.Warning)
        msgBox.setWindowTitle("Background Mismatch")
        msgBox.setText("Current measurement settings do not match the loaded background.\nPlease close the shutter and acquire a new background, or ignore to continue.")
        
        btn_ignore = msgBox.addButton("Ignore and continue", QMessageBox.ButtonRole.ActionRole)
        msgBox.addButton("Quit", QMessageBox.ButtonRole.RejectRole)
        
        msgBox.exec()
        
        if msgBox.clickedButton() == btn_ignore:
            callback()

    def check_bg_and_take_single(self):
        self.handle_bg_mismatch_and_run(self.take_single_spectrum)

    def check_bg_and_start_meas(self):
        self.handle_bg_mismatch_and_run(self.start_measurement)

    def check_bg_and_start_seq(self):
        self.handle_bg_mismatch_and_run(self.start_sequential)

    def start_sequential(self):
        if not self.seq_dir:
            QMessageBox.warning(self, "Error", "Please select a directory first.")
            return
            
        self.is_sequential_running = True
        self.seq_count = 0
        self.current_skip_count = self.spin_skip_frames.value()
        self._seq_fit_failed = False
        
        self.btn_start_seq.setEnabled(False)
        self.btn_start_seq.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.btn_stop_seq.setEnabled(True)
        self.btn_stop_seq.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        
        self.seq_start_time_dt = datetime.now()
        self.seq_log_data = []
        
        self.lbl_seq_progress.setVisible(True)
        self.lbl_seq_progress.setText(f"Progress: Acquired 0 / {self.spin_max_num.value()}")
        
        self.set_ui_enabled_during_seq(False)
        
        if self.radio_fit_on.isChecked():
            start_date_str = self.seq_start_time_dt.strftime("%Y%m%d_%H%M%S")
            self.seq_fitting_summary_path = os.path.join(self.seq_dir, f"fitting_seq_summary_{start_date_str}.txt")
            
            func = self.combo_fit_func.currentText()
            fit_start = self.spin_fit_start.value()
            fit_end = self.spin_fit_end.value()
            is_double = "Double" in func
            
            
            try:
                with open(self.seq_fitting_summary_path, "w", encoding="utf-8") as f:
                    f.write(f"# Fitting Function: {func}\n")
                    f.write(f"# Fitting Range: {fit_start} to {fit_end}\n")
                    
                        
                        
            except Exception as e:
                print(f"Failed to create summary file: {e}")
                self.seq_fitting_summary_path = None
        else:
            self.seq_fitting_summary_path = None
        
        self._ignore_next_frames = False
        if not hasattr(self.thread, 'is_measuring') or not self.thread.is_measuring:
            self.start_measurement()

    def stop_sequential(self):
        if getattr(self, 'is_sequential_running', False):
            if hasattr(self, 'seq_start_time_dt') and self.seq_dir:
                seq_end_time_dt = datetime.now()
                summary_path = os.path.join(self.seq_dir, f"seq_summary_{self.seq_start_time_dt.strftime('%Y%m%d_%H%M%S')}.txt")
                try:
                    with open(summary_path, "w", encoding="utf-8", newline="") as f:
                        f.write(f"Sequential Measurement Summary\n")
                        f.write(f"Start Time: {self.seq_start_time_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"End Time: {seq_end_time_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Exposure Time: {self.spin_acq_time.value()} s\n")
                        f.write(f"Accumulations: {self.spin_accumulate.value()}\n")
                        f.write(f"Skip Frames: {self.spin_skip_frames.value()}\n")
                        f.write("-" * 30 + "\n")
                        
                        writer = csv.writer(f)
                        writer.writerow(["Filename", "Saved Time"])
                        writer.writerows(self.seq_log_data)
                except Exception as e:
                    print(f"Failed to write sequential summary: {e}")

        self.is_sequential_running = False
        self.lbl_seq_progress.setVisible(False)
        self.seq_fitting_summary_path = None
        
        self.btn_start_seq.setEnabled(True)
        self.btn_start_seq.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.btn_stop_seq.setEnabled(False)
        self.btn_stop_seq.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        
        self.set_ui_enabled_during_seq(True)
        
        if hasattr(self.thread, 'is_measuring') and self.thread.is_measuring:
            self.stop_measurement()

    def on_set_r1_clicked(self):
        if self.current_w_peak1 is not None:
            if self.calib_coeffs is not None and self.radio_spec_mode_raman.isChecked():
                ex_wl = self.spin_exc_wl.value()
                if ex_wl > 0:
                    lam_peak1 = 1e7 / (1e7 / ex_wl - self.current_w_peak1)
                    self.spin_lambda0.setValue(float(lam_peak1))
            else:
                self.spin_lambda0.setValue(float(self.current_w_peak1))

    def toggle_sequential(self, checked):
        self.seq_content.setVisible(checked)
        self.seq_toggle_btn.setText("▼ Sequential measurements" if checked else "▶ Sequential measurements")

    def sync_pressure_calculator_mode(self):
        """メイン画面の nm/Raman 切り替えを圧力計算ウィンドウに即時反映させる"""
        if self.pressure_window:
            current_unit = "cm-1" if self.radio_spec_mode_raman.isChecked() else "nm"
            self.pressure_window.update_mode(current_unit)

    def open_pressure_calculator(self):
        """圧力計算ウィンドウを開く (ボタンクリック時)"""
        current_unit = "cm-1" if self.radio_spec_mode_raman.isChecked() else "nm"

        if self.radio_fit_off.isChecked():
            msgBox_fitRequired = QMessageBox(self)
            msgBox_fitRequired.setIcon(QMessageBox.Icon.Warning)
            msgBox_fitRequired.setWindowTitle("Fitting required")
            msgBox_fitRequired.setText("Please activate peak fitting to calculate pressure.")
            msgBox_fitRequired.exec()
        else:
                    
            if self.pressure_window is None:
                self.pressure_window = PressureCalculatorWindow(self, mode=current_unit)
            else:
                self.pressure_window.update_mode(current_unit)

            self.pressure_window.show()
            self.pressure_window.raise_()
            self.pressure_window.activateWindow()
            

    def load_spectrometer_config(self):
        config_path = "spectrometerConfig.json"
        default_config = {
            "model": "Andor",
            "com_port": "COM3",
            "grating": [
                {
                    "index": 1,
                    "grooves": 600,
                    "defaultROI": {"from": 100, "to": 140}
                },
                {
                    "index": 2,
                    "grooves": 1200,
                    "defaultROI": {"from": 100, "to": 140}
                },
                {
                    "index": 3,
                    "grooves": 1800,
                    "defaultROI": {"from": 100, "to": 140}
                }
            ],
            "flip_x": False
        }
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print("spectrometerConfig.json read:", json.dumps(data, indent=2))
                
                if "grating" in data and len(data["grating"]) > 0 and isinstance(data["grating"][0], (int, float)):
                    new_grating = []
                    for i, g in enumerate(data["grating"]):
                        new_grating.append({
                            "index": i + 1,
                            "grooves": int(g),
                            "defaultROI": data.get("defaultROI", {"from": 100, "to": 140})
                        })
                    data["grating"] = new_grating
                    
                    try:
                        with open(config_path, "w", encoding="utf-8") as fw:
                            json.dump(data, fw, indent=4)
                    except:
                        pass
                
                for key, val in default_config.items():
                    if key not in data:
                        data[key] = val
                return data
        except:
            return default_config

    def on_flip_x_changed(self):
        self.config["flip_x"] = self.chk_flip_x.isChecked()
        self.save_config_to_file()
        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

    def apply_calibration(self, coeffs, filename):
        self.calib_coeffs = coeffs
        self.calib_file_name = filename
        self.lbl_loaded_calib.setText(f"Loaded: {filename}")
        self.update_plot_labels()
        
        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

    def on_load_calibration(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", "", "JSON Files (*.json)")
        if not file_path:
            return
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            spec_settings = data.get("spectrometer_settings", {})
            calib_grating = str(spec_settings.get("grating_grooves_per_mm", "600"))
            calib_unit = spec_settings.get("unit", "Wavelength")
            calib_center = spec_settings.get("center_value", 694.0)
            
            if "center_wavelength_nm" in spec_settings:
                calib_center = spec_settings["center_wavelength_nm"]
                calib_unit = "Wavelength"
                
            det_settings = data.get("detector_settings", {})
            det_mode = det_settings.get("mode", "1D Spectrum (Custom ROI)")
            roi_start = det_settings.get("roi_start", 100)
            roi_end = det_settings.get("roi_end", 140)
            
            c0 = data["calibration_coefficients"]["c0"]
            c1 = data["calibration_coefficients"]["c1"]
            c2 = data["calibration_coefficients"]["c2"]
            
            if "2D" in det_mode:
                self.radio_2d.setChecked(True)
            elif "Full" in det_mode:
                self.radio_1d_full.setChecked(True)
            else:
                self.radio_1d_roi.setChecked(True)
                
            self.spin_vstart.blockSignals(True)
            self.spin_vend.blockSignals(True)
            self.spin_vstart.setValue(roi_start)
            self.spin_vend.setValue(roi_end)
            self.spin_vstart.blockSignals(False)
            self.spin_vend.blockSignals(False)
            self.apply_roi_settings()
            
            self.radio_spec_mode_raman.blockSignals(True)
            self.radio_spec_mode_wl.blockSignals(True)
            if calib_unit == "Raman shift":
                self.radio_spec_mode_raman.setChecked(True)
                self.lbl_centre.setText("Centre (cm⁻¹):")
            else:
                self.radio_spec_mode_wl.setChecked(True)
                self.lbl_centre.setText("Centre (nm):")
            self.radio_spec_mode_raman.blockSignals(False)
            self.radio_spec_mode_wl.blockSignals(False)
            
            cb_idx = self.combo_grating.findText(calib_grating)
            if cb_idx >= 0:
                self.combo_grating.setCurrentIndex(cb_idx)
                
            self.spin_centre_wl.setValue(calib_center)
            
            self._loading_config = True
            self._pending_calib_coeffs = (c0, c1, c2)
            self._pending_calib_filename = os.path.basename(file_path)
            
            self.on_apply_spectrometer()
            
        except Exception as e:
            self._loading_config = False
            self._pending_calib_coeffs = None
            QMessageBox.warning(self, "Error", f"Failed to load configuration:\n{e}")

    def on_acq_bg_clicked(self):
        self._is_acquiring_bg = True
        self.is_single_shot = True
        self._ignore_next_frames = False
        self.current_accum_count = 0
        self.btn_single.setEnabled(False)
        self.btn_commence.setEnabled(False)
        self.btn_commence.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.btn_terminate.setEnabled(True)
        self.btn_terminate.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.thread.start_measuring()

    def _process_acquired_bg(self):
        if getattr(self, 'raw_1d_data', None) is None:
            QMessageBox.warning(self, "Error", "No 1D data available for background.")
            return

        acq_time = self.spin_acq_time.value()
        accum = self.spin_accumulate.value()
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        mode_str = "1D Spectrum (Custom ROI)" if self.radio_1d_roi.isChecked() else "1D Spectrum (Full Range Binning)"
        
        if self.radio_1d_roi.isChecked():
            roi_str = f"_ROI_from_{self.spin_vstart.value()}_to_{self.spin_vend.value()}"
        else:
            roi_str = "_full"
            
        default_filename = f"background_{date_str}{roi_str}.txt"

        file_path, _ = QFileDialog.getSaveFileName(self, "Save Background Data", default_filename, "Text/JSON Files (*.txt *.json)")
        if not file_path:
            return

        current_temp = self.label_current_temp.text()

        bg_data = {
            "detector_settings": {
                "mode": mode_str,
                "roi_start": self.spin_vstart.value(),
                "roi_end": self.spin_vend.value()
            },
            "acquisition_time": f"{acq_time:.3f}",
            "accumulations": accum,
            "detector_temperature": current_temp,
            "signal": self.raw_1d_data.tolist()
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(bg_data, f, indent=4)
            QMessageBox.information(self, "Success", "Background saved successfully.")
            
            self.loaded_bg_data = self.raw_1d_data.astype(np.float64).copy()
            self.loaded_bg_metadata = {
                "acquisition_time": float(acq_time),
                "accumulations": accum,
                "mode": mode_str,
                "roi_start": self.spin_vstart.value(),
                "roi_end": self.spin_vend.value()
            }
            
            self.lbl_loaded_bg.setText(f"Loaded: {os.path.basename(file_path)}")
            self.radio_bg_on.setChecked(True)
            self.on_fit_settings_changed()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save background:\n{e}")

    def on_load_bg_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Background Data", "", "Text/JSON Files (*.txt *.json)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "signal" in data:
                        self.loaded_bg_data = np.array(data["signal"], dtype=np.float64)
                        
                        acq_time = float(data.get("acquisition_time", 0.0))
                        accum = int(data.get("accumulations", 1))
                        det_set = data.get("detector_settings", {})
                        mode_str = det_set.get("mode", "")
                        roi_s = det_set.get("roi_start", 0)
                        roi_e = det_set.get("roi_end", 0)
                        
                        self.loaded_bg_metadata = {
                            "acquisition_time": acq_time,
                            "accumulations": accum,
                            "mode": mode_str,
                            "roi_start": roi_s,
                            "roi_end": roi_e
                        }
                        
                        self.lbl_loaded_bg.setText(f"Loaded: {os.path.basename(file_path)}")
                        self.radio_bg_on.setChecked(True)
                        self.on_fit_settings_changed()
                    else:
                        QMessageBox.warning(self, "Error", "Invalid background file format.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load background:\n{e}")

    def on_save_data_clicked(self):
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        default_filename = f"data_{date_str}.txt"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Data", default_filename, "Text Files (*.txt);;All Files (*)")
        if file_path:
            self._save_data_to_path(file_path, show_msg=True)

    def _save_data_to_path(self, file_path, show_msg=True):
        is_1d = self.stacked_widget.currentIndex() == 0
        if is_1d and self.latest_1d_data is None:
            if show_msg: QMessageBox.warning(self, "Error", "No 1D data available to save.")
            return False
        if not is_1d and self.latest_2d_data is None:
            if show_msg: QMessageBox.warning(self, "Error", "No 2D data available to save.")
            return False
            
        try:
            grating = self.combo_grating.currentText()
            center_wl = self.spin_centre_wl.value()
            acq_time = self.spin_acq_time.value()
            accum = self.spin_accumulate.value()
            
            header = f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            header += f"Grating: {grating} grooves/mm\n"
            
            if self.radio_spec_mode_raman.isChecked():
                ex_wl = self.spin_exc_wl.value()
                header += f"Spectrometer Mode: Raman shift\n"
                header += f"Excitation Wavelength: {ex_wl} nm\n"
                header += f"Centre Raman shift: {center_wl} cm-1\n"
            else:
                header += f"Spectrometer Mode: Wavelength\n"
                header += f"Centre Wavelength: {center_wl} nm\n"
                
            header += f"Acquisition Time: {acq_time} s\n"
            header += f"Accumulations: {accum}\n"

            if self.calib_coeffs is not None:
                c0, c1, c2 = self.calib_coeffs
                header += f"Calibration Coefficients (c0, c1, c2: y = c0 + c1x + c2x^2): {c0}, {c1}, {c2}\n"
            else:
                header += f"Calibration Coefficients: None\n"

            header += f"ROI Start (Vertical Pixel): {self.spin_vstart.value()}\n"
            header += f"ROI End (Vertical Pixel): {self.spin_vend.value()}\n"

            mode = "2D" if self.radio_2d.isChecked() else "1D (Full)" if self.radio_1d_full.isChecked() else "1D (ROI)"
            header += f"Measurement Mode: {mode}\n"

            
            if is_1d:
                x_data = self.get_x_axis(len(self.latest_1d_data))
                y_disp = self.latest_1d_data
                
                bg_applied = False
                if self.radio_bg_on.isChecked() and self.loaded_bg_data is not None:
                    if len(self.raw_1d_data) == len(self.loaded_bg_data):
                        bg_applied = True
                
                x_label = "Raman_shift_cm-1" if self.radio_spec_mode_raman.isChecked() else "Wavelength_or_Pixel"
                
                if bg_applied:
                    header += f"{x_label},Intensity_Subtracted,Intensity_Raw,Background"
                    y_raw = self.raw_1d_data.astype(np.float64)
                    y_bg = self.loaded_bg_data.astype(np.float64)
                    if self.chk_flip_x.isChecked():
                        y_raw = y_raw[::-1]
                        y_bg = y_bg[::-1]
                    data_to_save = np.column_stack((x_data, y_disp, y_raw, y_bg))
                else:
                    header += f"{x_label},Intensity"
                    data_to_save = np.column_stack((x_data, y_disp))
                    
                np.savetxt(file_path, data_to_save, delimiter=",", header=header, comments="# ", fmt="%g")
                
                if self.chk_save_fitting.isChecked() and self.radio_fit_on.isChecked() and self.latest_fit_res is not None:
                    fit_file_path = file_path.rsplit('.', 1)[0] + "_fitting_results.txt"
                    res = self.latest_fit_res
                    func = getattr(self, 'latest_fit_func', 'Unknown')
                    
                    if res.get('is_double'):
                        fit_header = "Function,R2,Peak1_Pos,Peak1_Err,Peak1_Width,Peak1_WErr,Peak2_Pos,Peak2_Err,Peak2_Width,Peak2_WErr"
                        vals = [
                            func, f"{res.get('R2', 0):.6f}",
                            f"{res.get('Peak1', 0):.6f}", f"{res.get('Peak1_Err', 0):.6f}",
                            f"{res.get('Width1', 0):.6f}", f"{res.get('Width1_Err', 0):.6f}",
                            f"{res.get('Peak2', 0):.6f}", f"{res.get('Peak2_Err', 0):.6f}",
                            f"{res.get('Width2', 0):.6f}", f"{res.get('Width2_Err', 0):.6f}"
                        ]
                    else:
                        fit_header = "Function,R2,Peak_Pos,Peak_Err,Peak_Width,Peak_WErr"
                        vals = [
                            func, f"{res.get('R2', 0):.6f}",
                            f"{res.get('Peak', 0):.6f}", f"{res.get('Peak_Err', 0):.6f}",
                            f"{res.get('Width', 0):.6f}", f"{res.get('Width_Err', 0):.6f}"
                        ]
                        
                    
                        
                    fit_data_lines = [fit_header + "\n", ",".join(vals) + "\n"]
                        
                    with open(fit_file_path, "w", encoding="utf-8") as f:
                        f.writelines(fit_data_lines)
                        
            else:
                header += "2D Image Data"
                np.savetxt(file_path, self.latest_2d_data, delimiter=",", header=header, comments="# ", fmt="%g")
                
            if show_msg:
                QMessageBox.information(self, "Success", f"Data saved successfully to:\n{file_path}")
            return True
        except Exception as e:
            if show_msg:
                QMessageBox.critical(self, "Error", f"Failed to save data:\n{e}")
            else:
                print(f"Sequential save error: {e}")
            return False

    def take_single_spectrum(self):
        self.is_single_shot = True
        self._ignore_next_frames = False
        self.current_accum_count = 0
        self.btn_single.setEnabled(False)
        self.btn_commence.setEnabled(False)
        self.btn_commence.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.btn_terminate.setEnabled(True)
        self.btn_terminate.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.thread.start_measuring()

    def get_x_axis(self, num_pixels):
        x = np.arange(num_pixels)
        if self.calib_coeffs is not None:
            c0, c1, c2 = self.calib_coeffs
            wl = c0 + c1 * x + c2 * x**2
            if self.radio_spec_mode_raman.isChecked():
                ex_wl = self.spin_exc_wl.value()
                if ex_wl > 0:
                    with np.errstate(divide='ignore', invalid='ignore'):
                        rs = 1e7 / ex_wl - 1e7 / wl
                    return rs
            return wl
        return x

    def toggle_fitting_panel(self):
        is_on = self.radio_fit_on.isChecked()
        self.fitting_panel.setVisible(is_on)
        
        self.chk_save_fitting.setEnabled(is_on)
        if not is_on:
            self.chk_save_fitting.setChecked(False)
            self.fit_curve.clear()
            self.fit_curve_sub1.clear()
            self.fit_curve_sub2.clear()
            self.current_w_peak1 = None
            self.latest_fit_res = None
            self.latest_fit_func = None
        else:
            if getattr(self, 'raw_1d_data', None) is not None:
                x_data = self.get_x_axis(len(self.raw_1d_data))
                min_x = np.min(x_data)
                max_x = np.max(x_data)
                
                curr_start = self.spin_fit_start.value()
                curr_end = self.spin_fit_end.value()
                
                if curr_start < min_x or curr_end > max_x:
                    self.spin_fit_start.blockSignals(True)
                    self.spin_fit_end.blockSignals(True)
                    self.spin_fit_start.setValue(float(min_x))
                    self.spin_fit_end.setValue(float(max_x))
                    self.spin_fit_start.blockSignals(False)
                    self.spin_fit_end.blockSignals(False)

            if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
                self.update_display(is_new_data=False)

    def on_fit_settings_changed(self):
        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

    def on_calibrate_neon(self):
        was_measuring = self.thread.is_measuring
        if was_measuring:
            self.stop_measurement()
            
        calib_win = CalibrationWindow(camera_thread=self.thread, parent=self)
        calib_win.exec()
        
        if was_measuring:
            self.start_measurement()

    def on_exposure_changed(self):
        val = self.spin_acq_time.value()
        self.spin_acq_time.setEnabled(False) 
        self.thread.update_exposure(val)

    def on_temperature_changed(self):
        val = self.spin_cooler_temp.value()
        self.spin_cooler_temp.setEnabled(False) 
        self.thread.update_temperature(val)

    def on_apply_spectrometer(self):
        grating_index = self.combo_grating.currentIndex() + 1
        val = self.spin_centre_wl.value()
        
        if self.radio_spec_mode_raman.isChecked():
            ex_wl = self.spin_exc_wl.value()
            if ex_wl > 0:
                try:
                    target_wl = 1e7 / (1e7 / ex_wl - val)
                except ZeroDivisionError:
                    target_wl = val
            else:
                target_wl = val
        else:
            target_wl = val
        
        self.centralWidget().setEnabled(False)
        self.moving_dialog = QDialog(self)
        self.moving_dialog.setWindowTitle("Please Wait")
        self.moving_dialog.setModal(True)
        self.moving_dialog.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Grating is moving...\nPlease wait until the operation is completed."))
        self.moving_dialog.setLayout(layout)
        self.moving_dialog.show()

        self.spec_move_thread = SpectrometerMoveThread(self.spec_ctrl, grating_index, target_wl)
        self.spec_move_thread.finished_signal.connect(self.on_spectrometer_moved)
        self.spec_move_thread.start()

    def on_spectrometer_moved(self):
        self.physical_grating = self.combo_grating.currentText()
        val = self.spin_centre_wl.value()
        if self.radio_spec_mode_raman.isChecked():
            ex_wl = self.spin_exc_wl.value()
            self.physical_center_wl = 1e7 / (1e7 / ex_wl - val) if ex_wl > 0 else val
        else:
            self.physical_center_wl = val
            
        self.btn_apply_spec.setEnabled(False)
        
        if getattr(self, '_loading_config', False):
            if hasattr(self, '_pending_calib_coeffs') and self._pending_calib_coeffs is not None:
                self.apply_calibration(self._pending_calib_coeffs, self._pending_calib_filename)
                self._pending_calib_coeffs = None
                self._pending_calib_filename = None
            self._loading_config = False
        else:
            self.calib_coeffs = None
            self.calib_file_name = "None"
            self.lbl_loaded_calib.setText("Loaded: None")
            self.update_plot_labels()
            
            roi_f, roi_t = self.get_roi_for_grating(self.physical_grating)
            self.spin_vstart.blockSignals(True)
            self.spin_vend.blockSignals(True)
            self.spin_vstart.setValue(roi_f)
            self.spin_vend.setValue(roi_t)
            self.spin_vstart.blockSignals(False)
            self.spin_vend.blockSignals(False)
            self.apply_roi_settings()
        
        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)
            
        self.moving_dialog.accept()
        self.centralWidget().setEnabled(True)

    def request_temperature_read(self):
        self.label_current_temp.setText("Reading...")
        self.thread.read_temperature()

    def on_temperature_read(self, temp):
        if temp == -999.0:
            self.label_current_temp.setText("Error")
        else:
            self.label_current_temp.setText(f"{temp:.1f} °C")

    def on_camera_initialized(self):
        self.init_dialog.accept()
        self.centralWidget().setEnabled(True)
        
        self.btn_commence.setEnabled(True)
        self.btn_commence.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_single.setEnabled(True)
        
        self.status_label.setText("Camera Ready")
        
        self.spin_vstart.setMaximum(self.thread.det_height - 1)
        self.spin_vend.setMaximum(self.thread.det_height)
        
        self.radio_2d.setText(f"2D Image View ({self.thread.det_width}x{self.thread.det_height})")
        self.apply_roi_settings()

    def apply_roi_settings(self):
        is_custom_roi = self.radio_1d_roi.isChecked()
        self.spin_vstart.setEnabled(is_custom_roi)
        self.spin_vend.setEnabled(is_custom_roi)
        
        if self.radio_2d.isChecked():
            mode = "2d"
            self.radio_bg_off.setChecked(True)
            self.radio_bg_on.setEnabled(False)
        elif self.radio_1d_full.isChecked():
            mode = "1d_full"
            self.radio_bg_on.setEnabled(True)
        else:
            mode = "1d_roi"
            self.radio_bg_on.setEnabled(True)
            
        self.thread.update_roi_settings(mode, self.spin_vstart.value(), self.spin_vend.value())

    def start_measurement(self):
        self.is_single_shot = False
        self._ignore_next_frames = False
        self.current_accum_count = 0
        self.btn_single.setEnabled(False)
        self.btn_commence.setEnabled(False)
        self.btn_commence.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.btn_terminate.setEnabled(True)
        self.btn_terminate.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.thread.start_measuring()

    def stop_measurement(self):
        self.btn_single.setEnabled(True)
        self.btn_commence.setEnabled(True)
        self.btn_commence.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_terminate.setEnabled(False)
        self.btn_terminate.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")
        self.lbl_accum_status.setVisible(False)
        self.thread.stop_measuring()

    def on_data_ready(self, mode, data):
        if not getattr(self.thread, 'is_measuring', False) and not self.is_single_shot:
            pass
            
        if self._ignore_next_frames:
            return
            
        target_accum = self.spin_accumulate.value()
        
        if self.current_accum_count == 0:
            self.accumulated_data = data.astype(np.float64).copy()
        else:
            self.accumulated_data += data.astype(np.float64)
            
        self.current_accum_count += 1
        self.lbl_accum_status.setText(f"Acquired: {self.current_accum_count} / {target_accum}")
        self.lbl_accum_status.setVisible(target_accum > 1)
        
        if self.current_accum_count >= target_accum:
            if self.is_single_shot:
                self._ignore_next_frames = True
                self.stop_measurement()
            self.current_accum_count = 0
            final_data = self.accumulated_data.copy()
            self._process_completed_data(mode, final_data)

    def _process_completed_data(self, mode, data):
        if self.is_single_shot:
            self.is_single_shot = False
            
            if mode == "1d":
                self.raw_1d_data = data
            elif mode == "2d":
                self.raw_2d_data = data
            self.update_display(is_new_data=True, mode=mode)
            
            if getattr(self, '_is_acquiring_bg', False):
                self._is_acquiring_bg = False
                self._process_acquired_bg()
            return
            
        if mode == "1d":
            self.raw_1d_data = data
        elif mode == "2d":
            self.raw_2d_data = data
        self.update_display(is_new_data=True, mode=mode)

    def update_display(self, is_new_data=False, mode="1d"):
        if mode == "1d":
            if getattr(self, 'raw_1d_data', None) is None: return
            
            disp_data = self.raw_1d_data.astype(np.float64).copy()
            
            if self.radio_bg_on.isChecked() and self.loaded_bg_data is not None:
                if len(disp_data) == len(self.loaded_bg_data):
                    disp_data = disp_data - self.loaded_bg_data
            
            if self.chk_flip_x.isChecked():
                disp_data = disp_data[::-1]
                
            self.latest_1d_data = disp_data 
            self.stacked_widget.setCurrentIndex(0)
            
            x_data = self.get_x_axis(len(disp_data))
            
            min_x = np.min(x_data)
            max_x = np.max(x_data)
            
            # Plot design
            self.plot_widget.getViewBox().setLimits(xMin=min_x, xMax=max_x)
            self.plot_widget.getViewBox().setDefaultPadding(0)
            self.plot_widget.setClipToView(True)
            
            self.plot_scatter.setData(x_data, disp_data)
            
            if self.chk_rescale_x.isChecked():
                self.plot_widget.getViewBox().enableAutoRange(axis=pg.ViewBox.XAxis)
            else:
                self.plot_widget.getViewBox().disableAutoRange(axis=pg.ViewBox.XAxis)
                
            if self.chk_rescale_y.isChecked():
                self.plot_widget.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis)
            else:
                self.plot_widget.getViewBox().disableAutoRange(axis=pg.ViewBox.YAxis)
            
            do_fit = self.radio_fit_on.isChecked()
            is_save_frame = False
            if getattr(self, 'is_sequential_running', False) and is_new_data:
                is_save_frame = (self.current_skip_count >= self.spin_skip_frames.value())
                if getattr(self, '_seq_fit_failed', False) and not is_save_frame:
                    do_fit = False
            
            if do_fit:
                func = self.combo_fit_func.currentText()
                fit_start = self.spin_fit_start.value()
                fit_end = self.spin_fit_end.value()
                
                x_fit, y_fit, res = self.analyzer.fit_spectrum(x_data, disp_data, func, fit_start, fit_end)
                
                if x_fit is not None:
                    self._seq_fit_failed = False
                    self.fit_curve.setData(x_fit, y_fit)
                    
                    w_peak1 = res['Peak1'] if res.get('is_double') else res['Peak']
                    w_err1 = res['Peak1_Err'] if res.get('is_double') else res['Peak_Err']
                    
                    self.current_w_peak1 = w_peak1
                    
                    if res.get("is_double"):
                        if "y_fit1" in res and "y_fit2" in res:
                            self.fit_curve_sub1.setData(x_fit, res["y_fit1"])
                            self.fit_curve_sub2.setData(x_fit, res["y_fit2"])
                        else:
                            self.fit_curve_sub1.clear()
                            self.fit_curve_sub2.clear()
                    else:
                        self.fit_curve_sub1.clear()
                        self.fit_curve_sub2.clear()
                    
                    text = f"<span><b>Function:</b> {func}<br><br>"
                    
                    self.latest_fit_res = res.copy()
                    self.latest_fit_func = func
                    
                    if res.get("is_double"):
                        w_peak2 = res['Peak2']
                        w_err2 = res['Peak2_Err']
                        
                        text += f"<u>Peak 1 (Main)</u><br>"
                        text += f" Pos: {w_peak1:.3f} ± {w_err1:.3f}<br>"
                        text += f" Width: {res['Width1']:.3f} ± {res['Width1_Err']:.3f}<br><br>"
                        text += f"<u>Peak 2 (Sub)</u><br>"
                        text += f" Pos: {w_peak2:.3f} ± {w_err2:.3f}<br>"
                        text += f" Width: {res['Width2']:.3f} ± {res['Width2_Err']:.3f}<br><br>"
                    else:
                        text += f"<u>Peak 1</u><br>"
                        text += f" Pos: {w_peak1:.3f} ± {w_err1:.3f}<br>"
                        text += f" Width: {res['Width']:.3f} ± {res['Width_Err']:.3f}<br><br>"

                    text += f"<b>R-value:</b><br> {res['R2']:.4f}</span>"

                    
                    is_double_fit = res.get("is_double")
                    
                    
                    if self.pressure_window is not None and self.pressure_window.isVisible():
                        self.pressure_window.set_current_peak(w_peak1, w_err1)
                        text += f"<br><br><span>CalculatedPressure:<br>{self.pressure_window.current_pressure:.3f} ± {self.pressure_window.current_pressure_err:.3f} {self.pressure_window.unit}</span>"
                    

                        
                        
                        

                    self.fitting_text.setHtml(text)
                else:
                    self.fit_curve.clear()
                    self.fit_curve_sub1.clear()
                    self.fit_curve_sub2.clear()
                    self.current_w_peak1 = None
                    self.latest_fit_res = None
                    self.latest_fit_func = None
                    self.fitting_text.setHtml("<span>Fitting failed or out of range.</span>")
                    
                    if getattr(self, 'is_sequential_running', False):
                        self._seq_fit_failed = True
                    else:
                        self.radio_fit_off.setChecked(True) 
            else:
                self.fit_curve.clear()
                self.fit_curve_sub1.clear()
                self.fit_curve_sub2.clear()
                self.current_w_peak1 = None
                self.latest_fit_res = None
                self.latest_fit_func = None
                if self.radio_fit_on.isChecked():
                     self.fitting_text.setHtml("<span>Fitting failed. Paused for skipped frames.</span>")
                else:
                     self.fitting_text.setHtml("")

        elif mode == "2d":
            if getattr(self, 'raw_2d_data', None) is None: return
            disp_data = self.raw_2d_data.copy()
            if self.chk_flip_x.isChecked():
                disp_data = disp_data[:, ::-1]
                
            self.latest_2d_data = disp_data 
            self.stacked_widget.setCurrentIndex(1)
            self.image_view.setImage(disp_data.T)

        if getattr(self, 'is_sequential_running', False) and is_new_data:
            if self.current_skip_count >= self.spin_skip_frames.value():
                now_dt = datetime.now()
                date_str = now_dt.strftime("%Y%m%d_%H%M%S_%f")[:-3]
                filename = f"seq_{self.seq_count:05d}_{date_str}.txt"
                file_path = os.path.join(self.seq_dir, filename)
                
                success = self._save_data_to_path(file_path, show_msg=False)
                if success:
                    self.seq_log_data.append([filename, now_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]])
                    
                    if self.radio_fit_on.isChecked() and getattr(self, 'seq_fitting_summary_path', None):
                        is_double = "Double" in self.combo_fit_func.currentText()
                        
                        
                        res = self.latest_fit_res
                        cols = [filename, date_str]
                        
                        if res is None:
                            cols.extend(["NaN"] * (9 if is_double else 5))
                        else:
                            if is_double:
                                cols.extend([
                                    f"{res.get('Peak1', np.nan):.6f}", f"{res.get('Peak1_Err', np.nan):.6f}",
                                    f"{res.get('Width1', np.nan):.6f}", f"{res.get('Width1_Err', np.nan):.6f}",
                                    f"{res.get('Peak2', np.nan):.6f}", f"{res.get('Peak2_Err', np.nan):.6f}",
                                    f"{res.get('Width2', np.nan):.6f}", f"{res.get('Width2_Err', np.nan):.6f}",
                                    f"{res.get('R2', np.nan):.6f}"
                                ])
                            else:
                                cols.extend([
                                    f"{res.get('Peak', np.nan):.6f}", f"{res.get('Peak_Err', np.nan):.6f}",
                                    f"{res.get('Width', np.nan):.6f}", f"{res.get('Width_Err', np.nan):.6f}",
                                    f"{res.get('R2', np.nan):.6f}"
                                ])
                        
                        try:
                            with open(self.seq_fitting_summary_path, "a", encoding="utf-8") as f:
                                f.write(",".join(cols) + "\n")
                        except Exception as e:
                            print(f"Failed to write summary: {e}")

                    self.current_skip_count = 0
                    self.seq_count += 1
                    self.update_seq_progress()
                    if self.seq_count >= self.spin_max_num.value():
                        self.stop_sequential()
                else:
                    self.current_skip_count = 0
            else:
                self.current_skip_count += 1

    def on_mouse_moved(self, pos):
        try:
            if self.stacked_widget.currentIndex() == 0:
                vb = self.plot_widget.plotItem.vb
                if vb.sceneBoundingRect().contains(pos):
                    mouse_point = vb.mapSceneToView(pos)
                    x_val = mouse_point.x()
                    
                    x_pixel = int(np.round(x_val))
                    if self.calib_coeffs is not None:
                        x_arr = self.get_x_axis(len(self.latest_1d_data))
                        disp_idx = np.argmin(np.abs(x_arr - x_val))
                    else:
                        disp_idx = x_pixel
                        
                    data_val_str = ""
                    if self.latest_1d_data is not None and 0 <= disp_idx < len(self.latest_1d_data):
                        counts = self.latest_1d_data[disp_idx]
                        data_val_str = f", Counts: {counts:.1f}"
                        
                    unit = "Wavelength" if not self.radio_spec_mode_raman.isChecked() else "Raman shift"
                    unit_sym = "nm" if not self.radio_spec_mode_raman.isChecked() else "cm⁻¹"
                        
                    if self.calib_coeffs is not None:
                        self.coord_label.setText(f"1D Spectrum - {unit}: {x_val:.3f} {unit_sym} (Pixel: {disp_idx}){data_val_str}")
                    else:
                        self.coord_label.setText(f"1D Spectrum - Pixel: {x_val:.1f}{data_val_str}")
                        
            elif self.stacked_widget.currentIndex() == 1:
                view = self.image_view.getView()
                vb = view.vb if hasattr(view, 'vb') else view 
                if vb.sceneBoundingRect().contains(pos):
                    mouse_point = vb.mapSceneToView(pos)
                    x_pixel = int(np.round(mouse_point.x()))
                    y_pixel = int(np.round(mouse_point.y()))
                    data_val_str = ""
                    if self.latest_2d_data is not None:
                        h, w = self.latest_2d_data.shape
                        if 0 <= x_pixel < w and 0 <= y_pixel < h:
                            intensity = self.latest_2d_data[y_pixel, x_pixel]
                            data_val_str = f", Intensity: {intensity:.1f}"
                    self.coord_label.setText(f"2D Image Cursor - X: {x_pixel}, Y: {y_pixel}{data_val_str}")
        except: pass

    def closeEvent(self, event):
        self.thread.stop_thread()
        self.spec_ctrl.close()
        event.accept()

def print_software_and_author_info(): 
    print(
        "\n================================================================================\n================================================================================\n"\
        "FluoraPressée: Spectrometer Control & Analysis for high-pressure experiments\nHiroki Kobayashi (The University of Tokyo), 2026\n"\
        "https://github.com/khsacc/AndorPy\n"\
        "================================================================================\n================================================================================\n"
    )

def check_and_create_config():
    config_path = "spectrometerConfig.json"
    default_config = {
        "grating": [
            {
                "index": 1,
                "grooves": 600,
                "defaultROI": {"from": 100, "to": 140}
            },
            {
                "index": 2,
                "grooves": 1200,
                "defaultROI": {"from": 100, "to": 140}
            },
            {
                "index": 3,
                "grooves": 1800,
                "defaultROI": {"from": 100, "to": 140}
            }
        ],
        "flip_x": False
    }
    
    if not os.path.exists(config_path):
        app_temp = QApplication.instance()
        if not app_temp:
            app_temp = QApplication(sys.argv)
            
        text, ok = QInputDialog.getText(
            None, 
            "Spectrometer Configuration", 
            "spectrometerConfig.json not found.\nPlease enter the gratings (grooves/mm) separated by commas\n(e.g., 600, 1200, 1800):"
        )
        
        gratings_int = []
        if ok and text:
            gratings_str = [g.strip() for g in text.split(",") if g.strip()]
            for g in gratings_str:
                try:
                    gratings_int.append(int(g))
                except ValueError:
                    pass
                    
        if gratings_int:
            new_grating = []
            for i, g_val in enumerate(gratings_int):
                new_grating.append({
                    "index": i + 1,
                    "grooves": g_val,
                    "defaultROI": {"from": 100, "to": 140}
                })
            default_config["grating"] = new_grating
            
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
        except Exception as e:
            QMessageBox.warning(None, "Warning", f"Failed to save config file:\n{e}")


if __name__ == "__main__":
    print_software_and_author_info()
    check_and_create_config()
    
    debug_mode = "--debug" in sys.argv
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    window = SpectrometerGUI(debug=debug_mode)
    window.show()
    sys.exit(app.exec())