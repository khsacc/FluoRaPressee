"""Regression test for work/work_OceanOptics.md review round 5, point 4: _PagePaths.
apply_probe_result() unconditionally targeted the Princeton Instruments serial combo
(_pi_serial) and read "camera_serial_number" from the probe result, so a successful Ocean
Optics hardware probe (which reports "serial_number" and has its own _oo_serial combo) never
reached any visible field - "Read parameters from connected hardware" appeared to do nothing.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    from src.config_wizard import SUPPLIER_OCEANOPTICS, SUPPLIER_PI, _PagePaths
except ImportError:
    _PagePaths = None


def _probe_result(supplier, *, config, camera_candidates):
    return {
        "supplier": supplier,
        "config": config,
        "camera_candidates": camera_candidates,
        "successes": ["Ocean Optics device" if supplier == SUPPLIER_OCEANOPTICS else "PICam camera"],
        "errors": [],
    }


class OceanOpticsProbeResultReflectionTests(unittest.TestCase):
    def setUp(self):
        if _PagePaths is None:
            self.skipTest("PyQt6 is not importable in this environment")
        self.app = QApplication.instance() or QApplication([])
        self.page = _PagePaths()

    def test_single_device_serial_reaches_the_oceanoptics_field(self):
        result = _probe_result(
            SUPPLIER_OCEANOPTICS,
            config={"serial_number": "FLMS12345"},
            camera_candidates=[{"model": "USB4000", "serial_number": "FLMS12345", "interface": ""}],
        )

        self.page.apply_probe_result(result)

        self.assertEqual(self.page._oo_serial.currentData(), "FLMS12345")
        self.assertEqual(self.page._pi_serial.currentText(), "")

    def test_multiple_devices_populate_selectable_candidates(self):
        result = _probe_result(
            SUPPLIER_OCEANOPTICS,
            config={},  # multiple devices with no serial selected yet -> probe raised, no "serial_number" key
            camera_candidates=[
                {"model": "USB4000", "serial_number": "FLMS111", "interface": ""},
                {"model": "USB2000", "serial_number": "FLMS222", "interface": ""},
            ],
        )

        self.page.apply_probe_result(result)

        self.assertGreaterEqual(self.page._oo_serial.findData("FLMS111"), 0)
        self.assertGreaterEqual(self.page._oo_serial.findData("FLMS222"), 0)

    def test_princeton_probe_still_targets_the_pi_field(self):
        result = _probe_result(
            SUPPLIER_PI,
            config={"camera_serial_number": "0412060001"},
            camera_candidates=[{"model": "PIXIS", "serial_number": "0412060001", "interface": "USB"}],
        )

        self.page.apply_probe_result(result)

        self.assertEqual(self.page._pi_serial.currentData(), "0412060001")
        self.assertEqual(self.page._oo_serial.currentText(), "")


if __name__ == "__main__":
    unittest.main()
