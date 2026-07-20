import unittest
from unittest.mock import patch

from src import hardware_probe


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


if __name__ == "__main__":
    unittest.main()
