import json
import os
import tempfile
import unittest

import numpy as np

from src.file_io import DataFileIO
from src.measurement_metadata import build_hardware_metadata, capture_hardware_state


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


if __name__ == "__main__":
    unittest.main()
