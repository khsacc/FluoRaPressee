import ctypes
import sys
import types
import unittest

import numpy as np

try:
    import PyQt6.QtCore  # noqa: F401
except ImportError:
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QThread = object
    qtcore.pyqtSignal = lambda *args, **kwargs: None
    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtCore = qtcore
    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qtcore

from src.spectrometer_andor import SpectrometerControllerAndor


class _Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class _FakeShamrock:
    def __init__(self):
        self.number_pixels = None
        self.pixel_width = None
        self.ShamrockSetNumberPixels = _Function(self._set_number_pixels)
        self.ShamrockSetPixelWidth = _Function(self._set_pixel_width)
        self.ShamrockGetCalibration = _Function(self._get_calibration)

    def _set_number_pixels(self, device, count):
        self.number_pixels = count.value
        return 20202

    def _set_pixel_width(self, device, width):
        self.pixel_width = width.value
        return 20202

    @staticmethod
    def _get_calibration(device, output, count):
        for index in range(count.value):
            output[index] = 690.0 + index * 0.05
        return 20202


class AndorCalibrationAxisTests(unittest.TestCase):
    def test_supplies_detector_geometry_and_returns_axis(self):
        controller = SpectrometerControllerAndor()
        controller.is_initialized = True
        controller.shamrock = _FakeShamrock()

        axis = controller.get_calibration_seed_axis(8, 26.0)

        self.assertEqual(controller.shamrock.number_pixels, 8)
        self.assertAlmostEqual(controller.shamrock.pixel_width, 26.0)
        np.testing.assert_allclose(axis, 690.0 + np.arange(8) * 0.05)

    def test_disconnected_controller_returns_none(self):
        controller = SpectrometerControllerAndor()
        self.assertIsNone(controller.get_calibration_seed_axis(8, 26.0))


if __name__ == "__main__":
    unittest.main()
