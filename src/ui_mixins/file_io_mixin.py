import os
from datetime import datetime
import numpy as np
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from src.configuration_browser import ConfigurationBrowserDialog
from src.configuration_catalog import (
    ConfigurationError,
    format_configuration_label,
)
from src.measurement_metadata import background_mismatch_fields, build_hardware_metadata, public_axis_kind

class FileIOMixin:
    def check_bg_mismatch(self):
        if not self.radio_bg_on.isChecked() or getattr(self, 'loaded_bg_metadata', None) is None:
            return False

        return bool(background_mismatch_fields(self))

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

    def apply_calibration(
        self, coeffs, label, calib_unit='Wavelength', calib_laser_wl=None,
        axis_source="loaded_configuration", configuration_id=None, slot_id=None,
    ):
        self.calib_coeffs = coeffs
        self.calib_unit = calib_unit
        self.calib_laser_wl = calib_laser_wl
        self.configuration_label = label
        self.active_configuration_id = configuration_id
        self.active_configuration_slot_id = slot_id
        self.positioned_configuration_id = configuration_id
        self.positioned_configuration_slot_id = slot_id
        self.axis_source = axis_source
        self.lbl_loaded_configuration.setText(f"Loaded: {label}")
        self.update_plot_labels()
        self.sync_fit_range_to_spectrum(force=True)

        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

    def clear_active_configuration(self):
        self.calib_coeffs = None
        self.axis_source = "pixel"
        self.calib_unit = "Wavelength"
        self.calib_laser_wl = None
        self.configuration_label = "None"
        self.active_configuration_id = None
        self.active_configuration_slot_id = None
        self.positioned_configuration_id = None
        self.positioned_configuration_slot_id = None
        self.lbl_loaded_configuration.setText("Loaded: None")
        self.update_plot_labels()

    def configuration_hardware_context(self):
        """Return cached hardware facts used by both GUI and future API queries."""
        spec_metadata = {}
        getter = getattr(self.spec_ctrl, "get_cached_hardware_metadata", None)
        if getter is not None:
            spec_metadata = getter() or {}
        configured = self.config.get("hardware_identity", {})
        camera_identity = getattr(self, "_camera_identity", {})
        configured_camera = configured.get("camera", {})
        configured_spectrometer = configured.get("spectrometer", {})
        return {
            "spectrometer_model": (
                spec_metadata.get("model")
                or configured_spectrometer.get("model")
                or self.config.get("model")
            ),
            "spectrometer_serial_number": (
                spec_metadata.get("serial_number")
                or configured_spectrometer.get("serial_number")
            ),
            "camera_model": (
                camera_identity.get("model") or configured_camera.get("model")
            ),
            "camera_serial_number": (
                camera_identity.get("serial_number")
                or configured_camera.get("serial_number")
            ),
            "gratings": [
                {
                    "index": int(item.get("index", index + 1)),
                    "grooves": int(item.get("grooves", 0)),
                }
                for index, item in enumerate(self.config.get("grating", []))
            ],
            "detector_width": getattr(self.thread, "det_width", None),
            "detector_height": getattr(self.thread, "det_height", None),
            "current_grating": spec_metadata.get("grating"),
            "actual_center_wavelength_nm": spec_metadata.get("center_wavelength_nm"),
        }

    def _is_oceanoptics_backend(self):
        """Return True only for the integrated fixed Ocean Optics backend.

        This deliberately uses the configured backend identity instead of inferring from
        generic capabilities.  Other fixed or partially movable instruments must continue
        through their existing grating/centre movement and validation paths unchanged.
        """
        return self.config.get("model") == "OceanOptics"

    def _current_grating_definition(self, hardware_context=None):
        cached_grating = (hardware_context or {}).get("current_grating") or {}
        if (
            cached_grating.get("index") is not None
            and cached_grating.get("grooves_per_mm") is not None
        ):
            return {
                "index": int(cached_grating["index"]),
                "grooves_per_mm": int(cached_grating["grooves_per_mm"]),
            }
        combo_index = self.combo_grating.currentIndex()
        gratings = self.config.get("grating", [])
        if not 0 <= combo_index < len(gratings):
            raise ConfigurationError("The selected grating is not defined in the hardware configuration.")
        item = gratings[combo_index]
        return {
            "index": int(item.get("index", combo_index + 1)),
            "grooves_per_mm": int(item.get("grooves", 0)),
        }

    def _current_roi_definition(self):
        if self.radio_2d.isChecked():
            mode = "2d"
            start, end = 0, int(self.thread.det_height)
        elif self.radio_1d_full.isChecked():
            mode = "1d_full"
            start, end = 0, int(self.thread.det_height)
        else:
            mode = "1d_roi"
            start, end = self.spin_vstart.value(), self.spin_vend.value()
        return {"roi_mode": mode, "roi_start": int(start), "roi_end": int(end)}

    def register_current_configuration(
        self, coeffs, calibration_unit="Wavelength", excitation_wavelength_nm=None
    ):
        """Create a new active record for the current grating/centre/ROI slot."""
        hardware = self.configuration_hardware_context()
        grating = self._current_grating_definition(hardware)
        roi = self._current_roi_definition()
        c0, c1, c2 = coeffs
        draft = {
            "compatibility": {
                "spectrometer_model": hardware["spectrometer_model"],
                "spectrometer_serial_number": hardware["spectrometer_serial_number"],
                "camera_model": hardware["camera_model"],
                "camera_serial_number": hardware["camera_serial_number"],
            },
            "spectrometer": {
                "grating_index": grating["index"],
                "grating_grooves_per_mm": grating["grooves_per_mm"],
                # Slot identity follows the commanded/nominal position. Manual
                # calibration occurs after movement, so physical_center_wl is the
                # stable target rather than a fresh noisy readback.
                "target_center_wavelength_nm": float(self.physical_center_wl),
                "actual_center_wavelength_nm": float(
                    hardware["actual_center_wavelength_nm"]
                    if hardware["actual_center_wavelength_nm"] is not None
                    else self.physical_center_wl
                ),
            },
            "detector": {
                **roi,
                "detector_width": hardware["detector_width"],
                "detector_height": hardware["detector_height"],
            },
            "display": {
                "mode": (
                    "Raman shift" if self.radio_spec_mode_raman.isChecked()
                    else "Wavelength"
                ),
                "excitation_wavelength_nm": float(self.spin_exc_wl.value()),
            },
            "calibration": {
                "source": "neon_polynomial",
                "unit": calibration_unit,
                "excitation_wavelength_nm": (
                    float(excitation_wavelength_nm)
                    if calibration_unit == "Raman shift"
                    else None
                ),
                "coefficients": {
                    "c0": float(c0), "c1": float(c1), "c2": float(c2),
                },
            },
        }
        return self.configuration_catalog.register_configuration(draft)

    def on_load_configuration(self):
        dialog = ConfigurationBrowserDialog(
            self.configuration_catalog,
            self.configuration_hardware_context(),
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            record = self.configuration_catalog.get_configuration(
                dialog.selected_configuration_id
            )
            self.configuration_catalog.assert_compatible(
                record, self.configuration_hardware_context()
            )
            self._prepare_configuration_for_loading(
                record,
                # Ocean Optics' model+serial compatibility was already checked above.
                # It has no movable centre, so a saved display/slot centre must not be
                # sent through SpectrometerMoveThread.  Every other backend retains the
                # previous unconditional GUI move/apply behaviour.
                skip_move=self._is_oceanoptics_backend(),
            )
        except Exception as e:
            self._loading_config = False
            self._pending_calib_coeffs = None
            self._pending_axis_source = None
            QMessageBox.warning(self, "Error", f"Failed to load configuration:\n{e}")
            self._clear_pending_configuration()

    def _apply_pixel_configuration(self, label, configuration_id, slot_id):
        """Keep the configuration's physical state but expose an uncalibrated axis."""
        self.calib_coeffs = None
        self.calib_unit = "Wavelength"
        self.calib_laser_wl = None
        self.configuration_label = label
        self.active_configuration_id = None
        self.active_configuration_slot_id = None
        self.positioned_configuration_id = configuration_id
        self.positioned_configuration_slot_id = slot_id
        self.axis_source = "pixel"
        self.lbl_loaded_configuration.setText(f"Loaded: {label} (pixel axis)")
        self.update_plot_labels()
        self.sync_fit_range_to_spectrum(force=True)
        if (
            getattr(self, "raw_1d_data", None) is not None
            and hasattr(self.thread, "is_measuring")
            and not self.thread.is_measuring
        ):
            self.update_display(is_new_data=False)

    def _configuration_matches_current_state(self, record):
        """Return whether a configuration move would be physically redundant."""
        spectrometer = record["spectrometer"]
        detector = record["detector"]
        try:
            current_grating = self._current_grating_definition(
                self.configuration_hardware_context()
            )
            current_roi = self._current_roi_definition()
            return (
                int(current_grating["index"])
                == int(spectrometer["grating_index"])
                and int(current_grating["grooves_per_mm"])
                == int(spectrometer["grating_grooves_per_mm"])
                and abs(
                    float(self.physical_center_wl)
                    - float(spectrometer["target_center_wavelength_nm"])
                )
                < 5e-4
                and current_roi["roi_mode"] == detector["roi_mode"]
                and int(current_roi["roi_start"]) == int(detector["roi_start"])
                and int(current_roi["roi_end"]) == int(detector["roi_end"])
            )
        except (KeyError, TypeError, ValueError):
            return False

    def _prepare_configuration_for_loading(
        self,
        record,
        *,
        axis_mode="calibrated",
        completion_future=None,
        skip_move=False,
    ):
        detector = record["detector"]
        spectrometer = record["spectrometer"]
        display = record.get("display", {})
        calibration = record["calibration"]

        roi_mode = detector["roi_mode"]
        if roi_mode == "2d":
            self.radio_2d.setChecked(True)
        elif roi_mode == "1d_full":
            self.radio_1d_full.setChecked(True)
        else:
            self.radio_1d_roi.setChecked(True)

        self.spin_vstart.blockSignals(True)
        self.spin_vend.blockSignals(True)
        self.spin_vstart.setValue(detector["roi_start"])
        self.spin_vend.setValue(detector["roi_end"])
        self.spin_vstart.blockSignals(False)
        self.spin_vend.blockSignals(False)
        self.apply_roi_settings()

        self.radio_spec_mode_raman.blockSignals(True)
        self.radio_spec_mode_wl.blockSignals(True)
        excitation_wavelength = display.get("excitation_wavelength_nm")
        if excitation_wavelength is None:
            excitation_wavelength = calibration.get("excitation_wavelength_nm")
        if excitation_wavelength is not None:
            self.spin_exc_wl.setValue(float(excitation_wavelength))

        display_mode = display.get("mode", calibration["unit"])
        if display_mode == "Raman shift":
            self.radio_spec_mode_raman.setChecked(True)
            self.lbl_centre.setText("Centre (cm⁻¹):")
        else:
            self.radio_spec_mode_wl.setChecked(True)
            self.lbl_centre.setText("Centre (nm):")
        self.radio_spec_mode_raman.blockSignals(False)
        self.radio_spec_mode_wl.blockSignals(False)

        cb_idx = next(
            (
                index for index, item in enumerate(self.config.get("grating", []))
                if int(item.get("index", index + 1)) == int(spectrometer["grating_index"])
            ),
            -1,
        )
        if cb_idx < 0:
            raise ConfigurationError("The configuration's grating slot is not available.")
        self.combo_grating.setCurrentIndex(cb_idx)

        # Ocean Optics has no movable centre.  Use its connected native centre for the
        # hidden display widget; the saved centre is metadata, not a position to apply.
        # Movable backends retain the original saved-target path.
        if self._is_oceanoptics_backend():
            center_nm = float(self.physical_center_wl)
        else:
            center_nm = float(spectrometer["target_center_wavelength_nm"])
        if display_mode == "Raman shift":
            ex_wl = self.spin_exc_wl.value()
            if ex_wl > 0 and center_nm > 0:
                center_for_spinbox = 1e7 / ex_wl - 1e7 / center_nm
            else:
                center_for_spinbox = 0.0
        else:
            center_for_spinbox = center_nm
        self.spin_centre_wl.setValue(center_for_spinbox)

        self._loading_config = True
        coefficients = calibration["coefficients"]
        self._pending_calib_coeffs = (
            coefficients["c0"], coefficients["c1"], coefficients["c2"]
        )
        self._pending_configuration_label = format_configuration_label(record)
        self._pending_calib_unit = calibration["unit"]
        self._pending_calib_laser_wl = calibration.get("excitation_wavelength_nm")
        self._pending_axis_source = "loaded_configuration"
        self._pending_configuration_id = record["configuration_id"]
        self._pending_configuration_slot_id = record["slot_id"]
        self._pending_configuration_axis_mode = axis_mode
        self._pending_configuration_future = completion_future

        if skip_move:
            self._finalize_pending_configuration()
        else:
            self.on_apply_spectrometer()

    def _finalize_pending_configuration(self):
        """Apply the staged axis state after a move, or immediately for a no-op move."""
        configuration_id = self._pending_configuration_id
        slot_id = self._pending_configuration_slot_id
        completion_future = self._pending_configuration_future
        try:
            if self._pending_configuration_axis_mode == "pixel":
                self._apply_pixel_configuration(
                    self._pending_configuration_label, configuration_id, slot_id
                )
            else:
                self.apply_calibration(
                    self._pending_calib_coeffs,
                    self._pending_configuration_label,
                    calib_unit=self._pending_calib_unit,
                    calib_laser_wl=self._pending_calib_laser_wl,
                    axis_source=self._pending_axis_source,
                    configuration_id=configuration_id,
                    slot_id=slot_id,
                )
            try:
                self.configuration_catalog.mark_used(configuration_id)
            except Exception as exc:
                print(f"Failed to update configuration usage metadata: {exc}")
        except Exception as exc:
            self._clear_pending_configuration()
            self._loading_config = False
            if completion_future is not None and not completion_future.done():
                completion_future.set_exception(exc)
                return
            raise

        self._clear_pending_configuration()
        self._loading_config = False
        if completion_future is not None and not completion_future.done():
            completion_future.set_result(True)

    def _fail_pending_configuration(self, message):
        completion_future = getattr(self, "_pending_configuration_future", None)
        self._clear_pending_configuration()
        self._loading_config = False
        if completion_future is not None and not completion_future.done():
            completion_future.set_exception(RuntimeError(message))
            return True
        return False

    def _clear_pending_configuration(self):
        self._pending_calib_coeffs = None
        self._pending_configuration_label = None
        self._pending_calib_unit = None
        self._pending_calib_laser_wl = None
        self._pending_axis_source = None
        self._pending_configuration_id = None
        self._pending_configuration_slot_id = None
        self._pending_configuration_axis_mode = "calibrated"
        self._pending_configuration_future = None

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
                self.label_current_temp.text(),
                hardware_metadata=build_hardware_metadata(
                    self,
                    self._hardware_capture_by_mode.get("1d", self._latest_hardware_capture),
                    include_background=False,
                ),
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
            capture_mode = "1d" if is_1d else "2d"
            hardware_capture = self._hardware_capture_by_mode.get(
                capture_mode, self._latest_hardware_capture
            )
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
                "hardware_metadata": build_hardware_metadata(
                    self, hardware_capture
                ),
            }

            if is_1d:
                x_data = self.get_x_axis(len(self.latest_1d_data))
                if self.chk_flip_x.isChecked() and public_axis_kind(self) != "pixel":
                    # Must match DisplayMixin.update_display()'s flip condition, or the
                    # saved x column would desync from native wavelength/calibrated y data.
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
