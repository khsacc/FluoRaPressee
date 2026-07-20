"""Read connected hardware to pre-fill the first-run configuration wizard."""
from __future__ import annotations

from datetime import datetime
import os


SUPPLIER_ANDOR = "Andor"
SUPPLIER_PI = "PrincetonInstruments"


def probe_initial_hardware(supplier: str, config: dict) -> dict:
    """Return a best-effort config patch and a diagnostic summary.

    Camera and spectrograph probing are deliberately independent. A missing
    camera must not discard a successfully detected grating table, and vice
    versa.
    """
    result = {
        "supplier": supplier,
        "config": {},
        "detected_hardware": {
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "camera": {},
            "spectrometer": {},
        },
        "camera_candidates": [],
        "successes": [],
        "errors": [],
    }
    if supplier == SUPPLIER_ANDOR:
        _run_probe(result, "Andor camera", _probe_andor_camera, config)
        _run_probe(result, "Andor spectrograph", _probe_andor_spectrometer, config)
    elif supplier == SUPPLIER_PI:
        _run_probe(result, "PICam camera", _probe_pi_camera, config)
        _run_probe(result, "Acton spectrograph", _probe_pi_spectrometer, config)
    else:
        result["errors"].append(f"Unsupported supplier: {supplier}")
    return result


def _run_probe(result, label, probe, config):
    try:
        probe(result, config)
        result["successes"].append(label)
    except Exception as exc:
        result["errors"].append(f"{label}: {exc}")


def _merge_identity(result, category, identity):
    hardware_identity = result["config"].setdefault("hardware_identity", {})
    hardware_identity[category] = {
        "model": identity.get("model") or None,
        "serial_number": (
            str(identity["serial_number"]) if identity.get("serial_number") is not None else None
        ),
    }


def _probe_andor_camera(result, config):
    from pylablib.devices import Andor

    camera = None
    try:
        camera = Andor.AndorSDK2Camera()
        info = camera.get_device_info()
        width, height = camera.get_detector_size()
        pixel_width_m, pixel_height_m = camera.get_pixel_size()
        raw_serial = _field(info, "serial_number", 2)
        identity = {
            "model": _field(info, "head_model", 1),
            "serial_number": str(raw_serial) if raw_serial is not None else None,
        }
        _merge_identity(result, "camera", identity)
        camera_state = {
            "controller_model": _field(info, "controller_model", 0),
            "model": identity["model"],
            "serial_number": identity["serial_number"],
            "detector_size_px": {"width": int(width), "height": int(height)},
            "pixel_pitch_um": {
                "width": float(pixel_width_m) * 1e6,
                "height": float(pixel_height_m) * 1e6,
            },
        }
        temperature_range = _optional(camera, "get_temperature_range")
        if temperature_range is not None:
            camera_state["temperature_range_c"] = {
                "min": float(temperature_range[0]),
                "max": float(temperature_range[1]),
            }
        setpoint = _optional(camera, "get_temperature_setpoint")
        if setpoint is not None:
            result["config"]["default_temperature"] = int(round(float(setpoint)))
            camera_state["temperature_setpoint_c"] = float(setpoint)
        fan_mode = _optional(camera, "get_fan_mode")
        if fan_mode in ("full", "low", "off"):
            result["config"]["default_fan_mode"] = fan_mode
            camera_state["fan_mode"] = fan_mode
        result["detected_hardware"]["camera"] = camera_state
    finally:
        if camera is not None:
            try:
                camera.close()
            except Exception:
                pass


def _probe_andor_spectrometer(result, config):
    from src.spectrometer_andor import SpectrometerControllerAndor

    controller = SpectrometerControllerAndor(config=config, debug=False)
    try:
        if not controller.initialize():
            raise RuntimeError("Shamrock initialization failed or no device was found")
        identity = controller.get_device_identity()
        gratings = controller.get_gratings()
        if not gratings:
            raise RuntimeError("No installed gratings could be read")
        _merge_identity(result, "spectrometer", identity)
        result["config"]["grating"] = _config_gratings(gratings, result)
        result["detected_hardware"]["spectrometer"] = {
            **identity,
            "current_grating": int(controller.get_grating()),
            "center_wavelength_nm": float(controller.get_wavelength()),
            "gratings": gratings,
        }
    finally:
        try:
            controller.close()
        except Exception:
            pass


