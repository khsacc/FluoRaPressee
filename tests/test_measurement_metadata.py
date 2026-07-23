import json
import os
import tempfile
import unittest

import numpy as np

from src.file_io import DataFileIO
from src.measurement_metadata import (
    build_hardware_metadata,
    capture_hardware_state,
    public_axis_kind,
    public_axis_unit,
)


class Value:
    def __init__(self, value): self._value = value
    def value(self): return self._value


class Checked:
    def __init__(self, checked): self._checked = checked
    def isChecked(self): return self._checked


class Combo:
    def __init__(self, index): self._index = index
    def currentIndex(self): return self._index


class Camera:
    det_width = 1024
    det_height = 127
    current_exposure = 0.1

    def get_cached_hardware_metadata(self):
        return {
            "identity": {"model": "DU-401", "serial_number": "CAM-1"},
            "detector_size_px": {"width": 1024, "height": 127},
            "pixel_pitch_um": {"width": 26.0, "height": 26.0},
            "exposure_s": 0.1,
            "temperature": {"current_c": -64.9, "setpoint_c": -65.0, "status": "locked"},
        }


class Spectrometer:
    def get_cached_hardware_metadata(self):
        return {
            "serial_number": "SPEC-1",
            "grating": {"index": 1, "grooves_per_mm": 600, "blaze": "500 nm"},
            "center_wavelength_nm": 694.0,
            "wavelength_limits_nm": {"min": 0.0, "max": 1200.0},
        }


class Window:
    def __init__(self):
        self.thread = Camera()
        self.spec_ctrl = Spectrometer()
        self.config = {
            "grating": [{"index": 1, "grooves": 600}],
            "hardware_identity": {"spectrometer": {"serial_number": "SPEC-1"}},
        }
        self.combo_grating = Combo(0)
        self.spin_accumulate = Value(3)
        self.spin_acq_time = Value(0.1)
        self.spin_vstart = Value(45)
        self.spin_vend = Value(65)
        self.radio_2d = Checked(False)
        self.radio_1d_full = Checked(False)
        self.radio_bg_on = Checked(False)
        self.radio_spec_mode_raman = Checked(False)
        self.physical_center_wl = 694.0
        self.calib_coeffs = (690.0, 0.1, 1e-6)
        self.calib_unit = "Wavelength"
        self.configuration_label = "600 g/mm | 694.000 nm | ROI 45–65"
        self.active_configuration_id = "cfg-test"
        self.active_configuration_slot_id = "slot-test"
        self.axis_source = "neon_polynomial"
        self._camera_identity = {"model": "DU-401", "serial_number": "CAM-1"}
        self._last_temperature_c = -64.9
        self._last_temperature_status = "locked"
        self._temp_accepted_setpoint = -65.0
        self.loaded_bg_data = None
        self.loaded_bg_metadata = None


