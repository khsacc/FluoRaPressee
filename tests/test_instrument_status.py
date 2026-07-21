import json
import unittest
from collections import namedtuple

from src.andor_camera_status import collect_andor_camera_status
from src.andor_spectrometer_status import collect_shamrock_status
from src.instrument_status import legacy_camera_snapshot, make_report


DeviceInfo = namedtuple("DeviceInfo", "controller_model head_model serial_number")


class FakeCamera:
    def get_device_info(self): return DeviceInfo("C-1", "DU-1", 42)
    def get_detector_size(self): return 1024, 127
    def get_pixel_size(self): return 26e-6, 26e-6
    def get_frame_timings(self): return 0.1, 0.12
    def get_status(self): return "idle"
    def get_roi(self): return 0, 1024, 45, 65, 1, 20
    def get_read_mode(self): return "image"
    def get_acquisition_mode(self): return "single"
    def get_trigger_mode(self): return "internal"
    def get_readout_time(self): return 0.02
    def get_amp_mode(self): return (0, 0, 1, 2)
    def get_channel_bitdepth(self): return 16
    def get_hsspeed_frequency(self): return 1e6
    def get_vsspeed_period(self): return 1e-6
    def get_preamp_gain(self): return 2.4
    def get_EMCCD_gain(self): raise RuntimeError("not fitted")
    def get_temperature_setpoint(self): return -65.0
    def get_temperature(self): return -64.9
    def get_temperature_status(self): return "stabilized"
    def is_cooler_on(self): return True
    def get_fan_mode(self): return "full"
    def get_temperature_range(self): return -100.0, 20.0
    def get_shutter_parameters(self): return "auto", 0, 0, 0
    def get_capabilities(self): return {"cam_type": "CCD"}


class InstrumentStatusTests(unittest.TestCase):
    def test_camera_snapshot_is_json_serializable_and_uses_um(self):
        snapshot = collect_andor_camera_status(FakeCamera())
        json.dumps(snapshot)
        sensor = {row["key"]: row for row in snapshot["sections"]["Sensor geometry"]}
        self.assertEqual(sensor["pixel_width"]["value"], 26.0)
        self.assertEqual(sensor["pixel_width"]["unit"], "um")

    def test_one_failed_camera_field_does_not_fail_snapshot(self):
        snapshot = collect_andor_camera_status(FakeCamera())
        readout = {row["key"]: row for row in snapshot["sections"]["Readout / gain"]}
        self.assertEqual(readout["emccd_gain"]["state"], "error")
        self.assertEqual(readout["channel_bit_depth"]["value"], 16)

    def test_debug_report_has_both_devices(self):
        camera = collect_andor_camera_status(FakeCamera())
        spectrograph = collect_shamrock_status(None, 0, False, debug=True)
        report = make_report(camera, spectrograph)
        json.dumps(report)
        self.assertEqual(report["schema_version"], 1)
        self.assertTrue(report["spectrograph"]["available"])

    def test_legacy_princeton_snapshot_is_normalized(self):
        snapshot = legacy_camera_snapshot({"Identification": [("Model", "PI")]} )
        self.assertEqual(snapshot["sections"]["Identification"][0]["value"], "PI")


if __name__ == "__main__":
    unittest.main()
