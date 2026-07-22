"""DataFileIO: Pure file I/O operations for FluoraPressée.

All methods operate on plain Python/NumPy data with no dependency on Qt or UI state,
enabling reuse from external scripts and other applications.
"""

import csv
import json
import os
import re
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
        hardware_metadata = metadata.get("hardware_metadata")
        if hardware_metadata is not None:
            encoded = json.dumps(hardware_metadata, ensure_ascii=True, separators=(",", ":"))
            h += f"hardware_metadata: {encoded}\n"
        return h

    def save_spectrum_1d(self, file_path, x_data, display_data, metadata,
                         raw_data=None, bg_data=None):
        """Save 1D spectrum. If raw_data and bg_data are given, saves 4 columns."""
        header = self._build_header(metadata)
        calib_present = metadata.get("calib_coeffs") is not None
        if metadata.get("spec_mode") == "Raman shift" and calib_present:
            x_label = "Raman_shift_cm-1"
        else:
            x_label = "Wavelength_or_Pixel"

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

    def looks_like_spectrum_file(self, file_path):
        """Cheap header sniff (no full parse) for whether a file is a 1D spectrum saved
        by save_spectrum_1d. Used to filter directory listings in Analysis Mode -- it
        naturally rejects background/calibration files (JSON, no '#' lines) and
        *_fitting_results.txt files (plain CSV, no '#' lines either).

        Requires the trailing '#' line to be the actual 1D column header (not just any
        line containing 'Grating:', which save_spectrum_2d's header also has) so 2D
        image files -- saved with the same header block plus a final '2D Image Data'
        marker instead of a CSV column header -- are correctly rejected too.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                header_lines = []
                for _ in range(40):
                    line = f.readline()
                    if not line or not line.startswith("#"):
                        break
                    header_lines.append(line[1:].strip())
        except (OSError, UnicodeDecodeError):
            return False

        if not any(l.startswith("Grating:") for l in header_lines):
            return False
        if not header_lines:
            return False
        last_line = header_lines[-1]
        return last_line.startswith("Wavelength_or_Pixel,Intensity") or \
            last_line.startswith("Raman_shift_cm-1,Intensity")

    def load_spectrum_1d(self, file_path):
        """Load a 1D spectrum previously written by save_spectrum_1d.

        Returns (x, y, y_raw, y_bg, metadata). y_raw/y_bg are None unless the file
        was saved with the raw+background 4-column format. metadata has the same
        keys as the dict save_spectrum_1d's caller builds: grating, center_wl,
        acq_time, accum, calib_coeffs, roi_start, roi_end, mode, spec_mode, exc_wl,
        hardware_metadata, source_file.

        The x column is already fully resolved (nm / cm-1 / pixel) at save time, so
        no calibration/grating/ROI state is needed to use the returned data.

        Raises ValueError if the file doesn't look like a spectrum saved by this app.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"Could not read file: {e}")

        header_lines = [l[1:].strip() for l in raw_lines if l.startswith("#")]
        if any(l == "2D Image Data" for l in header_lines):
            raise ValueError("This file contains 2D image data, not a 1D spectrum.")

        def find(pattern, default=None, cast=str):
            for line in header_lines:
                m = re.match(pattern, line)
                if m:
                    return cast(m.group(1))
            return default

        grating = find(r"Grating:\s*(\S+)")
        if grating is None:
            raise ValueError(
                "Not a FluoraPressée spectrum file: missing 'Grating' header field."
            )

        spec_mode = find(r"Spectrometer Mode:\s*(.+)$", default="Wavelength")
        exc_wl = find(r"Excitation Wavelength:\s*([-\d.eE+]+)", cast=float)
        center = find(r"Centre (?:Wavelength|Raman shift):\s*([-\d.eE+]+)", cast=float)
        acq_time = find(r"Acquisition Time:\s*([-\d.eE+]+)", default=0.0, cast=float)
        accum = find(r"Accumulations:\s*(\d+)", default=1, cast=int)
        roi_start = find(r"ROI Start.*?:\s*(-?\d+)", default=0, cast=int)
        roi_end = find(r"ROI End.*?:\s*(-?\d+)", default=0, cast=int)
        mode = find(r"Measurement Mode:\s*(.+)$", default="1D (ROI)")

        calib_coeffs = None
        # Greedy ".*:" so it matches the LAST colon on the line -- the label itself
        # contains a colon (e.g. "...c2: y = c0 + c1x + c2x^2): 690.0, 0.05, -1e-06").
        calib_line = find(r"Calibration Coefficients.*:\s*(.+)$")
        if calib_line and calib_line.strip() != "None":
            try:
                calib_coeffs = tuple(float(v) for v in calib_line.split(","))
            except ValueError:
                calib_coeffs = None

        hardware_metadata = None
        hw_line = find(r"hardware_metadata:\s*(.+)$")
        if hw_line:
            try:
                hardware_metadata = json.loads(hw_line)
            except (json.JSONDecodeError, TypeError):
                hardware_metadata = None

        try:
            data = np.loadtxt(file_path, delimiter=",", comments="#")
        except Exception as e:
            raise ValueError(f"Failed to parse spectrum data columns: {e}")

        data = np.atleast_2d(data)
        if data.shape[1] not in (2, 4):
            raise ValueError(f"Unexpected number of data columns: {data.shape[1]}")

        x = data[:, 0]
        y = data[:, 1]
        y_raw = data[:, 2] if data.shape[1] == 4 else None
        y_bg = data[:, 3] if data.shape[1] == 4 else None

        metadata = {
            "grating": grating,
            "center_wl": center,
            "acq_time": acq_time,
            "accum": accum,
            "calib_coeffs": calib_coeffs,
            "roi_start": roi_start,
            "roi_end": roi_end,
            "mode": mode,
            "spec_mode": spec_mode,
            "exc_wl": exc_wl,
            "hardware_metadata": hardware_metadata,
            "source_file": os.path.basename(file_path),
        }
        return x, y, y_raw, y_bg, metadata

    def save_fitting_results(self, fit_file_path, fit_res, func_name, pressure_info=None):
        """Save fitting result parameters to a text file.

        pressure_info (optional) dict keys:
            pressure, pressure_err  — float, GPa
            scale, sensor           — str
            lam0                    — float, zero-pressure peak position
            lam0_unit               — "nm" or "cm-1"
        """
        peaks = fit_res.get("peaks") or []
        if not peaks:
            peaks = [{
                "position": fit_res.get("Peak", np.nan),
                "position_err": fit_res.get("Peak_Err", np.nan),
                "width": fit_res.get("Width", np.nan),
                "width_err": fit_res.get("Width_Err", np.nan),
            }]

        header_cols = ["Function", "R2"]
        vals = [func_name, f"{fit_res.get('R2', 0):.6f}"]
        for i, peak in enumerate(peaks, start=1):
            header_cols.extend([
                f"Peak{i}_Pos", f"Peak{i}_Err",
                f"Peak{i}_Width", f"Peak{i}_WErr",
            ])
            vals.extend([
                f"{peak.get('position', np.nan):.6f}",
                f"{peak.get('position_err', np.nan):.6f}",
                f"{peak.get('width', np.nan):.6f}",
                f"{peak.get('width_err', np.nan):.6f}",
            ])

        baseline = fit_res.get("baseline") or {}
        coefficients = list(baseline.get("coefficients") or [])
        coefficient_errors = list(baseline.get("coefficient_errors") or [])
        header_cols.extend([
            "Baseline_Requested", "Baseline_Selected",
            "Baseline_b0", "Baseline_b0_Err",
            "Baseline_b1", "Baseline_b1_Err",
            "Baseline_b2", "Baseline_b2_Err",
        ])
        vals.extend([
            str(baseline.get("requested", "Constant")),
            str(baseline.get("selected", "Constant")),
        ])
        for index in range(3):
            coefficient = coefficients[index] if index < len(coefficients) else np.nan
            coefficient_error = coefficient_errors[index] if index < len(coefficient_errors) else np.nan
            vals.extend([f"{coefficient:.6f}", f"{coefficient_error:.6f}"])
        fit_header = ",".join(header_cols)

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
                        mode_str, roi_start, roi_end, detector_temperature,
                        hardware_metadata=None):
        """
        Save background data as JSON.
        Returns (bg_array, metadata_dict) so the caller can immediately update its state.
        """
        payload = {
            "detector_settings": {"mode": mode_str, "roi_start": roi_start, "roi_end": roi_end},
            "acquisition_time": f"{acquisition_time:.3f}",
            "accumulations": accumulations,
            "detector_temperature": detector_temperature,
            "hardware_metadata": hardware_metadata,
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
            "hardware_metadata": hardware_metadata,
            "source_file": os.path.basename(file_path),
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
            "hardware_metadata": data.get("hardware_metadata"),
            "source_file": os.path.basename(file_path),
        }
        return bg_array, metadata

    def load_calibration_config(self, file_path):
        """
        Load calibration configuration from a JSON file.
        Returns a dict with keys:
          grating, calibration_unit, display_mode, center, exc_wl,
          mode, roi_start, roi_end, c0, c1, c2.
        Raises Exception on parse failure.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        spec  = data.get("spectrometer_settings", {})
        det   = data.get("detector_settings", {})
        calib = data["calibration_coefficients"]

        center = spec.get("center_wavelength_nm", spec.get("center_value", 694.0))

        # calibration_unit: unit used for the reference values during calibration.
        # Falls back through the old "display_unit" key, then the even older "unit" key.
        calibration_unit = spec.get(
            "calibration_unit", spec.get("display_unit", spec.get("unit", "Wavelength"))
        )

        # display_mode: what the main-window mode was when the file was saved.
        # Older files don't have this key; fall back to calibration_unit so behaviour
        # is unchanged for files created before this field was introduced.
        display_mode = spec.get("display_mode", calibration_unit)

        exc_wl = spec.get("excitation_wavelength_nm", None)

        return {
            "grating":          str(spec.get("grating_grooves_per_mm", "600")),
            "calibration_unit": calibration_unit,
            "display_mode":     display_mode,
            "center":           center,
            "exc_wl":           exc_wl,
            "mode":             det.get("mode", "1D Spectrum (Custom ROI)"),
            "roi_start":        det.get("roi_start", 100),
            "roi_end":          det.get("roi_end", 140),
            "c0": calib["c0"],
            "c1": calib["c1"],
            "c2": calib["c2"],
        }

    def create_fitting_seq_summary(self, file_path, func, fit_start, fit_end,
                                   peak_count, unit, has_pressure, peak_sort="x descending",
                                   baseline_model="Constant"):
        """Create the fitting sequential summary CSV with comment lines and a header row."""
        header_cols = ["Filename", "Timestamp"]
        for i in range(1, peak_count + 1):
            header_cols.extend([
                f"Peak{i} ({unit})", f"Peak{i}_Err ({unit})",
                f"Width{i} ({unit})", f"Width{i}_Err ({unit})",
            ])
        header_cols.append("R2")
        if has_pressure:
            header_cols.extend(["Pressure (GPa)", "Pressure_Err (GPa)"])
        header_cols.extend(["Baseline Selected", "Baseline b0", "Baseline b1", "Baseline b2"])

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# Fitting Function: {func}\n")
            f.write(f"# Peak Count: {peak_count}\n")
            f.write(f"# Peak Sort: {peak_sort}\n")
            f.write(f"# Baseline Model: {baseline_model}\n")
            f.write(f"# Fitting Range: {fit_start} to {fit_end}\n")
            f.write(",".join(header_cols) + "\n")

    def append_fitting_seq_row(self, file_path, filename, timestamp_str,
                               res, peak_count, pressure_info=None):
        """Append one data row to the fitting sequential summary CSV.

        pressure_info (optional) dict keys: pressure, pressure_err (float, GPa).
        Pass None when the pressure calculator is not active.
        """
        cols = [filename, timestamp_str]

        if res is None:
            cols.extend(["NaN"] * (peak_count * 4 + 1))
        else:
            peaks = res.get("peaks") or []
            if peaks:
                for i in range(peak_count):
                    if i < len(peaks):
                        peak = peaks[i]
                        cols.extend([
                            f"{peak.get('position', np.nan):.6f}",
                            f"{peak.get('position_err', np.nan):.6f}",
                            f"{peak.get('width', np.nan):.6f}",
                            f"{peak.get('width_err', np.nan):.6f}",
                        ])
                    else:
                        cols.extend(["NaN"] * 4)
                cols.append(f"{res.get('R2', np.nan):.6f}")
            else:
                cols.extend([
                    f"{res.get('Peak', np.nan):.6f}", f"{res.get('Peak_Err', np.nan):.6f}",
                    f"{res.get('Width', np.nan):.6f}", f"{res.get('Width_Err', np.nan):.6f}",
                    f"{res.get('R2', np.nan):.6f}",
                ])

        if pressure_info is not None:
            p  = pressure_info.get("pressure")
            pe = pressure_info.get("pressure_err")
            if p is not None:
                cols.extend([f"{p:.6f}", f"{pe:.6f}"])
            else:
                cols.extend(["NaN", "NaN"])

        baseline = (res or {}).get("baseline") or {}
        coefficients = list(baseline.get("coefficients") or [])
        cols.append(str(baseline.get("selected", "")))
        for index in range(3):
            value = coefficients[index] if index < len(coefficients) else np.nan
            cols.append(f"{value:.6f}")

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(",".join(cols) + "\n")

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