class MeasurementMetadataTests(unittest.TestCase):
    def test_required_hardware_and_axis_fields(self):
        window = Window()
        metadata = build_hardware_metadata(window, capture_hardware_state(window, 3))
        self.assertEqual(metadata["camera"]["identity"]["serial_number"], "CAM-1")
        self.assertEqual(metadata["camera"]["pixel_pitch_um"]["width"], 26.0)
        self.assertEqual(metadata["camera"]["binning"]["vertical"], 20)
        self.assertEqual(metadata["camera"]["accumulations"], 3)
        self.assertEqual(metadata["camera"]["accumulation_mode"], "software_sum")
        self.assertEqual(metadata["spectrometer"]["grating"]["blaze"], "500 nm")
        self.assertEqual(metadata["spectrometer"]["wavelength_limits_nm"]["max"], 1200.0)
        self.assertEqual(metadata["axis"]["source"], "neon_polynomial")
        self.assertEqual(metadata["axis"]["configuration_id"], "cfg-test")
        self.assertEqual(metadata["axis"]["configuration_slot_id"], "slot-test")

    def test_background_match_and_mismatch_are_recorded(self):
        window = Window()
        capture = capture_hardware_state(window, 3)
        background_hardware = build_hardware_metadata(window, capture, include_background=False)
        window.loaded_bg_data = np.zeros(1024)
        window.radio_bg_on = Checked(True)
        window.loaded_bg_metadata = {
            "acquisition_time": 0.1,
            "accumulations": 3,
            "mode": "1D Spectrum (Custom ROI)",
            "roi_start": 45,
            "roi_end": 65,
            "source_file": "background.json",
            "hardware_metadata": background_hardware,
        }
        metadata = build_hardware_metadata(window, capture)
        self.assertTrue(metadata["background"]["match"])
        window.loaded_bg_metadata["hardware_metadata"]["spectrometer"]["center_wavelength_nm"] = 700.0
        metadata = build_hardware_metadata(window, capture)
        self.assertFalse(metadata["background"]["match"])
        self.assertIn("spectrometer.center_wavelength_nm", metadata["background"]["mismatched_fields"])

    def test_background_accumulation_mode_mismatch_is_recorded(self):
        window = Window()
        capture = capture_hardware_state(window, 3)
        background_hardware = build_hardware_metadata(window, capture, include_background=False)
        background_hardware["camera"]["accumulation_mode"] = "hardware_accumulate"
        window.loaded_bg_data = np.zeros(1024)
        window.loaded_bg_metadata = {
            "acquisition_time": 0.1,
            "accumulations": 3,
            "mode": "1D Spectrum (Custom ROI)",
            "roi_start": 45,
            "roi_end": 65,
            "source_file": "background.json",
            "hardware_metadata": background_hardware,
        }

        metadata = build_hardware_metadata(window, capture)

        self.assertFalse(metadata["background"]["match"])
        self.assertIn(
            "camera.accumulation_mode",
            metadata["background"]["mismatched_fields"],
        )

    def test_spectrum_header_contains_parseable_hardware_metadata(self):
        hardware = build_hardware_metadata(Window())
        metadata = {"hardware_metadata": hardware}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "spectrum.txt")
            DataFileIO().save_spectrum_1d(path, np.arange(3), np.arange(3), metadata)
            with open(path, encoding="utf-8") as handle:
                line = next(line for line in handle if line.startswith("# hardware_metadata: "))
        decoded = json.loads(line.split(": ", 1)[1])
        self.assertEqual(decoded["camera"]["identity"]["serial_number"], "CAM-1")

    def test_background_round_trip_preserves_hardware_metadata(self):
        hardware = build_hardware_metadata(Window(), include_background=False)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "background.json")
            io = DataFileIO()
            io.save_background(path, np.arange(3), 0.1, 3, "1D Spectrum (Custom ROI)", 45, 65, "-65 C", hardware)
            _, loaded = io.load_background(path)
        self.assertEqual(loaded["hardware_metadata"]["spectrometer"]["serial_number"], "SPEC-1")
        self.assertEqual(loaded["source_file"], "background.json")


class PublicAxisKindTests(unittest.TestCase):
    """Covers work/work_OceanOptics.md Step 6: the shared classification that display/save
    logic and the API layer both use to decide whether flip_x must flip the x-axis together
    with y (native_wavelength/calibrated) or only y (pixel)."""

    def test_calibrated_when_calib_coeffs_present(self):
        window = Window()
        self.assertEqual(public_axis_kind(window), "calibrated")

    def test_native_wavelength_when_uncalibrated_but_camera_reports_one(self):
        window = Window()
        window.calib_coeffs = None
        window.thread.native_wavelengths = np.linspace(350.0, 1050.0, 128)
        self.assertEqual(public_axis_kind(window), "native_wavelength")

    def test_pixel_when_neither_calibrated_nor_native_wavelength_available(self):
        window = Window()
        window.calib_coeffs = None
        self.assertFalse(hasattr(window.thread, "native_wavelengths"))
        self.assertEqual(public_axis_kind(window), "pixel")

    def test_empty_native_wavelengths_falls_back_to_pixel(self):
        window = Window()
        window.calib_coeffs = None
        window.thread.native_wavelengths = np.array([])
        self.assertEqual(public_axis_kind(window), "pixel")

    def test_unit_is_none_for_pixel_regardless_of_raman_toggle(self):
        window = Window()
        window.calib_coeffs = None
        window.radio_spec_mode_raman = Checked(True)  # must not override the pixel priority
        self.assertIsNone(public_axis_unit(window, "pixel"))

    def test_unit_is_nm_for_native_wavelength_in_wavelength_mode(self):
        window = Window()
        window.calib_coeffs = None
        window.thread.native_wavelengths = np.linspace(350.0, 1050.0, 128)
        window.radio_spec_mode_raman = Checked(False)
        self.assertEqual(public_axis_unit(window), "nm")

    def test_unit_is_cm1_for_native_wavelength_in_raman_mode(self):
        window = Window()
        window.calib_coeffs = None
        window.thread.native_wavelengths = np.linspace(350.0, 1050.0, 128)
        window.radio_spec_mode_raman = Checked(True)
        self.assertEqual(public_axis_unit(window), "cm-1")

    def test_unit_follows_raman_toggle_when_calibrated_too(self):
        window = Window()  # calib_coeffs already set by the fixture
        window.radio_spec_mode_raman = Checked(True)
        self.assertEqual(public_axis_unit(window), "cm-1")

    def test_axis_state_source_is_oceanoptics_native_when_uncalibrated_with_native_wavelengths(self):
        from src.measurement_metadata import _axis_state  # exercise the richer provenance field too

        window = Window()
        window.calib_coeffs = None
        window.axis_source = "pixel"
        window.thread.native_wavelengths = np.linspace(350.0, 1050.0, 128)

        state = _axis_state(window)

        self.assertEqual(state["source"], "oceanoptics_native")
        self.assertIsNone(state["calibration_coefficients"])

    def test_axis_state_hardware_shamrock_is_still_preserved(self):
        from src.measurement_metadata import _axis_state

        window = Window()
        window.calib_coeffs = None
        window.axis_source = "hardware_shamrock"

        self.assertEqual(_axis_state(window)["source"], "hardware_shamrock")


