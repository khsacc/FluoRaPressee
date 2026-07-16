from PyQt5.QtWidgets import QVBoxLayout, QLabel, QDialog, QMessageBox
from PyQt5.QtCore import Qt

from src.spectrometer import SpectrometerMoveThread
from src.calibration_ui import CalibrationWindow


class SpectrometerControlMixin:
    def on_spec_mode_changed(self):
        # The centralWidget is fully disabled while the spectrometer moves
        # (_show_spectrometer_moving_dialog calls centralWidget().setEnabled(False)),
        # so this handler should not fire during movement. Return as a safety guard.
        if hasattr(self, 'spec_move_thread') and self.spec_move_thread.isRunning():
            return

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
                    # Check for invalid Raman shift value (when Raman shift >= excitation wavenumber)
                    denom = 1e7 / ex_wl - val
                    if denom <= 0:
                        # Invalid state: Raman shift is too large
                        self.btn_apply_spec.setEnabled(False)
                        return
                    target_wl = 1e7 / denom
                except (ZeroDivisionError, ValueError):
                    # If Raman shift calculation fails, disable apply button
                    self.btn_apply_spec.setEnabled(False)
                    return
            else:
                # Invalid state: ex_wl should never be <= 0 in Raman mode
                # Cannot calculate target wavelength from Raman shift
                self.btn_apply_spec.setEnabled(False)
                return
        else:
            target_wl = val

        if curr_g == self.physical_grating and abs(target_wl - self.physical_center_wl) < 1e-4:
            self.btn_apply_spec.setEnabled(False)
        else:
            self.btn_apply_spec.setEnabled(True)

    def on_flip_x_changed(self):
        self.config["flip_x"] = self.chk_flip_x.isChecked()
        self.save_config_to_file()
        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

    def on_calibrate_neon(self):
        was_measuring = self.thread.is_measuring
        if was_measuring:
            self.stop_measurement()  # also releases the acquisition gate

        if not self._try_acquire_gate():
            QMessageBox.warning(self, "Busy", "Another acquisition is already in progress.")
            return

        calib_win = CalibrationWindow(camera_thread=self.thread, parent=self)
        calib_win.exec()

        self._release_acquisition_gate()

        if was_measuring:
            # Re-acquire before resuming; if something else grabbed the gate in the brief
            # window since release (e.g. a concurrent API request), skip the resume rather
            # than starting an unprotected measurement.
            if self._try_acquire_gate():
                self.start_measurement()
            else:
                QMessageBox.warning(self, "Busy", "Could not resume measurement: acquisition is busy.")

    def _set_spectrometer_controls_enabled(self, enabled):
        self.combo_grating.setEnabled(enabled)
        self.radio_spec_mode_wl.setEnabled(enabled)
        self.radio_spec_mode_raman.setEnabled(enabled)
        self.spin_centre_wl.setEnabled(enabled)
        self.spin_exc_wl.setEnabled(enabled and self.radio_spec_mode_raman.isChecked())
        self.btn_calib_neon.setEnabled(enabled)
        self.btn_load_calib.setEnabled(enabled)
        if enabled:
            self.check_spectrometer_changes()
        else:
            self.btn_apply_spec.setEnabled(False)

    def _show_spectrometer_moving_dialog(self):
        if getattr(self, 'spec_move_dialog', None) is not None:
            return
        self.centralWidget().setEnabled(False)
        self.spec_move_dialog = QDialog(self)
        self.spec_move_dialog.setWindowTitle("Spectrometer is moving")
        self.spec_move_dialog.setModal(True)
        self.spec_move_dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        layout = QVBoxLayout(self.spec_move_dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(QLabel("Spectrometer is moving. Please wait..."))
        self.spec_move_dialog.setLayout(layout)
        self.spec_move_dialog.setFixedSize(320, 100)
        self.spec_move_dialog.show()
        self.spec_move_dialog.raise_()
        self.spec_move_dialog.activateWindow()

    def _close_spectrometer_moving_dialog(self):
        dialog = getattr(self, 'spec_move_dialog', None)
        if dialog is not None:
            dialog.accept()
            self.spec_move_dialog = None
        self.centralWidget().setEnabled(True)

    def on_apply_spectrometer(self):
        combo_index = self.combo_grating.currentIndex()
        gratings = self.config.get("grating", [])
        if 0 <= combo_index < len(gratings):
            grating_index = int(gratings[combo_index].get("index", combo_index + 1))
        else:
            grating_index = combo_index + 1
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

        self._set_spectrometer_controls_enabled(False)
        self._show_spectrometer_moving_dialog()

        self.spec_move_thread = SpectrometerMoveThread(self.spec_ctrl, grating_index, target_wl)
        self.spec_move_thread.finished_signal.connect(self.on_spectrometer_moved)
        self.spec_move_thread.start()

    def on_spectrometer_moved(self):
        if getattr(self.spec_move_thread, "success", True) is False:
            message = getattr(
                self.spec_move_thread,
                "error_message",
                "The spectrometer setting change failed."
            )
            self._loading_config = False
            self._close_spectrometer_moving_dialog()
            self._set_spectrometer_controls_enabled(True)
            QMessageBox.warning(self, "Spectrometer error", message)
            return

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
                self.apply_calibration(
                    self._pending_calib_coeffs,
                    self._pending_calib_filename,
                    calib_unit=getattr(self, '_pending_calib_unit', 'Wavelength'),
                    calib_laser_wl=getattr(self, '_pending_calib_laser_wl', None)
                )
                self._pending_calib_coeffs = None
                self._pending_calib_filename = None
                self._pending_calib_unit = None
                self._pending_calib_laser_wl = None
            self._loading_config = False
        else:
            # Grating/centre-wavelength changes invalidate the pixel calibration (it was only
            # valid at the previous physical position), but must NOT touch the ROI: ROI is set
            # independently via config load, calibration-file load, or direct user edits only.
            self.calib_coeffs = None
            self.calib_unit = 'Wavelength'
            self.calib_laser_wl = None
            self.calib_file_name = "None"
            self.lbl_loaded_calib.setText("Loaded: None")
            self.update_plot_labels()

        if getattr(self, 'raw_1d_data', None) is not None and hasattr(self.thread, 'is_measuring') and not self.thread.is_measuring:
            self.update_display(is_new_data=False)

        self._close_spectrometer_moving_dialog()
        self._set_spectrometer_controls_enabled(True)
