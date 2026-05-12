"""DataFileIO: Pure file I/O operations for FluoraPressée.

All methods operate on plain Python/NumPy data with no dependency on PyQt5 or UI state,
enabling reuse from external scripts and other applications.
"""

import csv
import json
import numpy as np
from datetime import datetime


class DataFileIO:

    def _build_header(self, metadata):
        grating  = metadata.get("grating", "")
        center   = metadata.get("center_wl", 0)
        acq_time = metadata.get("acq_time", 0)
        accum    = metadata.get("accum", 1)
        coeffs   = metadata.get("calib_coeffs", None)
        roi_s    = metadata.get("roi_start", 0)
        roi_e    = metadata.get("roi_end", 0)
        mode     = metadata.get("mode", "1D (ROI)")
        spec_mode = metadata.get("spec_mode", "Wavelength")
        exc_wl   = metadata.get("exc_wl", 532.0)

        h = f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        h += f"Grating: {grating} grooves/mm\n"
        if spec_mode == "Raman shift":
            h += f"Spectrometer Mode: Raman shift\n"
            h += f"Excitation Wavelength: {exc_wl} nm\n"
            h += f"Centre Raman shift: {center} cm-1\n"
        else:
            h += f"Spectrometer Mode: Wavelength\n"
            h += f"Centre Wavelength: {center} nm\n"
        h += f"Acquisition Time: {acq_time} s\n"
        h += f"Accumulations: {accum}\n"
        if coeffs is not None:
            c0, c1, c2 = coeffs
            h += f"Calibration Coefficients (c0, c1, c2: y = c0 + c1x + c2x^2): {c0}, {c1}, {c2}\n"
        else:
            h += "Calibration Coefficients: None\n"
        h += f"ROI Start (Vertical Pixel): {roi_s}\n"
        h += f"ROI End (Vertical Pixel): {roi_e}\n"
        h += f"Measurement Mode: {mode}\n"
        return h

    def save_spectrum_1d(self, file_path, x_data, display_data, metadata,
                         raw_data=None, bg_data=None):
        """Save 1D spectrum. If raw_data and bg_data are given, saves 4 columns."""
        header = self._build_header(metadata)
        x_label = "Raman_shift_cm-1" if metadata.get("spec_mode") == "Raman shift" else "Wavelength_or_Pixel"

        if raw_data is not None and bg_data is not None:
            header += f"{x_label},Intensity_Subtracted,Intensity_Raw,Background"
            cols = np.column_stack((x_data, display_data, raw_data, bg_data))
        else:
            header += f"{x_label},Intensity"
            cols = np.column_stack((x_data, display_data))

        np.savetxt(file_path, cols, delimiter=",", header=header, comments="# ", fmt="%g")

    def save_spectrum_2d(self, file_path, data_2d, metadata):
        """Save 2D image data."""
        header = self._build_header(metadata) + "2D Image Data"
        np.savetxt(file_path, data_2d, delimiter=",", header=header, comments="# ", fmt="%g")

    def save_fitting_results(self, fit_file_path, fit_res, func_name, pressure_info=None):
        """Save fitting result parameters to a text file.

        pressure_info (optional) dict keys:
            pressure, pressure_err  — float, GPa
            scale, sensor           — str
            lam0                    — float, zero-pressure peak position
            lam0_unit               — "nm" or "cm-1"
        """
        if fit_res.get("is_double"):
            fit_header = "Function,R2,Peak1_Pos,Peak1_Err,Peak1_Width,Peak1_WErr,Peak2_Pos,Peak2_Err,Peak2_Width,Peak2_WErr"
            vals = [
                func_name, f"{fit_res.get('R2', 0):.6f}",
                f"{fit_res.get('Peak1', 0):.6f}", f"{fit_res.get('Peak1_Err', 0):.6f}",
                f"{fit_res.get('Width1', 0):.6f}", f"{fit_res.get('Width1_Err', 0):.6f}",
                f"{fit_res.get('Peak2', 0):.6f}", f"{fit_res.get('Peak2_Err', 0):.6f}",
                f"{fit_res.get('Width2', 0):.6f}", f"{fit_res.get('Width2_Err', 0):.6f}",
            ]
        else:
            fit_header = "Function,R2,Peak_Pos,Peak_Err,Peak_Width,Peak_WErr"
            vals = [
                func_name, f"{fit_res.get('R2', 0):.6f}",
                f"{fit_res.get('Peak', 0):.6f}", f"{fit_res.get('Peak_Err', 0):.6f}",
                f"{fit_res.get('Width', 0):.6f}", f"{fit_res.get('Width_Err', 0):.6f}",
            ]

        if pressure_info is not None:
            lam0_col = "Lambda0_nm" if pressure_info.get("lam0_unit") == "nm" else "Nu0_cm-1"
            fit_header += f",Pressure_GPa,Pressure_Err_GPa,Scale,Sensor,{lam0_col}"
            vals += [
                f"{pressure_info['pressure']:.6f}",
                f"{pressure_info['pressure_err']:.6f}",
                pressure_info['scale'],
                pressure_info['sensor'],
                f"{pressure_info['lam0']:.6f}",
            ]

        with open(fit_file_path, "w", encoding="utf-8") as f:
            f.write(fit_header + "\n")
            f.write(",".join(vals) + "\n")

    def save_background(self, file_path, signal, acquisition_time, accumulations,
                        mode_str, roi_start, roi_end, detector_temperature):
        """
        Save background data as JSON.
        Returns (bg_array, metadata_dict) so the caller can immediately update its state.
        """
        payload = {
            "detector_settings": {"mode": mode_str, "roi_start": roi_start, "roi_end": roi_end},
            "acquisition_time": f"{acquisition_time:.3f}",
            "accumulations": accumulations,
            "detector_temperature": detector_temperature,
            "signal": signal.tolist(),
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)

        metadata = {
            "acquisition_time": float(acquisition_time),
            "accumulations": accumulations,
            "mode": mode_str,
            "roi_start": roi_start,
            "roi_end": roi_end,
        }
        return np.array(signal, dtype=np.float64), metadata

    def load_background(self, file_path):
        """
        Load background from a JSON file.
        Returns (bg_array, metadata_dict).
        Raises ValueError if the file format is invalid.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "signal" not in data:
            raise ValueError("Invalid background file: 'signal' key missing.")
        bg_array = np.array(data["signal"], dtype=np.float64)
        det = data.get("detector_settings", {})
        metadata = {
            "acquisition_time": float(data.get("acquisition_time", 0.0)),
            "accumulations": int(data.get("accumulations", 1)),
            "mode": det.get("mode", ""),
            "roi_start": det.get("roi_start", 0),
            "roi_end": det.get("roi_end", 0),
        }
        return bg_array, metadata

    def load_calibration_config(self, file_path):
        """
        Load calibration configuration from a JSON file.
        Returns a dict with keys: grating, unit, center, mode, roi_start, roi_end, c0, c1, c2.
        Raises Exception on parse failure.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spec  = data.get("spectrometer_settings", {})
        det   = data.get("detector_settings", {})
        calib = data["calibration_coefficients"]

        unit   = spec.get("unit", "Wavelength")
        center = spec.get("center_value", 694.0)
        if "center_wavelength_nm" in spec:
            center = spec["center_wavelength_nm"]
            unit   = "Wavelength"

        return {
            "grating":   str(spec.get("grating_grooves_per_mm", "600")),
            "unit":      unit,
            "center":    center,
            "mode":      det.get("mode", "1D Spectrum (Custom ROI)"),
            "roi_start": det.get("roi_start", 100),
            "roi_end":   det.get("roi_end", 140),
            "c0": calib["c0"],
            "c1": calib["c1"],
            "c2": calib["c2"],
        }

    def save_sequential_summary(self, summary_path, start_dt, end_dt,
                                acq_time, accum, skip_frames, log_data):
        """Write the sequential-measurement summary file."""
        with open(summary_path, "w", encoding="utf-8", newline="") as f:
            f.write("Sequential Measurement Summary\n")
            f.write(f"Start Time: {start_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"End Time: {end_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Exposure Time: {acq_time} s\n")
            f.write(f"Accumulations: {accum}\n")
            f.write(f"Skip Frames: {skip_frames}\n")
            f.write("-" * 30 + "\n")
            writer = csv.writer(f)
            writer.writerow(["Filename", "Saved Time"])
            writer.writerows(log_data)
