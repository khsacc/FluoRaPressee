"""Read connected hardware to pre-fill the first-run configuration wizard."""
from __future__ import annotations

from datetime import datetime
import os

from src.pylablib_loader import import_pylablib_module


SUPPLIER_ANDOR = "Andor"
SUPPLIER_PI = "PrincetonInstruments"
SUPPLIER_OCEANOPTICS = "OceanOptics"


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
    elif supplier == SUPPLIER_OCEANOPTICS:
        _run_probe(result, "Ocean Optics device", _probe_oceanoptics, config)
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
    Andor = import_pylablib_module("pylablib.devices.Andor")

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
            "temperature_control_available": True,
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
        result["detected_hardware"]["spectrometer"] = dict(identity)
    finally:
        try:
            controller.close()
        except Exception:
            pass


def _probe_pi_camera(result, config):
    pylablib = import_pylablib_module("pylablib")
    PrincetonInstruments = import_pylablib_module("pylablib.devices.PrincetonInstruments")

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
        has_temperature_control = _pi_temperature_control_available(camera)
        camera_state["temperature_control_available"] = has_temperature_control
        if has_temperature_control and setpoint is not None:
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
        result["detected_hardware"]["spectrometer"] = dict(identity)
    finally:
        try:
            controller.close()
        except Exception:
            pass


def _probe_oceanoptics(result, config):
    """Best-effort device listing only (optional per work/work_OceanOptics.md Step 9) - Ocean
    Optics has no separate grating/cooler to detect, unlike Andor/Princeton Instruments.

    TODO(実機確認待ち): list_devices()の返り値がmodel/serial_number属性を実際に持つか、
    デバイスを開かずに読めるかは実機/実際のseabreezeで未確認。失敗しても
    _run_probe()がexceptionを捕捉してerrorsへ積むだけなので、ウィザードがクラッシュする
    ことはない。
    """
    import seabreeze

    backend_name = config.get("seabreeze_backend")
    if backend_name:
        seabreeze.use(backend_name)
    from seabreeze.spectrometers import list_devices

    devices = list_devices()
    if not devices:
        from src.oceanoptics_diagnostics import no_devices_error

        raise RuntimeError(no_devices_error())
    result["camera_candidates"] = [
        {"model": device.model, "serial_number": str(device.serial_number), "interface": ""}
        for device in devices
    ]
    wanted_serial = str(config.get("serial_number") or "").strip()
    if wanted_serial:
        selected = next(
            (device for device in devices if str(device.serial_number) == wanted_serial), None
        )
        if selected is None:
            raise RuntimeError(f"Device serial {wanted_serial!r} was not detected")
    elif len(devices) == 1:
        selected = devices[0]
    else:
        raise RuntimeError("Multiple devices detected; select a serial number and read again")

    # Ocean Optics is a single physical device serving both roles (work/work_OceanOptics.md
    # 方針2), so the same identity is recorded under both categories.
    identity = {"model": selected.model, "serial_number": str(selected.serial_number)}
    _merge_identity(result, "camera", identity)
    _merge_identity(result, "spectrometer", identity)
    result["config"]["serial_number"] = identity["serial_number"]
    result["detected_hardware"]["camera"] = {
        **identity,
        "temperature_control_available": False,
    }
    result["detected_hardware"]["spectrometer"] = dict(identity)


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


def _pi_temperature_control_available(camera):
    """Mirror CameraThreadPI's usable temperature-control capability check."""
    try:
        setpoint = camera.get_attribute(
            "Sensor Temperature Set Point", error_on_missing=False
        )
        reading = camera.get_attribute(
            "Sensor Temperature Reading", error_on_missing=False
        )
        if setpoint is None or reading is None:
            return False
        setpoint_current = camera.get_attribute_value(
            "Sensor Temperature Set Point"
        )
        reading_current = camera.get_attribute_value(
            "Sensor Temperature Reading"
        )
        return bool(
            setpoint.exists
            and setpoint.relevant
            and setpoint.writable
            and setpoint_current is not None
            and reading.exists
            and reading.relevant
            and reading_current is not None
        )
    except Exception:
        return False


def _field(value, name, index):
    if hasattr(value, name):
        return getattr(value, name)
    try:
        return value[index]
    except (IndexError, KeyError, TypeError):
        return None


def _float_or_none(value):
    return None if value is None else float(value)
