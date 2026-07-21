import os
import tempfile
import unittest

import numpy as np

from src.file_io import DataFileIO


def metadata(spec_mode="Wavelength", exc_wl=532.0):
    return {
        "grating": "600",
        "center_wl": 694.0,
        "acq_time": 0.1,
        "accum": 3,
        "calib_coeffs": (690.0, 0.05, -1e-6),
        "roi_start": 100,
        "roi_end": 140,
        "mode": "1D (ROI)",
        "spec_mode": spec_mode,
        "exc_wl": exc_wl,
        "hardware_metadata": {"camera_model": "Test Camera", "serial_number": "SN123"},
    }


class LoadSpectrum1dTests(unittest.TestCase):
    def test_round_trip_two_column(self):
        io = DataFileIO()
        x = np.linspace(690.0, 700.0, 20)
        y = np.sin(x)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.txt")
            io.save_spectrum_1d(path, x, y, metadata())
            xl, yl, y_raw, y_bg, meta = io.load_spectrum_1d(path)

        np.testing.assert_allclose(xl, x, rtol=1e-5)
        np.testing.assert_allclose(yl, y, rtol=1e-5)
        self.assertIsNone(y_raw)
        self.assertIsNone(y_bg)
        self.assertEqual(meta["grating"], "600")
        self.assertEqual(meta["spec_mode"], "Wavelength")
        self.assertAlmostEqual(meta["center_wl"], 694.0)
        self.assertEqual(meta["accum"], 3)
        self.assertEqual(meta["roi_start"], 100)
        self.assertEqual(meta["roi_end"], 140)
        self.assertEqual(meta["hardware_metadata"]["camera_model"], "Test Camera")
        for got, expected in zip(meta["calib_coeffs"], (690.0, 0.05, -1e-6)):
            self.assertAlmostEqual(got, expected)

    def test_round_trip_four_column_raw_and_background(self):
        io = DataFileIO()
        x = np.linspace(0.0, 3500.0, 15)
        y_sub = np.cos(x / 500.0)
        y_raw = y_sub + 5.0
        y_bg = np.full_like(x, 5.0)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data.txt")
            io.save_spectrum_1d(
                path, x, y_sub, metadata(spec_mode="Raman shift", exc_wl=532.0),
                raw_data=y_raw, bg_data=y_bg,
            )
            xl, yl, raw_l, bg_l, meta = io.load_spectrum_1d(path)

        np.testing.assert_allclose(yl, y_sub, rtol=1e-5)
        np.testing.assert_allclose(raw_l, y_raw, rtol=1e-5)
        np.testing.assert_allclose(bg_l, y_bg, rtol=1e-5)
        self.assertEqual(meta["spec_mode"], "Raman shift")
        self.assertAlmostEqual(meta["exc_wl"], 532.0)

    def test_load_raises_on_non_spectrum_file(self):
        io = DataFileIO()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "not_a_spectrum.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"signal": [1, 2, 3]}')
            with self.assertRaises(ValueError):
                io.load_spectrum_1d(path)

    def test_looks_like_spectrum_file(self):
        io = DataFileIO()
        with tempfile.TemporaryDirectory() as directory:
            spectrum_path = os.path.join(directory, "data.txt")
            io.save_spectrum_1d(spectrum_path, np.array([1.0, 2.0]), np.array([1.0, 2.0]), metadata())
            self.assertTrue(io.looks_like_spectrum_file(spectrum_path))

            bg_path = os.path.join(directory, "background.txt")
            io.save_background(bg_path, np.array([1.0, 2.0]), 0.1, 1, "1D (ROI)", 100, 140, "-65")
            self.assertFalse(io.looks_like_spectrum_file(bg_path))

            fit_path = os.path.join(directory, "data_fitting_results.txt")
            io.save_fitting_results(fit_path, {
                "R2": 0.99,
                "peaks": [{"position": 1.0, "position_err": 0.1, "width": 1.0, "width_err": 0.1}],
                "baseline": {"requested": "Constant", "selected": "Constant"},
            }, "Gauss")
            self.assertFalse(io.looks_like_spectrum_file(fit_path))


if __name__ == "__main__":
    unittest.main()
