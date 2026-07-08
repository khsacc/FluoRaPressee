import numpy as np


class AcquisitionMixin:
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
            poly = c0 + c1 * x + c2 * x**2  # units: nm or cm⁻¹ depending on calib_unit

            calib_is_raman = getattr(self, 'calib_unit', 'Wavelength') == 'Raman shift'
            display_is_raman = self.radio_spec_mode_raman.isChecked()

            if calib_is_raman == display_is_raman:
                return poly  # same units, no conversion needed

            laser_wl = getattr(self, 'calib_laser_wl', None) or self.spin_exc_wl.value()

            if not calib_is_raman and display_is_raman:
                # poly is nm → convert to Raman shift (cm⁻¹)
                # Raman shift of 0 is physically valid (laser line); negative is anti-Stokes.
                # Only nan/inf (from poly ≤ 0, i.e. invalid nm) need masking.
                if laser_wl > 0:
                    with np.errstate(divide='ignore', invalid='ignore'):
                        rs = 1e7 / laser_wl - 1e7 / poly
                    return np.where(np.isfinite(rs), rs, np.nan)
                return poly
            else:
                # poly is Raman shift (cm⁻¹) → convert to nm
                # wavelength must be positive; nan for out-of-range pixels
                if laser_wl > 0:
                    with np.errstate(divide='ignore', invalid='ignore'):
                        denom = 1e7 / laser_wl - poly
                        wl = np.where(denom != 0, 1e7 / denom, np.nan)
                    return np.where(wl > 0, wl, np.nan)
                return poly
        return x

    def on_exposure_changed(self):
        val = self.spin_acq_time.value()
        self.spin_acq_time.setEnabled(False)
        self.thread.update_exposure(val)

    def on_temperature_changed(self):
        val = self.spin_cooler_temp.value()
        self.spin_cooler_temp.setEnabled(False)
        self.thread.update_temperature(val)

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

    def on_roi_spin_changed(self):
        self.apply_roi_settings()

        for g in self.config.get("grating", []):
            if str(g.get("grooves")) == self.physical_grating:
                g.setdefault("defaultROI", {})["from"] = self.spin_vstart.value()
                g.setdefault("defaultROI", {})["to"] = self.spin_vend.value()
                break
        self.save_config_to_file()

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
            # Stray frame that arrived after the thread was told to stop measuring
            # (the camera thread may already be mid-acquisition when stop_measuring()
            # is called) - ignore it rather than accumulating/displaying/saving it.
            return

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
