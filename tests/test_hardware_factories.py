import sys
import types
import unittest

# spectrometer_princeton.py imports pyserial at module load time; stub it when absent so this
# test (which never opens a serial port) still runs in lightweight environments without it -
# same convention as tests/test_spectrometer_princeton_metadata.py.
if "serial" not in sys.modules:
    try:
        import serial  # noqa: F401
    except ImportError:
        serial_stub = types.ModuleType("serial")
        serial_stub.SerialException = OSError
        serial_stub.Serial = None
        sys.modules["serial"] = serial_stub

from src.hardware.camera import CameraThread
from src.hardware.spectrometer import SpectrometerController, SpectrometerMoveThread


class CameraFactoryTests(unittest.TestCase):
    def test_default_model_is_andor(self):
        thread = CameraThread(config={}, debug=True)
        self.assertEqual(type(thread).__name__, "CameraThreadAndor")

    def test_princeton_instruments_model(self):
        thread = CameraThread(config={"model": "PrincetonInstruments"}, debug=True)
        self.assertEqual(type(thread).__name__, "CameraThreadPI")

    def test_ocean_optics_model(self):
        thread = CameraThread(config={"model": "OceanOptics"}, debug=True)
        self.assertEqual(type(thread).__name__, "CameraThreadOceanOptics")


class SpectrometerFactoryTests(unittest.TestCase):
    def test_default_model_is_andor(self):
        ctrl = SpectrometerController(config={}, debug=True)
        self.assertEqual(type(ctrl).__name__, "SpectrometerControllerAndor")

    def test_princeton_instruments_model(self):
        ctrl = SpectrometerController(config={"model": "PrincetonInstruments"}, debug=True)
        self.assertEqual(type(ctrl).__name__, "SpectrometerControllerPI")

    def test_ocean_optics_model(self):
        ctrl = SpectrometerController(config={"model": "OceanOptics"}, debug=True)
        self.assertEqual(type(ctrl).__name__, "SpectrometerControllerOceanOptics")

    def test_move_thread_dispatches_by_controller_module_for_each_vendor(self):
        for model, expected_class_name in (
            ("Andor", "SpectrometerMoveThread"),
            ("PrincetonInstruments", "SpectrometerMoveThread"),
            ("OceanOptics", "SpectrometerMoveThread"),
        ):
            with self.subTest(model=model):
                ctrl = SpectrometerController(config={"model": model}, debug=True)
                move_thread = SpectrometerMoveThread(ctrl, 1, 700.0)
                self.assertEqual(type(move_thread).__name__, expected_class_name)
                self.assertIn(
                    move_thread.__class__.__module__,
                    (
                        "src.hardware.spectrometer_andor",
                        "src.hardware.spectrometer_princeton",
                        "src.hardware.spectrometer_oceanoptics",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
