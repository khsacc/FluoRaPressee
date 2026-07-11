import secrets
import socket
import threading
import time
from concurrent.futures import Future
from datetime import datetime

import numpy as np
import uvicorn
from PyQt5.QtWidgets import QMessageBox

from src.pressureCalc import PressureCalculator


class BackgroundMismatchError(Exception):
    """Raised by api_acquire() when dark_mode="reuse_loaded" doesn't match the
    loaded background's acquisition settings and the caller didn't opt in via
    ignore_mismatch=True.
    """
    pass


def _parse_temp_c(text):
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


class ApiMixin:
    # ------------------------------------------------------------------
    # GUI-thread helpers. Must be invoked via self.gui_bridge.call(...) from
    # a non-GUI thread (GuiBridge itself refuses to be called from the GUI
    # thread, see src/api/gui_bridge.py).
    # ------------------------------------------------------------------

    def _api_start_acquire(self, exposure_s=None, accumulations=None):
        """Kick off a single-shot acquisition and return immediately.

        Does not wait for the frame to arrive - that happens asynchronously via
        the existing data_ready signal path; the returned Future is resolved
        later by _process_completed_data().
        """
        if not self._try_acquire_gate():
            raise RuntimeError("acquisition busy")

        actual_exposure = exposure_s if exposure_s is not None else self.spin_acq_time.value()
        actual_accum = accumulations if accumulations is not None else self.spin_accumulate.value()

        if exposure_s is not None:
            self.thread.update_exposure(exposure_s)
            time.sleep(0.1)  # let the camera thread pick up the new exposure, as acquire_single_image() does

        if accumulations is not None:
            self._active_target_accum = accumulations

        future = Future()
        self._api_pending_future = future
        self.take_single_spectrum()

        return future, actual_exposure, actual_accum

    def _api_check_bg_mismatch(self, actual_exposure, actual_accum):
        """Like FileIOMixin.check_bg_mismatch(), but independent of the
        radio_bg_on toggle - the API's dark handling must not depend on that
        GUI setting (see work/work_API.md, "Darkデータの扱い"). Compares
        against the *actual* exposure/accumulations used for this request
        rather than the current widget values, since an API caller may have
        overridden either without touching the widgets.
        """
        bg_meta = self.loaded_bg_metadata
        if bg_meta is None:
            return False

        curr_mode = "1D Spectrum (Custom ROI)" if self.radio_1d_roi.isChecked() else "1D Spectrum (Full Range Binning)"

        mismatch = False
        if abs(actual_exposure - bg_meta.get("acquisition_time", 0)) > 1e-4:
            mismatch = True
        if actual_accum != bg_meta.get("accumulations", 1):
            mismatch = True
        if curr_mode != bg_meta.get("mode"):
            mismatch = True
        if curr_mode == "1D Spectrum (Custom ROI)":
            if self.spin_vstart.value() != bg_meta.get("roi_start") or self.spin_vend.value() != bg_meta.get("roi_end"):
                mismatch = True
        return mismatch

    def _api_finalize_acquire(self, raw_len, mode, dark_mode, actual_exposure, actual_accum):
        """Gather everything the response needs that requires reading GUI state:
        the calibrated x-axis (1D only - a 2D image has no single x-axis), the
        detector temperature label, and - for dark_mode="reuse_loaded" - the
        loaded background array and whether it mismatches this request.
        """
        x = self.get_x_axis(raw_len) if mode == "1d" else None
        temp_text = self.label_current_temp.text()

        bg_data = None
        bg_mismatch = False
        if mode == "1d" and dark_mode == "reuse_loaded":
            bg_data = self.loaded_bg_data
            if bg_data is not None:
                bg_mismatch = self._api_check_bg_mismatch(actual_exposure, actual_accum)

        return x, temp_text, bg_data, bg_mismatch

    # ------------------------------------------------------------------
    # API worker-thread entry point.
    # ------------------------------------------------------------------

    def api_acquire(self, exposure_s=None, accumulations=None, dark_mode="none",
                     dark_data=None, ignore_mismatch=False, timeout=30.0):
        """Synchronous single-shot acquisition for API callers.

        Must be called from a non-GUI thread. Background subtraction is
        computed here from the raw acquired data and this call's own
        parameters only - it never depends on the GUI's "Subtract background"
        toggle or "Flip X-axis" checkbox (see work/work_API.md).
        """
        if dark_mode == "provided" and dark_data is None:
            raise ValueError('dark_mode="provided" requires dark_data')

        future, actual_exposure, actual_accum = self.gui_bridge.call(
            lambda: self._api_start_acquire(exposure_s, accumulations)
        )
        result = future.result(timeout=timeout)
        raw = result["raw"]
        mode = result["mode"]

        x, temp_text, bg_data, bg_mismatch = self.gui_bridge.call(
            lambda: self._api_finalize_acquire(
                len(raw) if mode == "1d" else None, mode, dark_mode, actual_exposure, actual_accum
            )
        )

        background_mismatch_warning = False

        if mode == "1d":
            if dark_mode == "none":
                y = raw.copy()
            elif dark_mode == "provided":
                dark_arr = np.asarray(dark_data)
                if len(dark_arr) != len(raw):
                    raise ValueError(
                        f"dark_data length ({len(dark_arr)}) does not match acquired data length ({len(raw)})"
                    )
                y = raw - dark_arr
            elif dark_mode == "reuse_loaded":
                if bg_data is None:
                    raise ValueError('dark_mode="reuse_loaded" but no background is currently loaded')
                if bg_mismatch and not ignore_mismatch:
                    raise BackgroundMismatchError(
                        "Loaded background does not match this request's exposure/accumulations/ROI settings. "
                        "Pass ignore_mismatch=True to subtract anyway, or use dark_mode='provided'/'none'."
                    )
                y = raw - bg_data
                if bg_mismatch:
                    background_mismatch_warning = True
            else:
                raise ValueError(f"Unknown dark_mode: {dark_mode!r}")
        else:
            y = raw

        response = {
            "x": x,
            "y_raw": raw,
            "y": y,
            "mode": mode,
            "exposure_time_s": actual_exposure,
            "accumulations": actual_accum,
            "detector_temperature_c": _parse_temp_c(temp_text),
            "timestamp": datetime.now().isoformat(),
        }
        if background_mismatch_warning:
            response["background_mismatch_warning"] = True
        return response

    # ------------------------------------------------------------------
    # Stateless computation (no GUI thread / widget dependency at all).
    # ------------------------------------------------------------------

    def api_fit(self, x, y, fit_function, fit_start=None, fit_end=None,
                fit_peak_count=2, peak_sort_order="x_desc"):
        """Fit a spectrum using DataAnalyzer directly - no GuiBridge needed,
        since DataAnalyzer.fit_spectrum() is Qt-independent. Deliberately does
        not touch combo_fit_func/spin_fit_start/spin_fit_end so a concurrent
        API request never disturbs the operator's own fit display settings.
        """
        x_fit, y_fit_curve, res = self.analyzer.fit_spectrum(
            np.asarray(x), np.asarray(y), fit_function, fit_start, fit_end,
            peak_count=fit_peak_count, peak_sort_order=peak_sort_order
        )
        if res is None:
            return {"success": False, "x_fit": None, "y_fit": None, "fit": None}
        return {"success": True, "x_fit": x_fit, "y_fit": y_fit_curve, "fit": res}

    def api_pressure(self, peak, peak_err, sensor, pressure_scale, zero_pressure_peak,
                      temperature_correction=None):
        """Calculate pressure using PressureCalculator's internal keys.

        `sensor`, `pressure_scale`, and `temperature_correction["scale"]` are
        backend keys such as "ruby", "ruby_shen_2020", and
        "ruby_kobayashi_unpublished", not GUI labels.

        This mirrors PressureCalculatorWindow.calculate() without any widget
        dependency. Temperature correction is performed inside
        PressureCalculator.calculate(); this method only gathers request values
        and formats the API response.
        """
        zero_peak_at_t0 = None
        current_t = 298.15
        t0 = 298.15
        t_scale = None
        temperature_enabled = False
        temperature_warning = None

        if temperature_correction is not None:
            current_t = temperature_correction.get("current_t", current_t)
            t0 = temperature_correction.get("t0", t0)
            zero_peak_at_t0 = temperature_correction.get("zero_pressure_peak_at_t0", zero_pressure_peak)
            temperature_enabled = temperature_correction.get("enabled", False)

            if temperature_enabled:
                t_scale = temperature_correction.get("scale")
                is_valid, rng = PressureCalculator.is_temp_in_range(
                    sensor=sensor, p_scale=pressure_scale, t_scale=t_scale, temp=current_t
                )
                if not is_valid and rng[0] is not None:
                    warning_scale = (
                        pressure_scale
                        if PressureCalculator.pressure_scale_requires_temperature(
                            sensor=sensor, p_scale=pressure_scale
                        )
                        else t_scale
                    )
                    temperature_warning = (
                        f"Temperature {current_t} K is outside the valid range "
                        f"({rng[0]}-{rng[1]} K) for {sensor} / {warning_scale}."
                    )

        t0 = PressureCalculator.resolve_t0(sensor=sensor, p_scale=pressure_scale, t0=t0)
        result = PressureCalculator.calculate(
            sensor=sensor, p_scale=pressure_scale,
            peak=peak, zero_peak=zero_pressure_peak,
            zero_peak_at_t0=zero_peak_at_t0,
            peak_err=peak_err,
            temperature_correction_enabled=temperature_enabled,
            t_scale=t_scale,
            current_t=current_t, t0=t0,
        )

        return {
            "pressure": result.pressure,
            "pressure_err": result.pressure_err,
            "zero_pressure_peak_at_current_t": result.zero_peak_at_current_t,
            "temperature_warning": temperature_warning,
        }

    # ------------------------------------------------------------------
    # More GUI-thread helpers (state mutation / widget reads).
    # ------------------------------------------------------------------

    def api_apply_calibration(self, c0, c1, c2, unit, laser_wavelength_nm=None, label="api"):
        """Must run on the GUI thread (updates self.lbl_loaded_calib etc. via
        FileIOMixin.apply_calibration()).
        """
        self.apply_calibration((c0, c1, c2), label, calib_unit=unit, calib_laser_wl=laser_wavelength_nm)
        return {
            "applied": True,
            "unit": self.calib_unit,
            "c0": c0, "c1": c1, "c2": c2,
            "label": self.calib_file_name,
        }

    def api_get_status(self):
        """Must run on the GUI thread (reads several widgets)."""
        if self.radio_2d.isChecked():
            roi_mode = "2d"
        elif self.radio_1d_full.isChecked():
            roi_mode = "1d_full"
        else:
            roi_mode = "1d_roi"

        return {
            "busy": self._acquisition_gate.locked(),
            "camera_connected": hasattr(self, 'thread') and self.thread.isRunning(),
            "exposure_time_s": self.spin_acq_time.value(),
            "calibration": {
                "applied": self.calib_coeffs is not None,
                "unit": self.calib_unit,
                "label": self.calib_file_name,
            },
            "roi": {
                "mode": roi_mode,
                "start": self.spin_vstart.value(),
                "end": self.spin_vend.value(),
            },
            "background": {
                "loaded": self.loaded_bg_data is not None,
                "metadata": self.loaded_bg_metadata,
            },
        }

    # ------------------------------------------------------------------
    # API server lifecycle (GUI thread only - touches widgets/threads).
    # ------------------------------------------------------------------

    def start_api_server(self, host, port):
        """Start the FastAPI server in a background thread and lock the
        measurement/config UI for as long as it runs (see work/work_API.md,
        "API稼働中のGUI操作ロック").
        """
        # Deferred import: src.api.server imports BackgroundMismatchError from
        # this module, so importing it at module load time here would be a
        # circular import. Importing lazily, inside the method, avoids it.
        from src.api.server import create_app

        self._api_key = self.get_or_create_api_key()
        self._api_last_port = port
        api_app = create_app(self, self.gui_bridge)
        config = uvicorn.Config(api_app, host=host, port=port, log_level="info")
        self._api_server = uvicorn.Server(config)
        self._api_server_thread = threading.Thread(target=self._api_server.run, daemon=True)
        self._api_server_thread.start()
        self._lock_ui("api_server")

    def stop_api_server(self):
        if getattr(self, '_api_server', None) is not None:
            self._api_server.should_exit = True
            self._api_server_thread.join(timeout=5)
            self._api_server = None
            self._api_server_thread = None
        self._unlock_ui("api_server")

    def get_or_create_api_key(self):
        """Load the persisted API key, generating and persisting one on first
        use so it stays stable across app restarts and server start/stop
        cycles - the paired client application only needs to be configured
        with it once (see work/work_API.md for the pre-shared-key rationale).
        """
        key = self.load_api_key_file()
        if not key:
            key = secrets.token_urlsafe(24)
            self.save_api_key_file(key)
        return key

    def regenerate_api_key(self):
        """Immediately invalidates the current key and persists a new one.
        src/api/server.py's verify_api_key reads self._api_key live on every
        request rather than closing over a value captured at server-start
        time, so this takes effect on the very next request without needing
        to restart the running server.
        """
        self._api_key = secrets.token_urlsafe(24)
        self.save_api_key_file(self._api_key)
        return self._api_key

    def _build_api_status_text(self, port):
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"
        return f"Running at http://{local_ip}:{port}/docs\nX-API-Key: {self._api_key}"

    def on_regenerate_api_key_clicked(self):
        reply = QMessageBox.question(
            self, "Regenerate API Key",
            "This immediately invalidates the current API key. Any paired client still using the "
            "old key will get 401 Unauthorized until it's updated with the new one shown next.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        new_key = self.regenerate_api_key()
        QMessageBox.information(self, "API Key Regenerated", f"New API key:\n\n{new_key}")

        if getattr(self, '_api_server', None) is not None:
            self.lbl_api_status.setText(self._build_api_status_text(self._api_last_port))

    def on_start_api_server_clicked(self):
        port = self.spin_api_port.value()
        self.start_api_server(host="0.0.0.0", port=port)

        self.lbl_api_status.setText(self._build_api_status_text(port))
        self.btn_start_api.setEnabled(False)
        self._set_button_style(self.btn_start_api, self.BUTTON_STYLE_GREEN)
        self.spin_api_port.setEnabled(False)
        self.btn_stop_api.setEnabled(True)
        self._set_button_style(self.btn_stop_api, self.BUTTON_STYLE_RED)

    def on_stop_api_server_clicked(self):
        self.stop_api_server()
        self.lbl_api_status.setText("Not running")
        self.btn_start_api.setEnabled(True)
        self._set_button_style(self.btn_start_api, self.BUTTON_STYLE_GREEN)
        self.spin_api_port.setEnabled(True)
        self.btn_stop_api.setEnabled(False)
        self._set_button_style(self.btn_stop_api, self.BUTTON_STYLE_RED)
