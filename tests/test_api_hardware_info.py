import unittest

from src.api.info_helpers import (
    build_config_response,
    build_device_response,
    normalize_camera_metadata,
    normalize_spectrometer_metadata,
)

try:
    from src.api.schemas import CameraInfoResponse, ConfigResponse, SpectrometerInfoResponse
except ImportError:
    CameraInfoResponse = ConfigResponse = SpectrometerInfoResponse = None


class ApiHardwareInfoHelperTests(unittest.TestCase):
    def test_camera_metadata_uses_public_exposure_name(self):
        metadata = normalize_camera_metadata({
            "identity": {"model": "DU-401", "serial_number": "CAM-1"},
            "detector_size_px": {"width": 1024, "height": 127},
            "pixel_pitch_um": {"width": 26.0, "height": 26.0},
            "exposure_s": 0.1,
            "accumulations": 3,
            "accumulation_mode": "software_sum",
            "roi": {"mode": "1d_roi", "vertical_start": 45, "vertical_end": 65},
            "binning": {"horizontal": 1, "vertical": 20},
            "temperature": {"current_c": -64.9, "setpoint_c": -65.0, "status": "locked"},
        })

        self.assertEqual(metadata["exposure_time_s"], 0.1)
        self.assertNotIn("exposure_s", metadata)

    def test_spectrometer_identity_is_normalized(self):
        metadata = normalize_spectrometer_metadata(
            {
                "serial_number": "LIVE-1",
                "grating": {"index": 2, "grooves_per_mm": 1200, "blaze": None},
                "center_wavelength_nm": 694.2,
                "wavelength_limits_nm": None,
            },
            {"model": "SP-2750", "serial_number": "CONFIG-OLD"},
        )

        self.assertEqual(
            metadata["identity"],
            {"model": "SP-2750", "serial_number": "LIVE-1"},
        )
        self.assertNotIn("serial_number", {
            key: value for key, value in metadata.items() if key != "identity"
        })

    def test_config_distinguishes_active_and_stored_hardware_keys(self):
        startup = {
            "model": "Andor",
            "dll_path": "C:/old",
            "grating": [{"index": 1, "grooves": 600}],
            "flip_x": False,
        }
        current = {
            "model": "PrincetonInstruments",
            "com_port": "COM7",
            "grating": [{"index": 1, "grooves": 1200}],
            "flip_x": True,
            "nested": {"access_token": "do-not-return", "visible": 1},
        }

        response = build_config_response(
            current, startup, stored_config=current, captured_at="2026-07-22T00:00:00+09:00"
        )

        self.assertEqual(response["active_config"]["model"], "Andor")
        self.assertNotIn("com_port", response["active_config"])
        self.assertEqual(response["active_config"]["grating"][0]["grooves"], 1200)
        self.assertEqual(response["stored_config"]["model"], "PrincetonInstruments")
        self.assertTrue(response["restart_required"])
        self.assertEqual(response["pending_restart_keys"], ["model", "com_port", "dll_path"])
        self.assertNotIn("access_token", response["active_config"]["nested"])
        self.assertIn("nested.access_token", response["redacted_fields"])

    @unittest.skipIf(CameraInfoResponse is None, "pydantic/fastapi dependencies are unavailable")
    def test_response_models_accept_normalized_payloads(self):
        camera_metadata = normalize_camera_metadata({
            "identity": {"model": "DU-401", "serial_number": "CAM-1"},
            "detector_size_px": {"width": 1024, "height": 127},
            "pixel_pitch_um": {"width": 26.0, "height": 26.0},
            "exposure_s": 0.1,
            "accumulations": 1,
            "accumulation_mode": "software_sum",
            "roi": {"mode": "1d_full"},
            "binning": {"horizontal": 1, "vertical": 127},
            "temperature": {"current_c": -65.0, "setpoint_c": -65.0, "status": "locked"},
        })
        camera_payload = build_device_response(
            backend="andor_sdk2", debug=False, operational=True,
            hardware_connected=True, busy=False, metadata=camera_metadata,
            captured_at="2026-07-22T00:00:00+09:00",
        )
        CameraInfoResponse.model_validate(camera_payload)

        spectrometer_metadata = normalize_spectrometer_metadata(
            {
                "serial_number": "SPEC-1",
                "grating": {"index": 1, "grooves_per_mm": 600, "blaze": None},
                "center_wavelength_nm": 694.0,
                "wavelength_limits_nm": None,
            },
            {"model": "SP-2750"},
        )
        spectrometer_payload = build_device_response(
            backend="princeton_acton", debug=False, operational=True,
            hardware_connected=True, busy=False, metadata=spectrometer_metadata,
            captured_at="2026-07-22T00:00:00+09:00",
        )
        SpectrometerInfoResponse.model_validate(spectrometer_payload)

        config_payload = build_config_response({}, {}, captured_at="2026-07-22T00:00:00+09:00")
        ConfigResponse.model_validate(config_payload)


if __name__ == "__main__":
    unittest.main()
