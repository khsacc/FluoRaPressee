import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    from src.ui.config_wizard import SUPPLIER_OCEANOPTICS
    from src.ui.menu.hardware_config_dialog import HardwareConfigDialog, _DisplayTab
except ImportError:
    QApplication = None


class HardwareConfigTemperatureTests(unittest.TestCase):
    def setUp(self):
        if QApplication is None:
            self.skipTest("PyQt6 is not importable in this environment")
        self.app = QApplication.instance() or QApplication([])

    def test_no_cooler_hides_field_and_omits_temperature(self):
        tab = _DisplayTab(temperature_control_available=False)
        tab.load({"flip_x": False, "default_temperature": -65})

        self.assertTrue(tab._temp_label.isHidden())
        self.assertTrue(tab._default_temp.isHidden())
        self.assertNotIn("default_temperature", tab.collect())

    def test_cooler_shows_field_and_saves_temperature(self):
        tab = _DisplayTab(temperature_control_available=True)
        tab.load({"flip_x": False, "default_temperature": -65})

        self.assertFalse(tab._temp_label.isHidden())
        self.assertFalse(tab._default_temp.isHidden())
        self.assertEqual(tab.collect()["default_temperature"], -65)

    def test_unknown_capability_does_not_invent_or_delete_temperature(self):
        absent = _DisplayTab(temperature_control_available=None)
        absent.load({"flip_x": False})
        self.assertNotIn("default_temperature", absent.collect())

        existing = _DisplayTab(temperature_control_available=None)
        existing.load({"flip_x": False, "default_temperature": -70})
        self.assertEqual(existing.collect()["default_temperature"], -70)

    def test_oceanoptics_dialog_removes_stale_temperature_and_keeps_identity(self):
        config = {
            "model": SUPPLIER_OCEANOPTICS,
            "serial_number": "USB2+F02651",
            "seabreeze_backend": None,
            "grating": [{
                "index": 1,
                "grooves": 0,
                "defaultROI": {"from": 0, "to": 1},
            }],
            "flip_x": False,
            "default_temperature": -65,
        }
        dialog = HardwareConfigDialog(
            config, temperature_control_available=False
        )

        result = dialog._collect_and_validate()

        self.assertIsNotNone(result)
        self.assertEqual(result["model"], SUPPLIER_OCEANOPTICS)
        self.assertEqual(result["serial_number"], "USB2+F02651")
        self.assertNotIn("default_temperature", result)


if __name__ == "__main__":
    unittest.main()
