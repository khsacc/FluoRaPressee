import unittest

import numpy as np

try:
    from src.api.schemas import AcquireRequest
except (ImportError, ModuleNotFoundError):
    AcquireRequest = None

try:
    from src.api.schemas import (
        ApplyConfigurationRequest,
        ResolveConfigurationsRequest,
    )
    from src.api.server import create_app
except (ImportError, ModuleNotFoundError):
    ApplyConfigurationRequest = None
    ResolveConfigurationsRequest = None
    create_app = None


class DirectBridge:
    def call(self, fn):
        return fn()


class FakeGui:
    _api_key = "test-key"

    def __init__(self):
        self.last_acquire = None

    def api_get_status(self):
        return {
            "busy": False,
            "camera_connected": True,
            "exposure_time_s": 0.1,
            "calibration": {"applied": True, "unit": "Wavelength", "label": "test"},
            "roi": {"mode": "1d_roi", "start": 45, "end": 65},
            "background": {"loaded": False, "metadata": None},
            "configuration": {
                "configuration_id": "cfg-1",
                "slot_id": "slot-1",
                "axis_mode": "calibrated",
                "calibration_applied": True,
                "unit": "Wavelength",
            },
            "hardware_state": {
                "grating_index": 1,
                "grooves_per_mm": 600,
                "actual_center_wavelength_nm": 690.0,
                "roi_mode": "1d_roi",
                "roi_start": 45,
                "roi_end": 65,
            },
        }

    def api_list_configurations(self, **kwargs):
        return {
            "catalog_revision": 7,
            "items": [{"configuration_id": "cfg-1", "slot_id": "slot-1"}],
            "total": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }

    def api_get_configuration(self, configuration_id):
        return {
            "catalog_revision": 7,
            "configuration": {"configuration_id": configuration_id},
            "compatible": True,
            "incompatibility_reasons": [],
        }

    def api_resolve_configurations(self, slot_ids):
        return {
            "catalog_revision": 7,
            "resolved": [
                {"slot_id": slot_id, "configuration_id": f"cfg-{index}"}
                for index, slot_id in enumerate(slot_ids, start=1)
            ],
        }

    def api_apply_configuration(self, configuration_id, axis_mode="calibrated"):
        return {
            "applied": True,
            "configuration_id": configuration_id,
            "slot_id": "slot-1",
            "display_label": "600 g/mm | 690.000 nm | ROI 45–65",
            "configuration": {
                "configuration_id": configuration_id,
                "slot_id": "slot-1",
                "axis_mode": axis_mode,
                "calibration_applied": axis_mode == "calibrated",
                "unit": "Wavelength" if axis_mode == "calibrated" else "pixel",
            },
            "hardware_state": {
                "grating_index": 1,
                "grooves_per_mm": 600,
                "actual_center_wavelength_nm": 690.0,
                "roi_mode": "1d_roi",
                "roi_start": 45,
                "roi_end": 65,
            },
        }

    def api_acquire(self, **kwargs):
        self.last_acquire = kwargs
        configuration_id = kwargs["configuration_id"]
        axis_mode = kwargs["axis_mode"] if configuration_id else "calibrated"
        return {
            "x": np.asarray([690.0, 690.1]),
            "y_raw": np.asarray([10.0, 20.0]),
            "y": np.asarray([10.0, 20.0]),
            "mode": "1d",
            "exposure_time_s": 0.1,
            "accumulations": 1,
            "detector_temperature_c": -65.0,
            "timestamp": "2026-07-22T00:00:00+09:00",
            "configuration": {
                "configuration_id": configuration_id,
                "slot_id": "slot-1" if configuration_id else None,
                "axis_mode": axis_mode,
                "calibration_applied": axis_mode == "calibrated",
                "unit": "Wavelength" if axis_mode == "calibrated" else "pixel",
            },
            "hardware_state": {
                "grating_index": 1,
                "grooves_per_mm": 600,
                "actual_center_wavelength_nm": 690.0,
                "roi_mode": "1d_roi",
                "roi_start": 45,
                "roi_end": 65,
            },
        }


@unittest.skipIf(create_app is None, "FastAPI test dependencies are unavailable")
class ConfigurationApiTests(unittest.TestCase):
    def setUp(self):
        self.gui = FakeGui()
        self.app = create_app(self.gui, DirectBridge())

    def endpoint(self, path, method):
        pending = list(self.app.routes)
        while pending:
            route = pending.pop(0)
            pending.extend(getattr(route, "routes", []))
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                pending.extend(original_router.routes)
            if (
                getattr(route, "path", None) == path
                and method in getattr(route, "methods", set())
            ):
                return route.endpoint
        self.fail(f"Missing route: {method} {path}")

    def test_acquire_configuration_is_optional(self):
        response = self.endpoint("/acquire", "POST")(AcquireRequest())

        self.assertIsNone(self.gui.last_acquire["configuration_id"])
        self.assertEqual(self.gui.last_acquire["axis_mode"], "calibrated")
        self.assertIsNone(response["configuration"]["configuration_id"])

    def test_explicit_configuration_and_pixel_mode_are_forwarded(self):
        response = self.endpoint("/acquire", "POST")(
            AcquireRequest(configuration_id="cfg-1", axis_mode="pixel")
        )

        self.assertEqual(self.gui.last_acquire["configuration_id"], "cfg-1")
        self.assertEqual(self.gui.last_acquire["axis_mode"], "pixel")
        self.assertEqual(response["configuration"]["unit"], "pixel")

    def test_catalog_discovery_resolve_get_and_apply(self):
        listing = self.endpoint("/configurations", "GET")()
        resolved = self.endpoint("/configurations/resolve", "POST")(
            ResolveConfigurationsRequest(slot_ids=["slot-1", "slot-2"])
        )
        record = self.endpoint("/configurations/{configuration_id}", "GET")(
            "cfg-1"
        )
        applied = self.endpoint(
            "/configurations/{configuration_id}/apply", "POST"
        )(
            "cfg-1", ApplyConfigurationRequest(axis_mode="calibrated")
        )

        self.assertEqual(listing["catalog_revision"], 7)
        self.assertEqual(len(resolved["resolved"]), 2)
        self.assertEqual(record["configuration"]["configuration_id"], "cfg-1")
        self.assertTrue(applied["configuration"]["calibration_applied"])

    def test_openapi_contains_configuration_routes(self):
        paths = self.app.openapi()["paths"]
        self.assertIn("/configurations", paths)
        self.assertIn("/configurations/resolve", paths)
        self.assertIn("/configurations/{configuration_id}/apply", paths)
        acquire_schema = paths["/acquire"]["post"]["requestBody"]["content"]
        acquire_schema = acquire_schema["application/json"]["schema"]
        if "$ref" in acquire_schema:
            schema_name = acquire_schema["$ref"].rsplit("/", 1)[-1]
            acquire_schema = self.app.openapi()["components"]["schemas"][schema_name]
        self.assertIn("configuration_id", acquire_schema["properties"])


class ConfigurationApiSchemaTests(unittest.TestCase):
    @unittest.skipIf(AcquireRequest is None, "Pydantic is unavailable")
    def test_axis_mode_is_only_valid_with_configuration(self):
        self.assertIsNone(AcquireRequest().configuration_id)
        self.assertIsNone(AcquireRequest().axis_mode)
        self.assertIsNone(AcquireRequest().accumulations)
        with self.assertRaises(ValueError):
            AcquireRequest(axis_mode="pixel")


if __name__ == "__main__":
    unittest.main()
