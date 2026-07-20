"""Read-only status collection for pyLabLib Andor SDK2 cameras."""
from __future__ import annotations

from src.instrument_status import device_snapshot, item, safe_item


def collect_andor_camera_status(cam):
    info = _read_or_none(cam.get_device_info)
    detector = _read_or_none(cam.get_detector_size)
    pixel_size = _read_or_none(cam.get_pixel_size)
    frame_timings = _read_or_none(cam.get_frame_timings)

    identity = [
        item("controller_model", "Controller model", _field(info, "controller_model", 0)),
        item("head_model", "Head model", _field(info, "head_model", 1)),
        item("serial_number", "Serial number", _field(info, "serial_number", 2)),
        safe_item("camera_status", "Camera status", cam.get_status),
    ]

    sensor = [
        item("detector_width", "Detector width", _at(detector, 0), "px"),
        item("detector_height", "Detector height", _at(detector, 1), "px"),
        item("pixel_width", "Pixel width", _micrometres(_at(pixel_size, 0)), "um"),
        item("pixel_height", "Pixel height", _micrometres(_at(pixel_size, 1)), "um"),
        item("sensor_width", "Sensor width", _sensor_mm(detector, pixel_size, 0), "mm"),
        item("sensor_height", "Sensor height", _sensor_mm(detector, pixel_size, 1), "mm"),
        safe_item("roi", "Current ROI / binning", cam.get_roi),
    ]

    acquisition = [
        safe_item("read_mode", "Read mode", cam.get_read_mode),
        safe_item("acquisition_mode", "Acquisition mode", cam.get_acquisition_mode),
        safe_item("trigger_mode", "Trigger mode", cam.get_trigger_mode),
        item("exposure", "Exposure", _at(frame_timings, 0), "s"),
        item("frame_period", "Frame period", _at(frame_timings, 1), "s"),
        safe_item("readout_time", "Readout time", cam.get_readout_time, "s"),
    ]

    readout = [
        safe_item("amplifier_mode", "Amplifier mode", cam.get_amp_mode),
        safe_item("channel_bit_depth", "ADC bit depth", cam.get_channel_bitdepth, "bit"),
        safe_item("horizontal_speed", "Horizontal readout rate", cam.get_hsspeed_frequency, "Hz"),
        safe_item("vertical_period", "Vertical shift period", cam.get_vsspeed_period, "s"),
        safe_item("preamp_gain", "Preamp gain", cam.get_preamp_gain),
        safe_item("emccd_gain", "EMCCD gain / advanced", cam.get_EMCCD_gain),
    ]

    thermal = [
        safe_item("temperature_setpoint", "Target temperature", cam.get_temperature_setpoint, "C"),
        safe_item("temperature", "Current temperature", cam.get_temperature, "C"),
        safe_item("temperature_status", "Temperature status", cam.get_temperature_status),
        safe_item("cooler_on", "Cooler on", cam.is_cooler_on),
        safe_item("fan_mode", "Fan mode", cam.get_fan_mode),
        safe_item("temperature_range", "Settable temperature range", cam.get_temperature_range, "C"),
    ]

    io = [
        safe_item("shutter", "Shutter", cam.get_shutter_parameters),
        safe_item("capabilities", "Capabilities", cam.get_capabilities),
    ]
    return device_snapshot(
        "andor_sdk2",
        {
            "Camera identification": identity,
            "Sensor geometry": sensor,
            "Exposure / acquisition": acquisition,
            "Readout / gain": readout,
            "Temperature / cooling": thermal,
            "Shutter / capabilities": io,
        },
    )


def debug_andor_camera_status(width, height, exposure, target_temperature):
    return device_snapshot(
        "andor_sdk2_debug",
        {
            "Camera identification": [
                item("controller_model", "Controller model", "DEBUG controller"),
                item("head_model", "Head model", "Andor Camera [DEBUG]"),
                item("serial_number", "Serial number", "DEBUG-0000000"),
                item("camera_status", "Camera status", "idle"),
            ],
            "Sensor geometry": [
                item("detector_width", "Detector width", width, "px"),
                item("detector_height", "Detector height", height, "px"),
                item("pixel_width", "Pixel width", 26.0, "um"),
                item("pixel_height", "Pixel height", 26.0, "um"),
                item("roi", "Current ROI / binning", [0, width, 0, height, 1, 1]),
            ],
            "Exposure / acquisition": [
                item("read_mode", "Read mode", "image"),
                item("acquisition_mode", "Acquisition mode", "single"),
                item("trigger_mode", "Trigger mode", "internal"),
                item("exposure", "Exposure", exposure, "s"),
                item("frame_period", "Frame period", exposure + 0.02, "s"),
                item("readout_time", "Readout time", 0.02, "s"),
            ],
            "Readout / gain": [item("adc", "ADC bit depth", 16, "bit")],
            "Temperature / cooling": [
                item("temperature_setpoint", "Target temperature", target_temperature, "C"),
                item("temperature", "Current temperature", target_temperature, "C"),
                item("temperature_status", "Temperature status", "stabilized"),
                item("cooler_on", "Cooler on", True),
                item("fan_mode", "Fan mode", "full"),
            ],
            "Shutter / capabilities": [item("shutter", "Shutter", "auto")],
        },
    )


def _read_or_none(getter):
    try:
        return getter()
    except Exception:
        return None


def _field(value, name, index):
    if value is None:
        return None
    return getattr(value, name, _at(value, index))


def _at(value, index):
    try:
        return value[index]
    except (TypeError, IndexError):
        return None


def _micrometres(value):
    return value * 1e6 if value is not None else None


def _sensor_mm(detector, pixel_size, index):
    pixels = _at(detector, index)
    pitch = _at(pixel_size, index)
    return pixels * pitch * 1e3 if pixels is not None and pitch is not None else None
