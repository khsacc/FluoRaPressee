import sys
import types
import unittest
from unittest.mock import patch

from src import hardware_probe


class _FakeDevice:
    def __init__(self, model, serial_number):
        self.model = model
        self.serial_number = serial_number


def _install_fake_seabreeze(devices):
    spectrometers_module = types.ModuleType("seabreeze.spectrometers")
    spectrometers_module.list_devices = lambda: list(devices)
    seabreeze_module = types.ModuleType("seabreeze")
    seabreeze_module.use = lambda backend: None
    seabreeze_module.spectrometers = spectrometers_module
    sys.modules["seabreeze"] = seabreeze_module
    sys.modules["seabreeze.spectrometers"] = spectrometers_module


def _uninstall_fake_seabreeze():
    sys.modules.pop("seabreeze", None)
    sys.modules.pop("seabreeze.spectrometers", None)


class HardwareProbeTests(unittest.TestCase):
    def test_camera_success_is_kept_when_spectrograph_fails(self):
        def camera_probe(result, config):
            result["config"]["default_temperature"] = -70
            result["detected_hardware"]["camera"] = {
                "detector_size_px": {"width": 1024, "height": 127},
            }

        def spectrograph_probe(result, config):
            raise RuntimeError("not connected")

        with patch.object(hardware_probe, "_probe_andor_camera", camera_probe), patch.object(
            hardware_probe, "_probe_andor_spectrometer", spectrograph_probe
        ):
            result = hardware_probe.probe_initial_hardware("Andor", {})

        self.assertEqual(result["config"]["default_temperature"], -70)
        self.assertEqual(result["successes"], ["Andor camera"])
        self.assertIn("not connected", result["errors"][0])

    def test_detected_gratings_keep_details_and_use_centered_roi(self):
        result = {
            "detected_hardware": {
                "camera": {"detector_size_px": {"width": 1024, "height": 127}}
            }
        }
        gratings = [{
            "index": 1,
            "grooves": 600,
            "blaze": "500 nm",
            "wavelength_limits_nm": {"min": 0.0, "max": 1200.0},
        }]

        config_gratings = hardware_probe._config_gratings(gratings, result)

        self.assertEqual(config_gratings[0]["blaze"], "500 nm")
        self.assertEqual(
            config_gratings[0]["wavelength_limits_nm"],
            {"min": 0.0, "max": 1200.0},
        )
        self.assertEqual(config_gratings[0]["defaultROI"], {"from": 53, "to": 73})

    def test_identity_values_are_normalized_for_json(self):
        result = {"config": {}}

        hardware_probe._merge_identity(
            result,
            "camera",
            {"model": "DU-401", "serial_number": 12345},
        )

        self.assertEqual(
            result["config"]["hardware_identity"]["camera"],
            {"model": "DU-401", "serial_number": "12345"},
        )


class OceanOpticsProbeTests(unittest.TestCase):
    """Covers work/work_OceanOptics.md Step 9 (optional priority): probe_initial_hardware()
    must never crash the setup wizard even though list_devices()'s exact return shape is
    unverified against real seabreeze (see the TODO in hardware_probe._probe_oceanoptics)."""

    def setUp(self):
        self.addCleanup(_uninstall_fake_seabreeze)

    def test_single_device_records_identity_under_both_categories(self):
        _install_fake_seabreeze([_FakeDevice("USB4000", "FLMS12345")])

        result = hardware_probe.probe_initial_hardware("OceanOptics", {})

        self.assertEqual(result["successes"], ["Ocean Optics device"])
        self.assertEqual(
            result["config"]["hardware_identity"]["camera"],
            {"model": "USB4000", "serial_number": "FLMS12345"},
        )
        self.assertEqual(
            result["config"]["hardware_identity"]["spectrometer"],
            {"model": "USB4000", "serial_number": "FLMS12345"},
        )
        self.assertEqual(result["config"]["serial_number"], "FLMS12345")

    def test_no_devices_reports_error_without_crashing(self):
        _install_fake_seabreeze([])

        result = hardware_probe.probe_initial_hardware("OceanOptics", {})

        self.assertEqual(result["successes"], [])
        self.assertTrue(result["errors"])

    def test_multiple_devices_without_selected_serial_reports_error(self):
        _install_fake_seabreeze([
            _FakeDevice("USB2000", "AAA"),
            _FakeDevice("USB4000", "BBB"),
        ])

        result = hardware_probe.probe_initial_hardware("OceanOptics", {})

        self.assertEqual(result["successes"], [])
        self.assertIn("Multiple devices detected", result["errors"][0])

    def test_multiple_devices_with_matching_serial_selects_it(self):
        _install_fake_seabreeze([
            _FakeDevice("USB2000", "AAA"),
            _FakeDevice("USB4000", "BBB"),
        ])

        result = hardware_probe.probe_initial_hardware(
            "OceanOptics", {"serial_number": "BBB"}
        )

        self.assertEqual(
            result["config"]["hardware_identity"]["camera"]["serial_number"], "BBB"
        )

    def test_unsupported_supplier_reports_error_without_crashing(self):
        result = hardware_probe.probe_initial_hardware("SomeOtherVendor", {})
        self.assertIn("Unsupported supplier", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
