import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.calibration_ui import CalibrationWindow


_APP = QApplication.instance() or QApplication([])


class CalibrationThresholdTests(unittest.TestCase):
    def test_threshold_supports_high_noise_spectra_and_shows_multiplier(self):
        window = CalibrationWindow()
        try:
            self.assertEqual(window.slider_threshold.maximum(), 500)
            self.assertEqual(window.slider_threshold.value(), 75)
            window.slider_threshold.setValue(320)
            self.assertEqual(window.slider_threshold_label.text(), "Threshold: 32.0× noise")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
