import unittest

try:
    from src.ui.analysis_ui import AnalysisWindow
except ImportError:
    AnalysisWindow = None


class UnitForMetadataTests(unittest.TestCase):
    """AnalysisWindow._unit_for_metadata is a pure staticmethod, so it can be tested
    without constructing a QApplication/widget. Guards against the P1 bug where an
    uncalibrated spectrum (raw pixel x-axis) was mislabeled as nm and allowed into
    the pressure calculator.
    """

    def setUp(self):
        if AnalysisWindow is None:
            self.skipTest("PyQt6 is not importable in this environment")

    def test_calibrated_wavelength(self):
        meta = {"calib_coeffs": (690.0, 0.05, 0.0), "spec_mode": "Wavelength"}
        self.assertEqual(AnalysisWindow._unit_for_metadata(meta), "nm")

    def test_calibrated_raman_shift(self):
        meta = {"calib_coeffs": (0.0, 1.0, 0.0), "spec_mode": "Raman shift"}
        self.assertEqual(AnalysisWindow._unit_for_metadata(meta), "cm-1")

    def test_uncalibrated_is_pixel_even_with_wavelength_spec_mode(self):
        # spec_mode defaults to "Wavelength" in saved headers even when no
        # calibration was ever loaded -- calib_coeffs is the real signal.
        meta = {"calib_coeffs": None, "spec_mode": "Wavelength"}
        self.assertEqual(AnalysisWindow._unit_for_metadata(meta), "pixel")

    def test_none_metadata_is_pixel(self):
        self.assertEqual(AnalysisWindow._unit_for_metadata(None), "pixel")


if __name__ == "__main__":
    unittest.main()
