import os
from datetime import datetime

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                             QFileDialog, QMessageBox)


class SequentialMixin:
    def _lock_ui(self, reason):
        """Add `reason` to the set of active UI locks and disable the
        measurement/config controls (see set_ui_enabled_during_seq). Multiple
        independent lockers (sequential run, API server) can be active at
        once; the UI only re-enables once all of them have released.
        """
        self._ui_lock_reasons.add(reason)
        self.set_ui_enabled_during_seq(False)

    def _unlock_ui(self, reason):
        self._ui_lock_reasons.discard(reason)
        if len(self._ui_lock_reasons) == 0:
            self.set_ui_enabled_during_seq(True)

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
        self.chk_cosmic_ray_removal.setEnabled(enabled)
        self.spin_spike_threshold.setEnabled(enabled and self.chk_cosmic_ray_removal.isChecked())
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
        start_dir = self.seq_dir if self.seq_dir and os.path.isdir(self.seq_dir) else ""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory for Sequential Data", start_dir)
        if dir_path:
            self.seq_dir = dir_path
            self._save_local_cache("last_seq_dir", dir_path)
            display_path = dir_path if len(dir_path) < 25 else "..." + dir_path[-22:]
            self.lbl_seq_dir.setText(f"Dir: {display_path}")
            if not self.is_sequential_running:
                self.btn_start_seq.setEnabled(True)
                self.btn_start_seq.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")

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

        self._lock_ui("sequential")

        if self.radio_fit_on.isChecked():
            start_date_str = self.seq_start_time_dt.strftime("%Y%m%d_%H%M%S")
            self.seq_fitting_summary_path = os.path.join(self.seq_dir, f"fitting_seq_summary_{start_date_str}.txt")

            func = self.combo_fit_func.currentText()
            fit_start = self.spin_fit_start.value()
            fit_end = self.spin_fit_end.value()
            is_double = "Double" in func


            try:
                unit = "cm-1" if self.radio_spec_mode_raman.isChecked() else "nm"
                has_pressure = (self.pressure_window is not None and self.pressure_window.isVisible())
                self.file_io.create_fitting_seq_summary(
                    self.seq_fitting_summary_path, func, fit_start, fit_end,
                    is_double, unit, has_pressure
                )
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
                    self.file_io.save_sequential_summary(
                        summary_path,
                        self.seq_start_time_dt, seq_end_time_dt,
                        self.spin_acq_time.value(), self.spin_accumulate.value(),
                        self.spin_skip_frames.value(), self.seq_log_data
                    )
                except Exception as e:
                    print(f"Failed to write sequential summary: {e}")

        self.is_sequential_running = False
        self.lbl_seq_progress.setVisible(False)
        self.seq_fitting_summary_path = None

        self.btn_start_seq.setEnabled(True)
        self.btn_start_seq.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.btn_stop_seq.setEnabled(False)
        self.btn_stop_seq.setStyleSheet("background-color: #A0A0A0; color: white; font-weight: bold;")

        self._unlock_ui("sequential")

        if hasattr(self.thread, 'is_measuring') and self.thread.is_measuring:
            self.stop_measurement()

    def toggle_sequential(self, checked):
        self.seq_content.setVisible(checked)
        self.seq_toggle_btn.setText("▼ Sequential measurements" if checked else "▶ Sequential measurements")
