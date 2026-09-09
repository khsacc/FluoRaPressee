import json
import sys
import types
import unittest
from unittest.mock import patch

# The test exercises controller caching/status only and never opens a serial
# port. Keep it runnable in lightweight CI environments without pyserial.
if "serial" not in sys.modules:
    try:
        import serial  # noqa: F401
    except ImportError:
        serial_stub = types.ModuleType("serial")
        serial_stub.SerialException = OSError
        serial_stub.Serial = None
        sys.modules["serial"] = serial_stub

if "PyQt6.QtCore" not in sys.modules:
    try:
        from PyQt6.QtCore import QThread  # noqa: F401
    except ImportError:
        pyqt_stub = types.ModuleType("PyQt6")
        qtcore_stub = types.ModuleType("PyQt6.QtCore")

        class QThread:
            pass

        def pyqtSignal(*_args, **_kwargs):
            return object()

        qtcore_stub.QThread = QThread
        qtcore_stub.pyqtSignal = pyqtSignal
        pyqt_stub.QtCore = qtcore_stub
        sys.modules["PyQt6"] = pyqt_stub
        sys.modules["PyQt6.QtCore"] = qtcore_stub

from src.hardware.spectrometer_princeton import SpectrometerControllerPI
from src.hardware.princeton_calibration import build_seed_axis, starting_parameters


_CALIBRATION_XML = """
<monochromators>
  <sp2500><startingParams gamma="17" focus="500" delta="0" eta="0.75" /></sp2500>
  <sp2700><startingParams gamma="13.1" focus="750" delta="0.7" eta="0.75" /></sp2700>
  <SCT320><startingParams gamma="18" focus="320" delta="8" eta="0.86" /></SCT320>
</monochromators>
"""


class _ArrayFactory:
    def __getitem__(self, _type):
        return lambda values: list(values)


class _FakeMonoCalibrate:
    def __init__(self, model, number_pixels, pixel_width_um, flags):
        self.defaults = None

    def LoadConfigParams(self):
        return _CALIBRATION_XML

    def ApplyDefaultParamaters(self, *values):
        self.defaults = values

    def GratingAngleCalc(self):
        return 0.25


class _FakeSpectralCal:
    def dispersedWave(self, gamma, spacing, order, center, detector_angle,
                      focus, pixel_width, offset, grating_angle, lens_correct):
        return center + offset * pixel_width


class FakePIController(SpectrometerControllerPI):
    def __init__(self, responses=None):
        super().__init__(config={"model": "PrincetonInstruments", "com_port": "COM7"})
        self.responses = responses or {}
        self.commands = []
        self.spec = object()
        self.is_initialized = True

    def _send_command(self, command, timeout_s=5.0, cancellable=False):
        self.commands.append(command)
        response = self.responses.get(command, [])
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response()
        return list(response)


