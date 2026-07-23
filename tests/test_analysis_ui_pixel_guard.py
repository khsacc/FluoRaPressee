import os
import tempfile
import unittest

import numpy as np

# Offscreen unless the environment already overrides it, so these tests never pop a
# real window when PyQt6 is importable (they still fully skip when it isn't, e.g. the
# broken PyQt6 install some environments run pytest with -- see test_analysis_ui_units.py).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from src.ui.analysis_ui import AnalysisWindow
    from src.core.file_io import DataFileIO
except ImportError:
    AnalysisWindow = None


def _spectrum_metadata(calib_coeffs):
    return {
        "grating": "600", "center_wl": 694.0, "acq_time": 0.1, "accum": 1,
        "calib_coeffs": calib_coeffs, "roi_start": 100, "roi_end": 140,
        "mode": "1D (ROI)", "spec_mode": "Wavelength", "exc_wl": 532.0,
        "hardware_metadata": None,
    }


class PixelPeaksNeverReachPressureWindowTests(unittest.TestCase):
    """Regression test for: open a calibrated (nm) file, then load an
    uncalibrated (pixel) file while the embedded pressure calculator is visible.
    The pressure window must not silently compute/display/save a pressure from
    raw pixel positions.
    """

    def setUp(self):
        if AnalysisWindow is None:
            self.skipTest("PyQt6 is not importable in this environment")
        # Must keep a live reference -- QApplication([]) with nothing holding onto the
        # result can be garbage-collected immediately, which then aborts the process
        # (not a catchable Python exception) on the next QWidget construction.
        self.app = QApplication.instance() or QApplication([])
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        QMessageBox.information = staticmethod(lambda *a, **k: None)

        self.tmpdir = tempfile.TemporaryDirectory()
        io = DataFileIO()

        x_cal = np.linspace(690.0, 700.0, 100)
        y_cal = (
            100 * np.exp(-((x_cal - 694.0) ** 2) / (2 * 0.3 ** 2))
            + 100 * np.exp(-((x_cal - 694.5) ** 2) / (2 * 0.3 ** 2))
            + 10
        )
        self.calibrated_path = os.path.join(self.tmpdir.name, "calibrated.txt")
        io.save_spectrum_1d(self.calibrated_path, x_cal, y_cal, _spectrum_metadata((690.0, 0.101, 0.0)))

        x_pix = np.arange(50, dtype=float)
        y_pix = (
            100 * np.exp(-((x_pix - 20) ** 2) / (2 * 1.5 ** 2))
            + 100 * np.exp(-((x_pix - 30) ** 2) / (2 * 1.5 ** 2))
            + 10
        )
        self.pixel_path = os.path.join(self.tmpdir.name, "uncalibrated.txt")
        io.save_spectrum_1d(self.pixel_path, x_pix, y_pix, _spectrum_metadata(None))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_pixel_file_after_calibrated_does_not_leak_into_pressure_window(self):
        win = AnalysisWindow()
        win.show()

        win.load_file(self.calibrated_path)
        self.assertTrue(win.pressure_window.isVisible())
        self.assertTrue(win.pressure_window.isEnabled())
        self.assertIsNotNone(win.pressure_window.current_pressure)

        win.load_file(self.pixel_path)

        self.assertEqual(win.current_unit, "pixel")
        self.assertEqual(win.pressure_window.current_fit_peaks, [])
        self.assertIsNone(win.pressure_window.current_pressure)
        self.assertNotIn("Calculated Pressure", win.fitting_text.toHtml())

        saved_path = os.path.join(self.tmpdir.name, "pixel_fit_results.txt")
        QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (saved_path, ""))
        win.on_save_fit_clicked()
        with open(saved_path, encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("Pressure_GPa", content)


if __name__ == "__main__":
    unittest.main()
