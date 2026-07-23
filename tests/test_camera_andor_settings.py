import unittest
import sys
import types
from types import SimpleNamespace


class _Signal:
    def connect(self, callback):
        pass

    def emit(self, *args):
        pass


class _QThread:
    def __init__(self):
        pass


try:
    from PyQt6.QtCore import QThread  # noqa: F401
except ImportError:
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QThread = _QThread
    qtcore.pyqtSignal = lambda *args, **kwargs: _Signal()
    pyqt6 = types.ModuleType("PyQt6")
    pyqt6.QtCore = qtcore
    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qtcore

from src.hardware.camera_andor import CameraThreadAndor


class FakeAndorCamera:
    def __init__(self, fvb_supported=True, max_vertical_binning=32):
        self.fvb_supported = fvb_supported
        self.max_vertical_binning = max_vertical_binning
        self.calls = []

    def set_read_mode(self, mode):
        self.calls.append(("set_read_mode", mode))
        if not self.fvb_supported:
            raise RuntimeError("FVB unavailable")
        return mode

    def get_roi_limits(self, hbin=1, vbin=1):
        return (
            SimpleNamespace(maxbin=1),
            SimpleNamespace(maxbin=self.max_vertical_binning),
        )

    def set_roi(self, hstart, hend, vstart, vend, hbin=1, vbin=1):
        applied = (hstart, hend, vstart, vend, hbin, vbin)
        self.calls.append(("set_roi", applied))
        return applied


class AndorCameraSettingsTests(unittest.TestCase):
    def make_thread(self, camera):
        thread = CameraThreadAndor(debug=False)
        thread.cam = camera
        thread.det_width = 1024
        thread.det_height = 127
        return thread

    def test_full_range_uses_native_fvb(self):
        camera = FakeAndorCamera()
        thread = self.make_thread(camera)
        thread.roi_mode = "1d_full"

        applied = thread._apply_camera_settings()

        self.assertEqual(applied["read_mode"], "fvb")
        self.assertEqual(applied["vertical_end"], 127)
        self.assertEqual(applied["output_rows"], 1)
        self.assertNotIn("set_roi", [call[0] for call in camera.calls])

    def test_full_range_fallback_preserves_all_detector_rows(self):
        camera = FakeAndorCamera(fvb_supported=False)
        thread = self.make_thread(camera)
        thread.roi_mode = "1d_full"

        applied = thread._apply_camera_settings()

        self.assertEqual(applied["read_mode"], "image")
        self.assertEqual(applied["vertical_start"], 0)
        self.assertEqual(applied["vertical_end"], 127)
        self.assertEqual(applied["vertical_binning"], 1)
        self.assertEqual(applied["output_rows"], 127)
        self.assertTrue(applied["software_vertical_sum"])

    def test_custom_roi_uses_largest_exact_supported_binning(self):
        camera = FakeAndorCamera(max_vertical_binning=32)
        thread = self.make_thread(camera)
        thread.roi_mode = "1d_roi"
        thread.roi_vstart = 45
        thread.roi_vend = 65

        applied = thread._apply_camera_settings()

        self.assertEqual(applied["vertical_binning"], 20)
        self.assertEqual(applied["output_rows"], 1)
        self.assertEqual(applied["vertical_start"], 45)
        self.assertEqual(applied["vertical_end"], 65)

    def test_invalid_custom_roi_is_rejected(self):
        thread = self.make_thread(FakeAndorCamera())
        thread.roi_mode = "1d_roi"
        thread.roi_vstart = 65
        thread.roi_vend = 65

        with self.assertRaisesRegex(ValueError, "Invalid vertical ROI"):
            thread._apply_camera_settings()

    def test_cached_metadata_contains_applied_readout(self):
        thread = self.make_thread(FakeAndorCamera())
        thread.roi_mode = "1d_roi"
        thread.roi_vstart = 45
        thread.roi_vend = 65
        thread._apply_camera_settings()

        metadata = thread.get_cached_hardware_metadata()

        self.assertEqual(metadata["read_mode"], "image")
        self.assertEqual(metadata["roi"]["vertical_start"], 45)
        self.assertEqual(metadata["binning"]["vertical"], 20)
        self.assertFalse(metadata["software_vertical_sum"])


if __name__ == "__main__":
    unittest.main()
