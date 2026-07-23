import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.core.configuration_catalog import (
    ConfigurationCatalog,
    ConfigurationCompatibilityError,
    ConfigurationError,
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
    spectrometer_model="SP-2750",
    camera_model="DU-401",
    c0=669.4,
):
    return {
        "compatibility": {
            "spectrometer_model": spectrometer_model,
            "spectrometer_serial_number": spectrometer_serial,
            "camera_model": camera_model,
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
    *,
    spectrometer_serial="SPEC-1",
    camera_serial="CAM-1",
    spectrometer_model="SP-2750",
    camera_model="DU-401",
    detector_height=127,
):
    return {
        "spectrometer_model": spectrometer_model,
        "spectrometer_serial_number": spectrometer_serial,
        "camera_model": camera_model,
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

    def test_saved_serial_is_required_even_when_current_query_returns_none(self):
        record = self.catalog.register_configuration(draft())
        context = hardware_context(camera_serial=None)

        with self.assertRaises(ConfigurationCompatibilityError) as raised:
            self.catalog.assert_compatible(record, context)

        self.assertIn("Camera serial number does not match", raised.exception.reasons)
        self.assertEqual(self.catalog.list_selectable(context)["total"], 0)

    def test_model_is_fallback_when_backend_has_no_serial(self):
        record = self.catalog.register_configuration(
            draft(spectrometer_serial=None, camera_serial=None)
        )
        same_models = hardware_context(
            spectrometer_serial=None, camera_serial=None
        )
        wrong_camera = hardware_context(
            spectrometer_serial=None,
            camera_serial=None,
            camera_model="DIFFERENT-CAMERA",
        )

        self.catalog.assert_compatible(record, same_models)
        self.assertEqual(self.catalog.list_selectable(same_models)["total"], 1)
        self.assertEqual(self.catalog.list_selectable(wrong_camera)["total"], 0)

    def test_models_are_verified_and_part_of_slot_identity(self):
        first = self.catalog.register_configuration(draft())
        second = self.catalog.register_configuration(
            draft(spectrometer_model="DIFFERENT-SPECTROMETER")
        )

        self.assertNotEqual(first["slot_id"], second["slot_id"])
        with self.assertRaises(ConfigurationCompatibilityError) as raised:
            self.catalog.assert_compatible(
                first, hardware_context(spectrometer_model="DIFFERENT-SPECTROMETER")
            )
        self.assertIn("Spectrometer model does not match", raised.exception.reasons)

    def test_registration_rejects_identityless_device(self):
        with self.assertRaises(ConfigurationValidationError):
            self.catalog.register_configuration(
                draft(camera_serial=None, camera_model=None)
            )

    def test_catalog_v1_is_migrated_with_model_identity(self):
        record = self.catalog.register_configuration(
            draft(spectrometer_serial=None, camera_serial=None)
        )
        database_path = Path(self.tempdir.name) / "catalog.sqlite3"
        with sqlite3.connect(database_path) as conn:
            conn.execute(
                "UPDATE catalog_meta SET value = '1' WHERE key = 'schema_version'"
            )
            conn.execute(
                "UPDATE slots SET signature = ? WHERE slot_id = ?",
                ("legacy-v1-signature", record["slot_id"]),
            )
            conn.execute("DROP INDEX idx_slots_hardware_identity")
            conn.execute("ALTER TABLE slots DROP COLUMN spectrometer_model")
            conn.execute("ALTER TABLE slots DROP COLUMN camera_model")

        migrated = ConfigurationCatalog(self.tempdir.name)
        result = migrated.list_selectable(
            hardware_context(spectrometer_serial=None, camera_serial=None)
        )
        with sqlite3.connect(database_path) as conn:
            schema_version = conn.execute(
                "SELECT value FROM catalog_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(slots)").fetchall()
            }

        self.assertEqual(schema_version, "2")
        self.assertIn("spectrometer_model", columns)
        self.assertIn("camera_model", columns)
        self.assertEqual(result["total"], 1)

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

    def test_list_all_shows_slots_regardless_of_hardware_compatibility(self):
        self.catalog.register_configuration(draft())
        self.catalog.register_configuration(
            draft(center=700.0, camera_serial="OTHER-CAMERA")
        )

        incompatible_context = hardware_context(camera_serial="OTHER-CAMERA")
        self.assertEqual(
            self.catalog.list_selectable(incompatible_context)["total"], 1
        )
        self.assertEqual(self.catalog.list_all()["total"], 2)

    def test_list_all_active_only_default_hides_archived_versions(self):
        self.catalog.register_configuration(draft(c0=1.0))
        self.catalog.register_configuration(draft(c0=2.0))

        self.assertEqual(self.catalog.list_all()["total"], 1)
        self.assertEqual(self.catalog.list_all(active_only=False)["total"], 2)

    def test_list_all_includes_use_count_and_last_used_at(self):
        record = self.catalog.register_configuration(draft())
        self.catalog.mark_used(record["configuration_id"])
        self.catalog.mark_used(record["configuration_id"])

        item = self.catalog.list_all()["items"][0]
        self.assertEqual(item["use_count"], 2)
        self.assertIsNotNone(item["last_used_at"])
        self.assertEqual(item["status"], "active")

    def test_delete_configuration_version_removes_archived_row_and_file(self):
        first = self.catalog.register_configuration(draft(c0=1.0))
        self.catalog.register_configuration(draft(c0=2.0))

        result = self.catalog.delete_configuration_version(
            first["configuration_id"]
        )

        self.assertEqual(result["deleted_files"], [
            f"records/{first['created_at'][0:4]}/{first['created_at'][5:7]}/"
            f"{first['configuration_id']}.json"
        ])
        self.assertEqual(result["file_errors"], [])
        with self.assertRaises(ConfigurationError):
            self.catalog.get_configuration(first["configuration_id"])
        self.assertEqual(self.catalog.list_all(active_only=False)["total"], 1)
        remaining_files = list(Path(self.tempdir.name).glob("records/*/*/*.json"))
        self.assertEqual(len(remaining_files), 1)

    def test_delete_configuration_version_refuses_to_delete_the_active_version(self):
        record = self.catalog.register_configuration(draft())

        with self.assertRaises(ConfigurationError):
            self.catalog.delete_configuration_version(record["configuration_id"])

        # Nothing was mutated: the record is still readable.
        self.catalog.get_configuration(record["configuration_id"])
        remaining_files = list(Path(self.tempdir.name).glob("records/*/*/*.json"))
        self.assertEqual(len(remaining_files), 1)

    def test_delete_configuration_version_unknown_id_raises(self):
        with self.assertRaises(ConfigurationError):
            self.catalog.delete_configuration_version("cfg_does_not_exist")

    def test_delete_slot_removes_all_versions_and_files(self):
        first = self.catalog.register_configuration(draft(c0=1.0))
        self.catalog.register_configuration(draft(c0=2.0))
        other_slot = self.catalog.register_configuration(draft(center=700.0))

        result = self.catalog.delete_slot(first["slot_id"])

        self.assertEqual(len(result["deleted_configuration_ids"]), 2)
        self.assertEqual(len(result["deleted_files"]), 2)
        self.assertEqual(result["file_errors"], [])
        self.assertEqual(self.catalog.list_all(active_only=False)["total"], 1)
        self.assertEqual(
            self.catalog.list_all(active_only=False)["items"][0]["slot_id"],
            other_slot["slot_id"],
        )
        remaining_files = list(Path(self.tempdir.name).glob("records/*/*/*.json"))
        self.assertEqual(len(remaining_files), 1)

    def test_delete_slot_unknown_id_raises(self):
        with self.assertRaises(ConfigurationError):
            self.catalog.delete_slot("slot_does_not_exist")

    def test_delete_slot_treats_already_missing_file_as_deleted(self):
        record = self.catalog.register_configuration(draft())
        record_path = Path(self.tempdir.name) / (
            f"records/{record['created_at'][0:4]}/{record['created_at'][5:7]}/"
            f"{record['configuration_id']}.json"
        )
        record_path.unlink()

        result = self.catalog.delete_slot(record["slot_id"])

        self.assertEqual(result["file_errors"], [])
        self.assertEqual(len(result["deleted_files"]), 1)
        self.assertEqual(self.catalog.list_all(active_only=False)["total"], 0)

    def test_delete_slot_reports_unremovable_file_without_raising_and_still_deletes_the_row(
        self,
    ):
        record = self.catalog.register_configuration(draft())
        record_path = Path(self.tempdir.name) / (
            f"records/{record['created_at'][0:4]}/{record['created_at'][5:7]}/"
            f"{record['configuration_id']}.json"
        )
        record_path.unlink()
        record_path.mkdir()  # unlink() on a directory raises, forcing a file_error

        result = self.catalog.delete_slot(record["slot_id"])

        self.assertEqual(len(result["file_errors"]), 1)
        self.assertEqual(result["deleted_files"], [])
        # The DB row is gone even though the file removal failed.
        self.assertEqual(self.catalog.list_all(active_only=False)["total"], 0)


if __name__ == "__main__":
    unittest.main()
