import os
from datetime import datetime
import numpy as np
from PyQt5.QtWidgets import QFileDialog, QMessageBox

class FileIOMixin:
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

    def handle_bg_mismatch_and_run(self, callback) -> bool:
        """Returns True if callback was actually invoked, False if the user declined (Quit)."""
        if not self.check_bg_mismatch():
            callback()
            return True

        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Icon.Warning)
        msgBox.setWindowTitle("Background Mismatch")
        msgBox.setText("Current measurement settings do not match the loaded background.\nPlease close the shutter and acquire a new background, or ignore to continue.")

        btn_ignore = msgBox.addButton("Ignore and continue", QMessageBox.ButtonRole.ActionRole)
        msgBox.addButton("Quit", QMessageBox.ButtonRole.RejectRole)

        msgBox.exec()

        if msgBox.clickedButton() == btn_ignore:
            callback()
            return True
        return False

    def check_bg_and_take_single(self):
        if not self._try_acquire_gate():
            QMessageBox.warning(self, "Busy", "Another acquisition is already in progress.")
            return
        if not self.handle_bg_mismatch_and_run(self.take_single_spectrum):
            self._release_acquisition_gate()

    def check_bg_and_start_meas(self):
        if not self._try_acquire_gate():
            QMessageBox.warning(self, "Busy", "Another acquisition is already in progress.")
            return
        if not self.handle_bg_mismatch_and_run(self.start_measurement):
            self._release_acquisition_gate()

    def check_bg_and_start_seq(self):
        if not self._try_acquire_gate():
            QMessageBox.warning(self, "Busy", "Another acquisition is already in progress.")
            return
        if not self.handle_bg_mismatch_and_run(self.start_sequential):
            self._release_acquisition_gate()

    def apply_calibration(self, coeffs, filename, calib_unit='Wavelength', calib_laser_wl=None):
        self.calib_coeffs = coeffs
        self.calib_unit = calib_unit
        self.calib_laser_wl = calib_laser_wl
        self.calib_file_name = filename
        self.lbl_loaded_calib.setText(f"Loaded: {filename}")
        self.update_plot_labels()
        self.sync_fit_range_to_spectrum(force=True)

        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

    def on_load_calibration(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Configuration", self._last_calib_dir, "JSON Files (*.json)")
        if not file_path:
            return
        self._last_calib_dir = os.path.dirname(file_path)
        self._save_local_cache("last_calib_dir", self._last_calib_dir)

        try:
            cfg = self.file_io.load_calibration_config(file_path)
        except Exception as e:
            self._loading_config = False
            self._pending_calib_coeffs = None
            QMessageBox.warning(self, "Error", f"Failed to load configuration:\n{e}")
            return

        # For Raman shift calibrations the excitation wavelength is embedded in the
        # polynomial coefficients; a mismatch means every x-axis value will be wrong.
        if cfg.get("calibration_unit") == "Raman shift":
            saved_exc_wl = cfg.get("exc_wl")
            if saved_exc_wl is None:
                QMessageBox.critical(self, "Invalid File",
                    "This calibration file does not contain an excitation wavelength.\n"
                    "Cannot load a Raman shift calibration without it.")
                return
            current_exc_wl = self.spin_exc_wl.value()
            if abs(saved_exc_wl - current_exc_wl) > 1e-6:
                QMessageBox.critical(self, "Excitation Wavelength Mismatch",
                    f"This calibration was created with an excitation wavelength of "
                    f"{saved_exc_wl:.6f} nm, but the current setting is {current_exc_wl:.6f} nm.\n\n"
                    f"Please set the excitation wavelength to exactly {saved_exc_wl:.6f} nm before loading.")
                return

        if "2D" in cfg["mode"]:
            self.radio_2d.setChecked(True)
        elif "Full" in cfg["mode"]:
            self.radio_1d_full.setChecked(True)
        else:
            self.radio_1d_roi.setChecked(True)

        self.spin_vstart.blockSignals(True)
        self.spin_vend.blockSignals(True)
        self.spin_vstart.setValue(cfg["roi_start"])
        self.spin_vend.setValue(cfg["roi_end"])
        self.spin_vstart.blockSignals(False)
        self.spin_vend.blockSignals(False)
        self.apply_roi_settings()

        self.radio_spec_mode_raman.blockSignals(True)
        self.radio_spec_mode_wl.blockSignals(True)
        if cfg["display_mode"] == "Raman shift":
            self.radio_spec_mode_raman.setChecked(True)
            self.lbl_centre.setText("Centre (cm⁻¹):")
        else:
            self.radio_spec_mode_wl.setChecked(True)
            self.lbl_centre.setText("Centre (nm):")
        self.radio_spec_mode_raman.blockSignals(False)
        self.radio_spec_mode_wl.blockSignals(False)

        cb_idx = self.combo_grating.findText(cfg["grating"])
        if cb_idx >= 0:
            self.combo_grating.setCurrentIndex(cb_idx)

        # cfg["center"] is always in nm; convert to Raman shift if needed for the spin box
        center_nm = cfg["center"]
        if cfg["display_mode"] == "Raman shift":
            ex_wl = self.spin_exc_wl.value()
            if ex_wl > 0 and center_nm > 0:
                center_for_spinbox = 1e7 / ex_wl - 1e7 / center_nm
            else:
                center_for_spinbox = 0.0
        else:
            center_for_spinbox = center_nm
        self.spin_centre_wl.setValue(center_for_spinbox)

        self._loading_config = True
        self._pending_calib_coeffs = (cfg["c0"], cfg["c1"], cfg["c2"])
        self._pending_calib_filename = os.path.basename(file_path)
        self._pending_calib_unit = cfg.get("calibration_unit", "Wavelength")
        self._pending_calib_laser_wl = (cfg.get("exc_wl")
                                        if cfg.get("calibration_unit") == "Raman shift"
                                        else None)

        self.on_apply_spectrometer()

    def on_acq_bg_clicked(self):
        if not self._try_acquire_gate():
            QMessageBox.warning(self, "Busy", "Another acquisition is already in progress.")
            return
        self._is_acquiring_bg = True
        self.is_single_shot = True
        self._ignore_next_frames = False
        self.current_accum_count = 0
        self.btn_single.setEnabled(False)
        self.btn_commence.setEnabled(False)
        self._set_button_style(self.btn_commence, self.BUTTON_STYLE_GREEN)
        self.btn_terminate.setEnabled(True)
        self._set_button_style(self.btn_terminate, self.BUTTON_STYLE_RED)
        self.thread.start_measuring()

    def _process_acquired_bg(self):
        if getattr(self, 'raw_1d_data', None) is None:
            QMessageBox.warning(self, "Error", "No 1D data available for background.")
            return

        acq_time = self.spin_acq_time.value()
        accum = self.spin_accumulate.value()
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_str = "1D Spectrum (Custom ROI)" if self.radio_1d_roi.isChecked() else "1D Spectrum (Full Range Binning)"
        roi_str = f"_ROI_from_{self.spin_vstart.value()}_to_{self.spin_vend.value()}" if self.radio_1d_roi.isChecked() else "_full"
        default_filename = f"background_{date_str}{roi_str}.txt"
        initial_path = os.path.join(self._last_save_dir, default_filename) if self._last_save_dir else default_filename

        file_path, _ = QFileDialog.getSaveFileName(self, "Save Background Data", initial_path, "Text/JSON Files (*.txt *.json)")
        if not file_path:
            return
        self._last_save_dir = os.path.dirname(file_path)
        self._save_local_cache("last_save_dir", self._last_save_dir)

        try:
            bg_arr, bg_meta = self.file_io.save_background(
                file_path, self.raw_1d_data,
                acq_time, accum, mode_str,
                self.spin_vstart.value(), self.spin_vend.value(),
                self.label_current_temp.text()
            )
            QMessageBox.information(self, "Success", "Background saved successfully.")
            self.loaded_bg_data = bg_arr
            self.loaded_bg_metadata = bg_meta
            self.lbl_loaded_bg.setText(f"Loaded: {os.path.basename(file_path)}")
            self.radio_bg_on.setChecked(True)
            self.on_fit_settings_changed()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save background:\n{e}")

    def on_load_bg_clicked(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Background Data", self._last_save_dir, "Text/JSON Files (*.txt *.json)")
        if file_path:
            self._last_save_dir = os.path.dirname(file_path)
            self._save_local_cache("last_save_dir", self._last_save_dir)
            try:
                bg_arr, bg_meta = self.file_io.load_background(file_path)
                self.loaded_bg_data = bg_arr
                self.loaded_bg_metadata = bg_meta
                self.lbl_loaded_bg.setText(f"Loaded: {os.path.basename(file_path)}")
                self.radio_bg_on.setChecked(True)
                self.on_fit_settings_changed()
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load background:\n{e}")

    def on_save_data_clicked(self):
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        default_filename = f"data_{date_str}.txt"
        initial_path = os.path.join(self._last_save_dir, default_filename) if self._last_save_dir else default_filename
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Data", initial_path, "Text Files (*.txt);;All Files (*)")
        if file_path:
            self._last_save_dir = os.path.dirname(file_path)
            self._save_local_cache("last_save_dir", self._last_save_dir)
            self._save_data_to_path(file_path, show_msg=True)

    def _save_data_to_path(self, file_path, show_msg=True):
        is_1d = self.stacked_widget.currentIndex() == 0
        if is_1d and self.latest_1d_data is None:
            if show_msg:
                QMessageBox.warning(self, "Error", "No 1D data available to save.")
            return False
        if not is_1d and self.latest_2d_data is None:
            if show_msg:
                QMessageBox.warning(self, "Error", "No 2D data available to save.")
            return False

        try:
            metadata = {
                "grating":      self.combo_grating.currentText(),
                "center_wl":    self.spin_centre_wl.value(),
                "acq_time":     self.spin_acq_time.value(),
                "accum":        self.spin_accumulate.value(),
                "calib_coeffs": self.calib_coeffs,
                "roi_start":    self.spin_vstart.value(),
                "roi_end":      self.spin_vend.value(),
                "mode":         "2D" if self.radio_2d.isChecked() else "1D (Full)" if self.radio_1d_full.isChecked() else "1D (ROI)",
                "spec_mode":    "Raman shift" if self.radio_spec_mode_raman.isChecked() else "Wavelength",
                "exc_wl":       self.spin_exc_wl.value(),
            }

            if is_1d:
                x_data = self.get_x_axis(len(self.latest_1d_data))
                if self.chk_flip_x.isChecked() and self.calib_coeffs is not None:
                    x_data = x_data[::-1]
                raw_data = None
                bg_data = None
                if self.radio_bg_on.isChecked() and self.loaded_bg_data is not None:
                    if len(self.raw_1d_data) == len(self.loaded_bg_data):
                        raw_data = self.raw_1d_data.astype(np.float64)
                        bg_data = self.loaded_bg_data.astype(np.float64)
                        if self.chk_flip_x.isChecked():
                            raw_data = raw_data[::-1]
                            bg_data = bg_data[::-1]
                self.file_io.save_spectrum_1d(file_path, x_data, self.latest_1d_data, metadata,
                                              raw_data=raw_data, bg_data=bg_data)

                if self.chk_save_fitting.isChecked() and self.radio_fit_on.isChecked() and self.latest_fit_res is not None:
                    fit_file_path = file_path.rsplit('.', 1)[0] + "_fitting_results.txt"
                    pressure_info = None
                    pw = self.pressure_window
                    if pw is not None and pw.isVisible() and pw.current_pressure is not None:
                        lam0_value = pw.current_zero_peak_at_current_t
                        if lam0_value is None:
                            lam0_value = pw.spin_lam0_t0.value() if pw.radio_on.isChecked() else pw.spin_lam0.value()
                        pressure_info = {
                            "pressure":     pw.current_pressure,
                            "pressure_err": pw.current_pressure_err,
                            "scale":        pw.combo_p_scale.currentText(),
                            "sensor":       pw.combo_sensor.currentText(),
                            "lam0":         lam0_value,
                            "lam0_unit":    pw.unit,
                        }
                    self.file_io.save_fitting_results(fit_file_path, self.latest_fit_res,
                                                      getattr(self, 'latest_fit_func', 'Unknown'),
                                                      pressure_info=pressure_info)
            else:
                self.file_io.save_spectrum_2d(file_path, self.latest_2d_data, metadata)

            if show_msg:
                QMessageBox.information(self, "Success", f"Data saved successfully to:\n{file_path}")
            return True
        except Exception as e:
            if show_msg:
                QMessageBox.critical(self, "Error", f"Failed to save data:\n{e}")
            else:
                print(f"Sequential save error: {e}")
            return False
