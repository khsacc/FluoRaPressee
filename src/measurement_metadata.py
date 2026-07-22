"""Build measurement metadata without making live hardware calls."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from src.instrument_status import json_value


METADATA_SCHEMA_VERSION = 1


def capture_hardware_state(window, accumulations=None):
    """Freeze hardware state at the end of an acquisition cycle."""
    camera = _camera_state(window)
    camera["accumulations"] = int(
        accumulations if accumulations is not None else window.spin_accumulate.value()
    )
    camera["accumulation_mode"] = "software_sum"
    return {
        "captured_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "camera": camera,
        "spectrometer": _spectrometer_state(window),
    }


def build_hardware_metadata(window, captured=None, include_background=True):
    captured = deepcopy(captured or capture_hardware_state(window))
    result = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "captured_at": captured.get("captured_at"),
        "camera": captured.get("camera", {}),
        "spectrometer": captured.get("spectrometer", {}),
        "axis": _axis_state(window),
    }
    if include_background:
        result["background"] = _background_state(window, result)
    return json_value(result)


def background_mismatch_fields(window, hardware_metadata=None):
    bg_meta = getattr(window, "loaded_bg_metadata", None)
    if bg_meta is None:
        return []

    current = hardware_metadata or build_hardware_metadata(
        window, capture_hardware_state(window), include_background=False
    )
    camera = current.get("camera", {})
    roi = camera.get("roi", {})
    fields = []

    _compare_float(fields, "camera.exposure_s", camera.get("exposure_s"), bg_meta.get("acquisition_time"), 1e-4)
    _compare(fields, "camera.accumulations", camera.get("accumulations"), bg_meta.get("accumulations"))
    _compare(fields, "camera.roi.mode", _background_mode(roi.get("mode")), bg_meta.get("mode"))
    if roi.get("mode") == "1d_roi":
        _compare(fields, "camera.roi.vertical_start", roi.get("vertical_start"), bg_meta.get("roi_start"))
        _compare(fields, "camera.roi.vertical_end", roi.get("vertical_end"), bg_meta.get("roi_end"))

    bg_hardware = bg_meta.get("hardware_metadata")
    if bg_hardware:
        bg_camera = bg_hardware.get("camera", {})
        bg_spec = bg_hardware.get("spectrometer", {})
        spec = current.get("spectrometer", {})
        _compare(fields, "camera.identity.serial_number", _path(camera, "identity", "serial_number"), _path(bg_camera, "identity", "serial_number"), skip_missing=True)
        _compare(fields, "camera.detector_size_px", camera.get("detector_size_px"), bg_camera.get("detector_size_px"), skip_missing=True)
        _compare(fields, "camera.pixel_pitch_um", camera.get("pixel_pitch_um"), bg_camera.get("pixel_pitch_um"), skip_missing=True)
        _compare(fields, "camera.binning", camera.get("binning"), bg_camera.get("binning"), skip_missing=True)
        _compare(fields, "camera.accumulation_mode", camera.get("accumulation_mode"), bg_camera.get("accumulation_mode"), skip_missing=True)
        _compare(fields, "camera.read_mode", camera.get("read_mode"), bg_camera.get("read_mode"), skip_missing=True)
        _compare(fields, "camera.output_rows", camera.get("output_rows"), bg_camera.get("output_rows"), skip_missing=True)
        _compare(fields, "camera.software_vertical_sum", camera.get("software_vertical_sum"), bg_camera.get("software_vertical_sum"), skip_missing=True)
        _compare_float(fields, "camera.temperature.setpoint_c", _path(camera, "temperature", "setpoint_c"), _path(bg_camera, "temperature", "setpoint_c"), 0.1, skip_missing=True)
        _compare(fields, "spectrometer.serial_number", spec.get("serial_number"), bg_spec.get("serial_number"), skip_missing=True)
        _compare(fields, "spectrometer.grating.index", _path(spec, "grating", "index"), _path(bg_spec, "grating", "index"), skip_missing=True)
        _compare_float(fields, "spectrometer.center_wavelength_nm", spec.get("center_wavelength_nm"), bg_spec.get("center_wavelength_nm"), 1e-4, skip_missing=True)
    return fields


def _camera_state(window):
    getter = getattr(window.thread, "get_cached_hardware_metadata", None)
    state = deepcopy(getter() if getter is not None else {})
    identity = state.setdefault("identity", {})
    fallback_identity = getattr(window, "_camera_identity", {})
    _fill_missing(identity, "model", fallback_identity.get("model"))
    _fill_missing(identity, "serial_number", fallback_identity.get("serial_number"))
    state.setdefault("detector_size_px", {
        "width": getattr(window.thread, "det_width", None),
        "height": getattr(window.thread, "det_height", None),
    })
    state.setdefault("exposure_s", float(getattr(window.thread, "current_exposure", window.spin_acq_time.value())))
    state.setdefault("roi", _roi_state(window))
    state.setdefault(
        "binning",
        _binning_state(state["roi"], getattr(window.thread, "det_height", None)),
    )
    temperature = state.setdefault("temperature", {})
    _fill_missing(temperature, "current_c", getattr(window, "_last_temperature_c", None))
    _fill_missing(temperature, "setpoint_c", getattr(window, "_temp_accepted_setpoint", None))
    _fill_missing(temperature, "status", getattr(window, "_last_temperature_status", None))
    return state


def _spectrometer_state(window):
    getter = getattr(window.spec_ctrl, "get_cached_hardware_metadata", None)
    state = deepcopy(getter() if getter is not None else {})
    identity = window.config.get("hardware_identity", {}).get("spectrometer", {})
    _fill_missing(state, "serial_number", identity.get("serial_number"))
    current_index = _current_grating_index(window)
    config_grating = _config_grating(window, current_index)
    grating = state.setdefault("grating", {})
    _fill_missing(grating, "index", current_index)
    _fill_missing(grating, "grooves_per_mm", config_grating.get("grooves"))
    _fill_missing(grating, "blaze", config_grating.get("blaze"))
    state["center_wavelength_nm"] = float(getattr(window, "physical_center_wl", 0.0))
    state.setdefault("wavelength_limits_nm", None)
    return state


def _axis_state(window):
    coeffs = getattr(window, "calib_coeffs", None)
    source = getattr(window, "axis_source", None)
    if coeffs is None:
        source = "hardware_shamrock" if source == "hardware_shamrock" else "pixel"
        coefficients = None
    else:
        source = source if source in (
            "neon_polynomial", "loaded_configuration", "api_inline_calibration"
        ) else "loaded_configuration"
        coefficients = {"c0": coeffs[0], "c1": coeffs[1], "c2": coeffs[2]}
    return {
        "source": source,
        "configuration_id": (
            getattr(window, "active_configuration_id", None) if coefficients else None
        ),
        "configuration_slot_id": (
            getattr(window, "active_configuration_slot_id", None) if coefficients else None
        ),
        "configuration_label": (
            getattr(window, "configuration_label", None) if coefficients else None
        ),
        "calibration_coefficients": coefficients,
        "calibration_unit": getattr(window, "calib_unit", None) if coefficients else None,
    }


def _background_state(window, hardware_metadata):
    bg_meta = getattr(window, "loaded_bg_metadata", None)
    loaded = bg_meta is not None and getattr(window, "loaded_bg_data", None) is not None
    used = bool(loaded and window.radio_bg_on.isChecked())
    mismatches = background_mismatch_fields(window, hardware_metadata) if loaded else []
    return {
        "loaded": loaded,
        "used": used,
        "match": (not mismatches) if loaded else None,
        "mismatched_fields": mismatches,
        "comparison_level": "hardware_metadata" if loaded and bg_meta.get("hardware_metadata") else "legacy_settings" if loaded else None,
        "source_file": bg_meta.get("source_file") if loaded else None,
    }


def _roi_state(window):
    if window.radio_2d.isChecked():
        mode = "2d"
        start, end = 0, getattr(window.thread, "det_height", None)
    elif window.radio_1d_full.isChecked():
        mode = "1d_full"
        start, end = 0, getattr(window.thread, "det_height", None)
    else:
        mode = "1d_roi"
        start, end = window.spin_vstart.value(), window.spin_vend.value()
    return {
        "mode": mode,
        "horizontal_start": 0,
        "horizontal_end": getattr(window.thread, "det_width", None),
        "vertical_start": start,
        "vertical_end": end,
    }


def _binning_state(roi, detector_height):
    mode = roi.get("mode")
    if mode == "2d":
        vertical = 1
    elif mode == "1d_full":
        vertical = detector_height
    else:
        start, end = roi.get("vertical_start"), roi.get("vertical_end")
        vertical = end - start if start is not None and end is not None else None
    return {"horizontal": 1, "vertical": vertical}


def _current_grating_index(window):
    combo_index = window.combo_grating.currentIndex()
    gratings = window.config.get("grating", [])
    if 0 <= combo_index < len(gratings):
        return gratings[combo_index].get("index", combo_index + 1)
    return combo_index + 1


def _config_grating(window, index):
    for grating in window.config.get("grating", []):
        if grating.get("index") == index:
            return grating
    return {}


def _background_mode(roi_mode):
    return "1D Spectrum (Custom ROI)" if roi_mode == "1d_roi" else "1D Spectrum (Full Range Binning)"


def _path(mapping, *keys):
    value = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _compare(fields, name, current, saved, skip_missing=False):
    if skip_missing and (current is None or saved is None):
        return
    if current != saved:
        fields.append(name)


def _compare_float(fields, name, current, saved, tolerance, skip_missing=False):
    if current is None or saved is None:
        if not skip_missing and current != saved:
            fields.append(name)
        return
    try:
        mismatch = abs(float(current) - float(saved)) > tolerance
    except (TypeError, ValueError):
        mismatch = current != saved
    if mismatch:
        fields.append(name)


def _fill_missing(mapping, key, fallback):
    if mapping.get(key) is None and fallback is not None:
        mapping[key] = fallback