class PrincetonSpectrometerMetadataTests(unittest.TestCase):
    def _controller(self):
        return FakePIController({
            "MODEL": ["SP-2750"],
            "SERIAL": ["SPEC-123"],
            "?NM": ["694.250 nm"],
            "?GRATING": ["2"],
            "?GRATINGS": [
                "1 600 g/mm BLZ=500nm",
                "2 1200 g/mm BLZ=750nm",
            ],
        })

    def test_hardware_reads_populate_cache_and_cached_getter_does_not_query(self):
        controller = self._controller()

        self.assertEqual(
            controller.get_device_identity(),
            {"model": "SP-2750", "serial_number": "SPEC-123"},
        )
        self.assertEqual(controller.get_gratings()[1], {"index": 2, "grooves": 1200})
        self.assertEqual(controller.get_wavelength(), 694.25)
        self.assertEqual(controller.get_grating(), 2)

        commands_before = list(controller.commands)
        metadata = controller.get_cached_hardware_metadata()

        self.assertEqual(controller.commands, commands_before)
        self.assertEqual(metadata["serial_number"], "SPEC-123")
        self.assertEqual(metadata["grating"]["index"], 2)
        self.assertEqual(metadata["grating"]["grooves_per_mm"], 1200)
        self.assertEqual(metadata["center_wavelength_nm"], 694.25)
        self.assertIsNone(metadata["wavelength_limits_nm"])

    def test_status_snapshot_is_json_serializable_and_refreshes_cache(self):
        controller = self._controller()

        snapshot = controller.get_status_snapshot()

        json.dumps(snapshot)
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["backend"], "princeton_acton")
        position = {
            entry["key"]: entry
            for entry in snapshot["sections"]["Current position"]
        }
        self.assertEqual(position["centre_wavelength"]["value"], 694.25)
        self.assertEqual(position["grating"]["value"], 2)
        self.assertEqual(
            snapshot["sections"]["Optical geometry"][0]["state"],
            "unsupported",
        )

        metadata = controller.get_cached_hardware_metadata()
        self.assertEqual(metadata["serial_number"], "SPEC-123")
        self.assertEqual(metadata["grating"]["grooves_per_mm"], 1200)

    def test_successful_moves_update_cached_position(self):
        controller = self._controller()
        controller.get_gratings()
        controller.responses.update({
            "700.000 GOTO": [],
            "?NM": ["700.125 nm"],
            "2 GRATING": [],
            "?GRATING": ["2"],
        })

        self.assertTrue(controller.set_wavelength(700.0))
        self.assertTrue(controller.set_grating(2))

        metadata = controller.get_cached_hardware_metadata()
        self.assertEqual(metadata["center_wavelength_nm"], 700.125)
        self.assertEqual(metadata["grating"]["index"], 2)
        self.assertEqual(metadata["grating"]["grooves_per_mm"], 1200)

    def test_one_failed_status_field_does_not_fail_snapshot(self):
        controller = self._controller()
        controller.responses["MODEL"] = RuntimeError("MODEL is unavailable")

        snapshot = controller.get_status_snapshot()

        identity = {
            entry["key"]: entry
            for entry in snapshot["sections"]["Spectrograph identification"]
        }
        self.assertTrue(snapshot["available"])
        self.assertEqual(identity["model"]["state"], "error")
        self.assertEqual(identity["serial_number"]["value"], "SPEC-123")

    def test_debug_snapshot_and_metadata_are_available_without_serial_port(self):
        controller = SpectrometerControllerPI(
            config={
                "model": "PrincetonInstruments",
                "com_port": "COM8",
                "grating": [{"index": 1, "grooves": 600}],
            },
            debug=True,
        )

        self.assertFalse(controller.initialize())
        metadata = controller.get_cached_hardware_metadata()
        snapshot = controller.get_status_snapshot()

        self.assertEqual(metadata["serial_number"], "DEBUG-SP2750-0000000")
        self.assertEqual(metadata["grating"]["grooves_per_mm"], 600)
        self.assertEqual(snapshot["backend"], "princeton_acton_debug")
        self.assertTrue(snapshot["available"])

    def test_disconnected_status_reports_unavailable(self):
        controller = SpectrometerControllerPI(
            config={"model": "PrincetonInstruments"}, debug=False
        )

        snapshot = controller.get_status_snapshot()

        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["backend"], "princeton_acton")

    def test_calibration_seed_uses_cached_pi_hardware_parameters(self):
        controller = self._controller()
        controller._device_identity["model"] = "SP-2750"
        controller._gratings = [{"index": 3, "grooves": 150}]
        controller._current_grating = 3
        controller._current_wavelength_nm = 685.0

        with patch(
            "src.hardware.spectrometer_princeton.build_seed_axis",
            return_value=[680.0, 690.0],
        ) as builder:
            axis = controller.get_calibration_seed_axis(2, 16.0)

        self.assertEqual(axis, [680.0, 690.0])
        builder.assert_called_once_with(
            "SP-2750", 2, 16.0, 150, 685.0, lightfield_path=None
        )

    def test_spectrapro_2750_controller_name_maps_to_dll_family(self):
        params = starting_parameters("MODEL SP-2-750i", _CALIBRATION_XML)

        self.assertEqual(params["focus"], 750.0)
        self.assertEqual(params["gamma"], 13.1)

    def test_isoplane_name_maps_to_dll_family(self):
        params = starting_parameters("IsoPlane SCT-320", _CALIBRATION_XML)

        self.assertEqual(params["focus"], 320.0)

    def test_seed_axis_uses_pi_pixel_center_convention(self):
        runtime = (
            _FakeMonoCalibrate,
            _FakeSpectralCal,
            _ArrayFactory(),
            bool,
        )
        with patch(
            "src.hardware.princeton_calibration._load_runtime",
            return_value=runtime,
        ):
            axis = build_seed_axis("SP-2750", 4, 10.0, 150, 685.0)

        self.assertEqual(axis, [684.99, 685.0, 685.01, 685.02])


if __name__ == "__main__":
    unittest.main()
