import json
import tempfile
import unittest
from pathlib import Path

from src.configuration_catalog import (
    ConfigurationCatalog,
    ConfigurationCompatibilityError,
    ConfigurationValidationError,
    format_configuration_label,
)


def draft(
    *,
    center=690.0,
    grating_index=1,
    grooves=600,
    roi_mode="1d_roi",
    roi_start=45,
    roi_end=65,
    spectrometer_serial="SPEC-1",
    camera_serial="CAM-1",
    c0=669.4,
):
    return {
        "compatibility": {
            "spectrometer_model": "SP-2750",
            "spectrometer_serial_number": spectrometer_serial,
            "camera_model": "DU-401",
            "camera_serial_number": camera_serial,
        },
        "spectrometer": {
            "grating_index": grating_index,
            "grating_grooves_per_mm": grooves,
            "target_center_wavelength_nm": center,
            "actual_center_wavelength_nm": center,
        },
        "detector": {
            "roi_mode": roi_mode,
            "roi_start": roi_start,
            "roi_end": roi_end,
            "detector_width": 1024,
            "detector_height": 127,
        },
        "display": {
            "mode": "Wavelength",
            "excitation_wavelength_nm": 532.0,
        },
        "calibration": {
            "source": "neon_polynomial",
            "unit": "Wavelength",
            "excitation_wavelength_nm": None,
            "coefficients": {"c0": c0, "c1": 0.0208, "c2": -1.2e-7},
        },
    }


def hardware_context(
    *, spectrometer_serial="SPEC-1", camera_serial="CAM-1", detector_height=127
):
    return {
        "spectrometer_serial_number": spectrometer_serial,
        "camera_serial_number": camera_serial,
        "gratings": [
            {"index": 1, "grooves": 600},
            {"index": 2, "grooves": 1200},
        ],
        "detector_width": 1024,
        "detector_height": detector_height,
    }


class ConfigurationCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.catalog = ConfigurationCatalog(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_new_calibration_replaces_active_version_in_same_slot(self):
        first = self.catalog.register_configuration(draft(c0=1.0))
        second = self.catalog.register_configuration(draft(c0=2.0))

        self.assertEqual(first["slot_id"], second["slot_id"])
        self.assertNotEqual(first["configuration_id"], second["configuration_id"])
        self.assertEqual(self.catalog.catalog_revision(), 2)

        active = self.catalog.list_selectable(hardware_context())
        self.assertEqual(active["total"], 1)
        self.assertEqual(
            active["items"][0]["configuration_id"], second["configuration_id"]
        )

        history = self.catalog.list_selectable(
            hardware_context(), active_only=False
        )
        self.assertEqual(history["total"], 2)
        self.assertTrue(history["items"][0]["active"])
        self.assertFalse(history["items"][1]["active"])
        self.assertEqual(
            self.catalog.get_configuration(first["configuration_id"])["calibration"]
            ["coefficients"]["c0"],
            1.0,
        )

    def test_slot_identity_uses_grating_center_and_roi(self):
        base = self.catalog.register_configuration(draft())
        changed_center = self.catalog.register_configuration(draft(center=691.0))
        changed_roi = self.catalog.register_configuration(draft(roi_start=40))
        changed_grating = self.catalog.register_configuration(
            draft(grating_index=2, grooves=1200)
        )

        self.assertEqual(
            len(
                {
                    base["slot_id"],
                    changed_center["slot_id"],
                    changed_roi["slot_id"],
                    changed_grating["slot_id"],
                }
            ),
            4,
        )

    def test_center_is_normalized_to_picometres_for_slot_identity(self):
        first = self.catalog.register_configuration(draft(center=690.0001))
        second = self.catalog.register_configuration(draft(center=690.0004))
        third = self.catalog.register_configuration(draft(center=690.0006))
        self.assertEqual(first["slot_id"], second["slot_id"])
        self.assertNotEqual(second["slot_id"], third["slot_id"])

    def test_list_returns_only_compatible_active_summaries(self):
        compatible = self.catalog.register_configuration(draft())
        self.catalog.register_configuration(
            draft(center=700.0, camera_serial="OTHER-CAMERA")
        )
        self.catalog.register_configuration(
            draft(center=710.0, roi_end=140)
        )

        result = self.catalog.list_selectable(hardware_context())

        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["configuration_id"], compatible["configuration_id"])
        self.assertNotIn("coefficients", item["calibration"])
        self.assertEqual(item["display_label"], "600 g/mm | 690.000 nm | ROI 45–65")

    def test_list_is_paginated_without_loading_record_payloads(self):
        for index in range(5):
            self.catalog.register_configuration(draft(center=680.0 + index))

        result = self.catalog.list_selectable(
            hardware_context(), limit=2, offset=1
        )

        self.assertEqual(result["total"], 5)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["limit"], 2)
        self.assertEqual(result["offset"], 1)

    def test_resolve_slots_freezes_exact_active_ids(self):
        first = self.catalog.register_configuration(draft(center=680.0))
        second = self.catalog.register_configuration(draft(center=690.0))

        result = self.catalog.resolve_slots(
            [first["slot_id"], second["slot_id"]], hardware_context()
        )

        self.assertEqual(
            result["resolved"],
            [
                {
                    "slot_id": first["slot_id"],
                    "configuration_id": first["configuration_id"],
                },
                {
                    "slot_id": second["slot_id"],
                    "configuration_id": second["configuration_id"],
                },
            ],
        )

    def test_assert_compatible_reports_serial_and_grating_mismatch(self):
        record = self.catalog.register_configuration(draft())
        incompatible_context = hardware_context(camera_serial="CAM-2")
        incompatible_context["gratings"] = [{"index": 1, "grooves": 1200}]

        with self.assertRaises(ConfigurationCompatibilityError) as raised:
            self.catalog.assert_compatible(record, incompatible_context)

        self.assertIn("Camera serial number does not match", raised.exception.reasons)
        self.assertIn(
            "Grating type does not match the configured slot",
            raised.exception.reasons,
        )

    def test_record_is_json_and_does_not_add_acquisition_or_sample_fields(self):
        record = self.catalog.register_configuration(draft())
        loaded = self.catalog.get_configuration(record["configuration_id"])
        record_files = list(Path(self.tempdir.name).glob("records/*/*/*.json"))

        self.assertEqual(len(record_files), 1)
        with record_files[0].open(encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk, loaded)
        self.assertNotIn("exposure_time_s", loaded)
        self.assertNotIn("accumulations", loaded)
        self.assertNotIn("material", loaded)

    def test_invalid_roi_is_rejected_before_any_record_is_written(self):
        with self.assertRaises(ConfigurationValidationError):
            self.catalog.register_configuration(draft(roi_start=70, roi_end=65))
        self.assertEqual(
            list(Path(self.tempdir.name).glob("records/*/*/*.json")), []
        )

    def test_record_label_uses_configuration_structure(self):
        record = self.catalog.register_configuration(
            draft(roi_mode="1d_full", roi_start=0, roi_end=127)
        )
        self.assertEqual(
            format_configuration_label(record),
            "600 g/mm | 690.000 nm | Full ROI",
        )


if __name__ == "__main__":
    unittest.main()
