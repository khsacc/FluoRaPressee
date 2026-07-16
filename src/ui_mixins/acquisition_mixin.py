import numpy as np
from PyQt5.QtWidgets import QMessageBox

from src.accumulation import AccumulationCombiner

# Cap on how many raw frames we buffer in memory for spike rejection (list of
# individual frames instead of an O(1) running sum). ~16MB worst case for a
# 1024-pixel 1D spectrum. Accumulation counts above this fall back to the
# legacy plain-sum path (no rejection) rather than risking unbounded memory,
# since spin_accumulate allows values up to 99999.
MAX_BUFFERED_FRAMES = 2000


class AcquisitionMixin:
    def _try_acquire_gate(self) -> bool:
        """測定権の排他ゲートを非ブロッキングで取得する。既に誰かが握っていれば False を返す。"""
        if self._acquisition_gate.acquire(blocking=False):
            self._gate_held_by_me = True
            return True
        return False

    def _release_acquisition_gate(self) -> None:
        """自分が取得したゲートを解放する（保持していなければ何もしない、二重解放を防止）。"""
        if getattr(self, '_gate_held_by_me', False):
            self._gate_held_by_me = False
            self._acquisition_gate.release()

    def take_single_spectrum(self):
        self.is_single_shot = True
        self._ignore_next_frames = False
        self.current_accum_count = 0
        self.btn_single.setEnabled(False)
        self.btn_commence.setEnabled(False)
        self._set_button_style(self.btn_commence, self.BUTTON_STYLE_GREEN)
        self.btn_terminate.setEnabled(True)
        self._set_button_style(self.btn_terminate, self.BUTTON_STYLE_RED)
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

    def on_em_gain_info_ready(self, exists, available, minimum, maximum, increment, current):
        """Render the EM Gain row only when PICam says the parameter exists."""
        self.label_em_gain.setVisible(exists)
        self.spin_em_gain.setVisible(exists)
        self._em_gain_available = bool(exists and available)
        if not exists:
            self.spin_em_gain.setEnabled(False)
            return

        self.spin_em_gain.blockSignals(True)
        if available:
            self.spin_em_gain.setRange(minimum, maximum)
            self.spin_em_gain.setSingleStep(max(1, increment))
            self.spin_em_gain.setValue(current)
            self.spin_em_gain.setToolTip(
                "Electron-multiplication gain reported by the connected camera.\n"
                "Changing this value selects the Electron Multiplied ADC quality."
            )
        else:
            self.spin_em_gain.setToolTip(
                "The camera has an EM Gain parameter, but it is not available "
                "with the current camera/readout settings."
            )
        self.spin_em_gain.blockSignals(False)
        self.spin_em_gain.setEnabled(
            self._em_gain_available and not self._ui_lock_reasons
        )

    def on_em_gain_changed(self):
        if not self._em_gain_available:
            return
        self.spin_em_gain.setEnabled(False)
        self.thread.update_em_gain(self.spin_em_gain.value())

    def on_em_gain_set_finished(self, actual_gain):
        self.spin_em_gain.blockSignals(True)
        self.spin_em_gain.setValue(actual_gain)
        self.spin_em_gain.blockSignals(False)
        self.spin_em_gain.setEnabled(
            self._em_gain_available and not self._ui_lock_reasons
        )

    def on_temperature_changed(self):
        val = self.spin_cooler_temp.value()
        self.spin_cooler_temp.setEnabled(False)
        self.thread.update_temperature(val)

    def on_temperature_set_finished(self, actual_temperature):
        """Reflect the set point that the camera accepted, not only the requested value."""
        self.spin_cooler_temp.blockSignals(True)
        self.spin_cooler_temp.setValue(round(actual_temperature))
        self.spin_cooler_temp.blockSignals(False)
        self.spin_cooler_temp.setEnabled(not self._ui_lock_reasons)

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
        self._set_button_style(self.btn_commence, self.BUTTON_STYLE_GREEN)
        self.btn_single.setEnabled(True)

        self.status_label.setText("Camera Ready")

        self.spin_vstart.setMaximum(self.thread.det_height - 1)
        self.spin_vend.setMaximum(self.thread.det_height)

        self.radio_2d.setText(f"2D Image View ({self.thread.det_width}x{self.thread.det_height})")
        self.apply_roi_settings()

    def on_hardware_error(self, message):
        self.status_label.setText(f"Camera error: {message}")
        QMessageBox.warning(self, "Camera Error", message)

    def on_camera_init_failed(self, reason):
        self.init_dialog.reject()
        self.centralWidget().setEnabled(True)

        self.btn_commence.setEnabled(False)
        self.btn_single.setEnabled(False)

        self.status_label.setText("Camera initialization failed")
        QMessageBox.critical(
            self, "Camera Initialization Failed",
            f"Failed to initialize the camera:\n\n{reason}"
        )

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
        self._set_button_style(self.btn_commence, self.BUTTON_STYLE_GREEN)
        self.btn_terminate.setEnabled(True)
        self._set_button_style(self.btn_terminate, self.BUTTON_STYLE_RED)
        self.thread.start_measuring()

    def stop_measurement(self):
        self.btn_single.setEnabled(True)
        self.btn_commence.setEnabled(True)
        self._set_button_style(self.btn_commence, self.BUTTON_STYLE_GREEN)
        self.btn_terminate.setEnabled(False)
        self._set_button_style(self.btn_terminate, self.BUTTON_STYLE_RED)
        self.lbl_accum_status.setVisible(False)
        self.thread.stop_measuring()
        self._release_acquisition_gate()

    def on_acquisition_failed(self, error_msg):
        """Camera thread auto-stopped acquisition after repeated hardware errors.

        Without this handler the GUI would silently stay in a "measuring" state
        forever (buttons still showing Terminate as active) with no indication
        that data collection actually halted - dangerous for unattended
        Sequential runs that may go for hours.
        """
        was_sequential = getattr(self, 'is_sequential_running', False)

        self.current_accum_count = 0
        self.accumulated_data = None
        self.accum_frames = None
        self.is_single_shot = False

        if was_sequential:
            self.stop_sequential()
        else:
            self.stop_measurement()

        # stop_sequential() only relays to stop_measurement() (which releases the gate) when
        # thread.is_measuring is still True; but the camera thread already sets is_measuring to
        # False internally before emitting this signal, so that relay is skipped here. Release
        # explicitly as a backstop (no-op if already released by the stop_measurement() call above).
        self._release_acquisition_gate()

        self.status_label.setText("Camera Error: acquisition stopped")
        QMessageBox.critical(
            self, "Acquisition Stopped",
            "Data acquisition failed repeatedly and was stopped automatically.\n\n"
            f"Last error: {error_msg}\n\n"
            "Check the camera connection/hardware before starting a new measurement."
        )

    def on_cosmic_ray_removal_toggled(self, checked):
        self.spin_spike_threshold.setEnabled(checked)

    def on_data_ready(self, mode, data):
        if not getattr(self.thread, 'is_measuring', False) and not self.is_single_shot:
            # Stray frame that arrived after the thread was told to stop measuring
            # (the camera thread may already be mid-acquisition when stop_measuring()
            # is called) - ignore it rather than accumulating/displaying/saving it.
            return

        if self._ignore_next_frames:
            return

        target_accum = self._active_target_accum if self._active_target_accum is not None else self.spin_accumulate.value()

        if self.current_accum_count == 0:
            # Decide the combine strategy once per cycle, at the first frame, so a
            # mid-cycle checkbox toggle can't desync accum_frames vs accumulated_data.
            self._accum_use_rejection = (
                mode == "1d"
                and self.chk_cosmic_ray_removal.isChecked()
                and AccumulationCombiner.MIN_FRAMES_FOR_REJECTION <= target_accum <= MAX_BUFFERED_FRAMES
            )
            if self._accum_use_rejection:
                self.accum_frames = [data.astype(np.float64).copy()]
                self.accumulated_data = None
            else:
                if (self.chk_cosmic_ray_removal.isChecked() and mode == "1d"
                        and not (AccumulationCombiner.MIN_FRAMES_FOR_REJECTION <= target_accum <= MAX_BUFFERED_FRAMES)):
                    print("[Cosmic ray removal] skipped: accumulation count out of range "
                          f"({AccumulationCombiner.MIN_FRAMES_FOR_REJECTION}-{MAX_BUFFERED_FRAMES}).")
                self.accum_frames = None
                self.accumulated_data = data.astype(np.float64).copy()
        else:
            if self._accum_use_rejection:
                self.accum_frames.append(data.astype(np.float64).copy())
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

            if self._accum_use_rejection:
                threshold_k = self.spin_spike_threshold.value()
                final_data, n_spikes = AccumulationCombiner.combine(
                    self.accum_frames, reject_spikes=True, threshold_k=threshold_k
                )
                self.accum_frames = None
                if n_spikes > 0:
                    print(f"[Cosmic ray removal] {n_spikes} spike value(s) rejected "
                          f"over {target_accum} accumulated frames (threshold={threshold_k}σ).")
                    self.lbl_accum_status.setText(
                        f"Acquired: {target_accum} / {target_accum} ({n_spikes} spikes rejected)"
                    )
                    self.lbl_accum_status.setVisible(True)
            else:
                final_data = self.accumulated_data.copy()
                self.accumulated_data = None

            self._process_completed_data(mode, final_data)

    def _process_completed_data(self, mode, data):
        if self.is_single_shot:
            self.is_single_shot = False
            # stop_measurement() (called from on_data_ready() just before this method, for the
            # single-shot completion path) already releases the gate; call again defensively in
            # case that call path ever changes so a single-shot completion never leaves it stuck.
            self._release_acquisition_gate()
            # Reset any API-supplied accumulation override so the next GUI-triggered
            # acquisition goes back to reading spin_accumulate.value().
            self._active_target_accum = None

            if mode == "1d":
                self.raw_1d_data = data
            elif mode == "2d":
                self.raw_2d_data = data

            pending = getattr(self, '_api_pending_future', None)
            if pending is not None:
                self._api_pending_future = None
                if not pending.done():
                    pending.set_result({
                        "raw": (self.raw_1d_data if mode == "1d" else self.raw_2d_data),
                        "mode": mode,
                    })

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