def _probe_pi_camera(result, config):
    import pylablib
    from pylablib.devices import PrincetonInstruments

    runtime_path = config.get("PIcam_dll_path", "")
    dll_cookie = None
    if runtime_path:
        if hasattr(os, "add_dll_directory"):
            try:
                dll_cookie = os.add_dll_directory(runtime_path)
            except OSError:
                pass
        os.environ["PATH"] = runtime_path + os.pathsep + os.environ.get("PATH", "")
        pylablib.par["devices/dlls/picam"] = runtime_path

    cameras = PrincetonInstruments.list_cameras()
    if not cameras:
        raise RuntimeError("No PICam camera was detected")
    result["camera_candidates"] = [
        {
            "model": camera.model,
            "serial_number": str(camera.serial_number),
            "interface": str(camera.interface),
        }
        for camera in cameras
    ]
    wanted_serial = str(config.get("camera_serial_number") or "").strip()
    if wanted_serial:
        selected = next(
            (camera for camera in cameras if str(camera.serial_number) == wanted_serial), None
        )
        if selected is None:
            raise RuntimeError(f"Camera serial {wanted_serial!r} was not detected")
    elif len(cameras) == 1:
        selected = cameras[0]
    else:
        raise RuntimeError("Multiple cameras detected; select a serial number and read again")

    camera = None
    try:
        camera = PrincetonInstruments.PicamCamera(serial_number=selected.serial_number)
        info = camera.get_device_info()
        width, height = camera.get_detector_size()
        raw_serial = _field(info, "serial_number", 1)
        identity = {
            "model": _field(info, "model", 0),
            "serial_number": str(raw_serial) if raw_serial is not None else None,
        }
        _merge_identity(result, "camera", identity)
        result["config"]["camera_serial_number"] = identity["serial_number"] or ""
        camera_state = {
            **identity,
            "detector_size_px": {"width": int(width), "height": int(height)},
        }
        pixel_width = _attribute_value(camera, "Pixel Width")
        pixel_height = _attribute_value(camera, "Pixel Height")
        if pixel_width is not None or pixel_height is not None:
            camera_state["pixel_pitch_um"] = {
                "width": _float_or_none(pixel_width),
                "height": _float_or_none(pixel_height),
            }
        setpoint = _attribute_value(camera, "Sensor Temperature Set Point")
        if setpoint is not None:
            result["config"]["default_temperature"] = int(round(float(setpoint)))
            camera_state["temperature_setpoint_c"] = float(setpoint)
        result["detected_hardware"]["camera"] = camera_state
    finally:
        if camera is not None:
            try:
                camera.close()
            except Exception:
                pass
        if dll_cookie is not None:
            dll_cookie.close()


def _probe_pi_spectrometer(result, config):
    from src.spectrometer_princeton import SpectrometerControllerPI

    controller = SpectrometerControllerPI(config=config, debug=False)
    try:
        if not controller.initialize():
            raise RuntimeError(f"Could not connect on {config.get('com_port', 'COM3')}")
        identity = controller.get_device_identity()
        gratings = controller.get_gratings()
        _merge_identity(result, "spectrometer", identity)
        if gratings:
            result["config"]["grating"] = _config_gratings(gratings, result)
        result["detected_hardware"]["spectrometer"] = {
            **identity,
            "current_grating": int(controller.get_grating()),
            "center_wavelength_nm": float(controller.get_wavelength()),
            "gratings": gratings,
        }
    finally:
        try:
            controller.close()
        except Exception:
            pass


def _config_gratings(gratings, result=None):
    detector = (result or {}).get("detected_hardware", {}).get("camera", {}).get(
        "detector_size_px", {}
    )
    height = detector.get("height")
    if isinstance(height, int) and height > 0:
        span = min(20, height)
        roi = {"from": (height - span) // 2, "to": (height + span) // 2}
    else:
        roi = {"from": 100, "to": 140}
    return [
        {
            **dict(grating),
            "index": int(grating["index"]),
            "grooves": int(grating["grooves"]),
            "defaultROI": dict(roi),
        }
        for grating in gratings
    ]


def _optional(device, method_name):
    method = getattr(device, method_name, None)
    if method is None:
        return None
    try:
        return method()
    except Exception:
        return None


def _attribute_value(camera, name):
    try:
        attribute = camera.get_attribute(name, error_on_missing=False)
        if attribute is None:
            return None
        return camera.get_attribute_value(name)
    except Exception:
        return None


def _field(value, name, index):
    if hasattr(value, name):
        return getattr(value, name)
    try:
        return value[index]
    except (IndexError, KeyError, TypeError):
        return None


def _float_or_none(value):
    return None if value is None else float(value)
