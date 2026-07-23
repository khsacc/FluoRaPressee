import sys
import unittest

from src.hardware.pylablib_loader import import_pylablib_module


class PylablibLoaderTests(unittest.TestCase):
    def test_device_modules_load_without_legacy_qt(self):
        pylablib = import_pylablib_module("pylablib")
        andor = import_pylablib_module("pylablib.devices.Andor")
        princeton = import_pylablib_module("pylablib.devices.PrincetonInstruments")

        self.assertTrue(hasattr(andor, "AndorSDK2Camera"))
        self.assertTrue(hasattr(princeton, "PicamCamera"))
        self.assertFalse(pylablib.core.gui.qt_present)
        self.assertFalse(any(
            name == "PyQt5" or name.startswith("PyQt5.")
            for name in sys.modules
        ))

    def test_rejects_non_pylablib_module(self):
        with self.assertRaises(ValueError):
            import_pylablib_module("json")


if __name__ == "__main__":
    unittest.main()
