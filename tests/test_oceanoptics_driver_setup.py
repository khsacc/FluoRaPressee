"""Driver setup decisions without downloading or changing Windows USB drivers."""

import ctypes
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from contextlib import nullcontext, redirect_stdout
from unittest.mock import Mock, patch
from zipfile import ZipFile


_spec = importlib.util.spec_from_file_location(
    "oceanoptics_driver_setup",
    Path(__file__).resolve().parents[1] / "packaging" / "oceanoptics_driver.py",
)
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)


class DriverSetupTests(unittest.TestCase):
    device = types.SimpleNamespace(instance_id="target", hardware_ids=(r"USB\VID_2457&PID_1022",))
    other_device = types.SimpleNamespace(instance_id="other", hardware_ids=(r"USB\VID_2457&PID_1002",))

    def run_setup(self, detected, setup_ok=True, admin=True, devices=None, ready=None):
        output = io.StringIO()
        devices = [self.device] if devices is None else devices
        ready = [{self.device.instance_id}] * 2 if ready is None else ready
        with patch.object(driver.sys, "platform", "win32"), \
                patch.object(driver, "version_details", return_value="test"), \
                patch.object(driver, "hold_installer_mutex"), \
                patch.object(driver, "_is_admin", return_value=admin), \
                patch.object(driver, "_verify_device", side_effect=detected), \
                patch.object(driver.oceanoptics_windows, "connected_devices",
                             return_value=nullcontext(("api", "handle", devices))), \
                patch.object(driver.oceanoptics_windows, "seabreeze_interfaces", side_effect=ready), \
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
        install.assert_called_once_with("api", "handle", [self.device])
        self.assertIn("WARNING", output)
        self.assertIn("confirms detection only", output)

    def test_successful_registration_does_not_confirm_an_absent_instrument(self):
        result, install, output = self.run_setup([False, False])
        self.assertEqual(result, 1)
        install.assert_called_once_with("api", "handle", [self.device])
        self.assertIn("NOT confirmed", output)

    def test_failed_install_and_no_device_remains_a_failure(self):
        result, _, _ = self.run_setup([False, False], setup_ok=False)
        self.assertEqual(result, 1)

    def test_installation_requires_admin_when_device_is_not_detected(self):
        result, install, output = self.run_setup([False], admin=False)
        self.assertEqual(result, 1)
        install.assert_not_called()
        self.assertIn("administrator rights are required", output)

    def test_no_connected_device_skips_the_package_download(self):
        result, install, output = self.run_setup([False], devices=[])
        self.assertEqual(result, 1)
        install.assert_not_called()
        self.assertIn("no connected Ocean Optics USB device", output)

    def test_one_detected_instrument_does_not_hide_another_device_missing_a_driver(self):
        result, install, output = self.run_setup(
            [True, True], devices=[self.device, self.other_device], ready=[{"other"}, {"other"}]
        )
        self.assertEqual(result, 1)
        install.assert_called_once_with("api", "handle", [self.device])
        self.assertIn(self.device.hardware_ids[0], output)


class DriverPackageTests(unittest.TestCase):
    def test_extract_keeps_the_regular_inf_and_its_dependencies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "drivers.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("OOI_USB4000.inf", "regular")
                archive.writestr("OOI_USB4000_XP.inf", "xp")
                archive.writestr("OOI_USB4000.cat", "catalog")
                archive.writestr("amd64/WinUSBCoInstaller.dll", "coinstaller")
            package = root / "package"
            driver._extract_driver_package(archive_path, package)
            self.assertEqual((package / "OOI_USB4000.inf").read_text(), "regular")
            self.assertFalse((package / "OOI_USB4000_XP.inf").exists())
            self.assertTrue((package / "OOI_USB4000.cat").is_file())
            self.assertTrue((package / "amd64/WinUSBCoInstaller.dll").is_file())

    def test_pnputil_receives_only_distinct_matched_infs(self):
        package = Path("package")
        match = package / "OOI_USB4000.inf"
        devices = [DriverSetupTests.device, DriverSetupTests.device, DriverSetupTests.other_device]
        with patch.object(driver.oceanoptics_windows, "best_matching_inf",
                          side_effect=[match, match, None]), \
                patch.object(driver.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                patch.dict(driver.os.environ, {"SystemRoot": "Windows", "PROCESSOR_ARCHITEW6432": ""}), \
                patch("builtins.input", return_value="yes"), redirect_stdout(io.StringIO()):
            self.assertFalse(driver._install_matching_infs("api", "handle", devices, package))
        pnputil = Path("Windows") / "System32" / "pnputil.exe"
        run.assert_called_once_with([str(pnputil), "/add-driver", str(match), "/install"], check=False)

    def test_no_matching_inf_skips_pnputil_and_the_prompt(self):
        with patch.object(driver.oceanoptics_windows, "best_matching_inf", return_value=None), \
                patch.object(driver.subprocess, "run") as run, \
                patch("builtins.input") as confirm, redirect_stdout(io.StringIO()):
            self.assertFalse(driver._install_matching_infs(
                "api", "handle", [DriverSetupTests.device], Path("package")
            ))
        run.assert_not_called()
        confirm.assert_not_called()


class WindowsDeviceEnumerationTests(unittest.TestCase):
    def test_seabreeze_interface_lookup_uses_null_enumerator(self):
        windows = driver.oceanoptics_windows
        api = Mock()

        def get_devices(guid, enumerator, parent, flags):
            # Windows rejects a bus name such as "USB" in interface mode.
            if enumerator is not None:
                raise OSError(13, "The data is invalid")
            self.assertEqual(
                bytes(ctypes.cast(guid, ctypes.POINTER(windows._Guid)).contents),
                windows._SEABREEZE_INTERFACE.bytes_le,
            )
            self.assertEqual(flags, windows._DIGCF_PRESENT | windows._DIGCF_DEVICEINTERFACE)
            return "interfaces"

        api.SetupDiGetClassDevsW.side_effect = get_devices
        info = windows._DeviceInfo()
        with patch.object(windows, "_device_infos", return_value=[info]), \
                patch.object(windows, "_instance_id", return_value="USB\\VID_2457&PID_101E\\TEST"):
            self.assertEqual(windows.seabreeze_interfaces(api), {"USB\\VID_2457&PID_101E\\TEST"})
        api.SetupDiDestroyDeviceInfoList.assert_called_once_with("interfaces")

    def test_connected_device_lookup_still_filters_by_usb_bus(self):
        windows = driver.oceanoptics_windows
        api = Mock()
        api.SetupDiGetClassDevsW.return_value = "devices"
        with patch.object(windows, "_load_setupapi", return_value=api), \
                patch.object(windows, "_device_infos", return_value=[]):
            with windows.connected_devices() as (_, handle, devices):
                self.assertEqual(handle, "devices")
                self.assertEqual(devices, [])
        api.SetupDiGetClassDevsW.assert_called_once_with(
            None, "USB", None, windows._DIGCF_PRESENT | windows._DIGCF_ALLCLASSES
        )
        api.SetupDiDestroyDeviceInfoList.assert_called_once_with("devices")


class SeaBreezeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.seabreeze = types.ModuleType("seabreeze")
        self.seabreeze.use = Mock()
        self.spectrometers = types.ModuleType("seabreeze.spectrometers")
        self.spectrometers.list_devices = Mock()
        self.modules = patch.dict(sys.modules, {
            "seabreeze": self.seabreeze,
            "seabreeze.spectrometers": self.spectrometers,
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


if __name__ == "__main__":
    unittest.main()