class OceanOpticsCamera(Camera):
    """Mimics CameraThreadOceanOptics.get_cached_hardware_metadata() (Step 1/7): reports
    *effective* dark/nonlinearity correction flags rather than raw config request values."""

    def __init__(self, hardware_dark_corrected, nonlinearity_corrected):
        self._hardware_dark_corrected = hardware_dark_corrected
        self._nonlinearity_corrected = nonlinearity_corrected

    def get_cached_hardware_metadata(self):
        metadata = super().get_cached_hardware_metadata()
        metadata["hardware_dark_corrected"] = self._hardware_dark_corrected
        metadata["nonlinearity_corrected"] = self._nonlinearity_corrected
        return metadata


class BackgroundCorrectionMismatchTests(unittest.TestCase):
    """Covers work/work_OceanOptics.md Step 7: a background taken under different
    dark/nonlinearity correction settings must be flagged as mismatched rather than silently
    subtracted, mirroring every other hardware-state comparison in background_mismatch_fields()."""

    def _window_with_background(self, current_dark, current_nonlinearity, saved_dark, saved_nonlinearity):
        from src.measurement_metadata import background_mismatch_fields

        window = Window()
        window.thread = OceanOpticsCamera(current_dark, current_nonlinearity)
        capture = capture_hardware_state(window, 3)
        saved_hardware = build_hardware_metadata(window, capture, include_background=False)
        # Overwrite with the *saved* background's own correction state (as it would have been
        # captured at the time that background was acquired).
        saved_hardware["camera"]["hardware_dark_corrected"] = saved_dark
        saved_hardware["camera"]["nonlinearity_corrected"] = saved_nonlinearity
        window.loaded_bg_metadata = {
            "acquisition_time": 0.1,
            "accumulations": 3,
            "mode": "1D Spectrum (Custom ROI)",
            "roi_start": 45,
            "roi_end": 65,
            "source_file": "background.json",
            "hardware_metadata": saved_hardware,
        }
        return background_mismatch_fields(window, build_hardware_metadata(window, capture, include_background=False))

    def test_matching_correction_flags_report_no_mismatch(self):
        fields = self._window_with_background(True, False, True, False)
        self.assertNotIn("camera.hardware_dark_corrected", fields)
        self.assertNotIn("camera.nonlinearity_corrected", fields)

    def test_changed_dark_correction_is_flagged(self):
        fields = self._window_with_background(False, False, True, False)
        self.assertIn("camera.hardware_dark_corrected", fields)

    def test_changed_nonlinearity_correction_is_flagged(self):
        fields = self._window_with_background(True, True, True, False)
        self.assertIn("camera.nonlinearity_corrected", fields)

    def test_andor_backgrounds_without_the_field_are_unaffected(self):
        from src.measurement_metadata import background_mismatch_fields

        window = Window()  # plain Camera fixture - no hardware_dark_corrected key at all
        capture = capture_hardware_state(window, 3)
        saved_hardware = build_hardware_metadata(window, capture, include_background=False)
        window.loaded_bg_metadata = {
            "acquisition_time": 0.1,
            "accumulations": 3,
            "mode": "1D Spectrum (Custom ROI)",
            "roi_start": 45,
            "roi_end": 65,
            "source_file": "background.json",
            "hardware_metadata": saved_hardware,
        }
        fields = background_mismatch_fields(window, build_hardware_metadata(window, capture, include_background=False))
        self.assertNotIn("camera.hardware_dark_corrected", fields)
        self.assertNotIn("camera.nonlinearity_corrected", fields)


if __name__ == "__main__":
    unittest.main()
