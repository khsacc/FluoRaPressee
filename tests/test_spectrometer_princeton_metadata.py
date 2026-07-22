import json
import sys
import types
import unittest

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

from src.spectrometer_princeton import SpectrometerControllerPI


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


if __name__ == "__main__":
    unittest.main()
