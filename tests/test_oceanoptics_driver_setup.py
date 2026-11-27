"""Driver setup decisions without downloading or changing Windows USB drivers."""

import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch


_spec = importlib.util.spec_from_file_location(
    "oceanoptics_driver_setup",
    Path(__file__).resolve().parents[1] / "packaging" / "oceanoptics_driver.py",
)
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)


class DriverSetupTests(unittest.TestCase):
    def run_setup(self, detected, setup_ok=True, admin=True):
        output = io.StringIO()
        with patch.object(driver.sys, "platform", "win32"), \
                patch.object(driver, "version_details", return_value="test"), \
                patch.object(driver, "hold_installer_mutex"), \
                patch.object(driver, "_is_admin", return_value=admin), \
                patch.object(driver, "_verify_device", side_effect=detected), \
                patch.object(driver, "_install_driver", return_value=setup_ok) as install, \
                redirect_stdout(output):
            result = driver.main()
        return result, install, output.getvalue()

    def test_already_detected_skips_driver_changes_even_without_admin(self):
        result, install, output = self.run_setup([True], admin=False)
        self.assertEqual(result, 0)
        install.assert_not_called()
        self.assertIn("No USB drivers were changed", output)

    def test_partial_install_failure_does_not_hide_successful_detection(self):
        result, install, output = self.run_setup([False, True], setup_ok=False)
        self.assertEqual(result, 0)
        install.assert_called_once_with()
        self.assertIn("WARNING", output)
        self.assertIn("confirms detection only", output)

    def test_upstream_zero_exit_does_not_confirm_an_absent_instrument(self):
        result, install, output = self.run_setup([False, False])
        self.assertEqual(result, 1)
        install.assert_called_once_with()
        self.assertIn("NOT confirmed", output)

    def test_failed_install_and_no_device_remains_a_failure(self):
        result, _, _ = self.run_setup([False, False], setup_ok=False)
        self.assertEqual(result, 1)

    def test_installation_requires_admin_when_device_is_not_detected(self):
        result, install, output = self.run_setup([False], admin=False)
        self.assertEqual(result, 1)
        install.assert_not_called()
        self.assertIn("administrator rights are required", output)


class SeaBreezeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.seabreeze = types.ModuleType("seabreeze")
        self.seabreeze.use = Mock()
        self.spectrometers = types.ModuleType("seabreeze.spectrometers")
        self.spectrometers.list_devices = Mock()
        self.os_setup = types.ModuleType("seabreeze.os_setup")
        self.os_setup.main = Mock()
        self.modules = patch.dict(sys.modules, {
            "seabreeze": self.seabreeze,
            "seabreeze.spectrometers": self.spectrometers,
            "seabreeze.os_setup": self.os_setup,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_detection_uses_the_distributed_cseabreeze_backend(self):
        for devices, expected in (([], False), (["USB4000: test"], True)):
            with self.subTest(devices=devices):
                self.spectrometers.list_devices.return_value = devices
                self.assertEqual(driver._verify_device(), expected)
        self.seabreeze.use.assert_called_with("cseabreeze")

    def test_enumeration_error_does_not_confirm_detection(self):
        self.spectrometers.list_devices.side_effect = RuntimeError("USB unavailable")
        self.assertFalse(driver._verify_device())

    def test_upstream_exit_codes_are_handled_without_exiting_the_tool(self):
        for code, expected in ((0, True), (1, False)):
            with self.subTest(code=code):
                self.os_setup.main.side_effect = SystemExit(code)
                self.assertEqual(driver._install_driver(), expected)

    def test_upstream_exception_does_not_skip_final_detection(self):
        self.os_setup.main.side_effect = RuntimeError("Download failed")
        self.assertFalse(driver._install_driver())


if __name__ == "__main__":
    unittest.main()
