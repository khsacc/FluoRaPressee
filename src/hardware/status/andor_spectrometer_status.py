"""Read-only Shamrock diagnostics kept separate from motion control."""
from __future__ import annotations

import ctypes

from src.hardware.status.instrument_status import device_snapshot, item, unavailable_device


SUCCESS = 20202
_STRING_SIZE = 256


class ShamrockStatusError(RuntimeError):
    pass


def configure_status_prototypes(dll):
    """Declare the status-related Shamrock C API signatures when available."""
    p_int = ctypes.POINTER(ctypes.c_int)
    p_float = ctypes.POINTER(ctypes.c_float)
    signatures = {
        "ShamrockInitialize": ([ctypes.c_char_p], ctypes.c_int),
        "ShamrockClose": ([], ctypes.c_int),
        "ShamrockGetNumberDevices": ([p_int], ctypes.c_int),
        "ShamrockGetSerialNumber": ([ctypes.c_int, ctypes.c_char_p], ctypes.c_int),
        "ShamrockEepromGetOpticalParams": ([ctypes.c_int, p_float, p_float, p_float], ctypes.c_int),
        "ShamrockGetTurret": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetNumberGratings": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetGrating": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetGratingInfo": (
            [ctypes.c_int, ctypes.c_int, p_float, ctypes.c_char_p, p_int, p_int], ctypes.c_int
        ),
        "ShamrockGetWavelength": ([ctypes.c_int, p_float], ctypes.c_int),
        "ShamrockGetWavelengthLimits": ([ctypes.c_int, ctypes.c_int, p_float, p_float], ctypes.c_int),
        "ShamrockSetNumberPixels": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
        "ShamrockSetPixelWidth": ([ctypes.c_int, ctypes.c_float], ctypes.c_int),
        "ShamrockGetCalibration": (
            [ctypes.c_int, p_float, ctypes.c_int], ctypes.c_int
        ),
        "ShamrockAtZeroOrder": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockAutoSlitIsPresent": ([ctypes.c_int, ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetAutoSlitWidth": ([ctypes.c_int, ctypes.c_int, p_float], ctypes.c_int),
        "ShamrockShutterIsPresent": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetShutter": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockFilterIsPresent": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetFilter": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetFilterInfo": ([ctypes.c_int, ctypes.c_int, ctypes.c_char_p], ctypes.c_int),
        "ShamrockFlipperMirrorIsPresent": ([ctypes.c_int, ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetFlipperMirror": ([ctypes.c_int, ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockFocusMirrorIsPresent": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetFocusMirror": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetFocusMirrorMaxSteps": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockIrisIsPresent": ([ctypes.c_int, ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetIris": ([ctypes.c_int, ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockAccessoryIsPresent": ([ctypes.c_int, p_int], ctypes.c_int),
        "ShamrockGetAccessoryState": ([ctypes.c_int, ctypes.c_int, p_int], ctypes.c_int),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(dll, name, None)
        if function is not None:
            function.argtypes = argtypes
            function.restype = restype


def collect_shamrock_status(dll, device_id, initialized, debug=False):
    if debug:
        return _debug_snapshot()
    if not initialized or dll is None:
        return unavailable_device("andor_shamrock", "Spectrograph is not connected.")

    sections = {
        "Spectrograph identification": _collect_identity(dll, device_id),
        "Current position": _collect_position(dll, device_id),
        "Installed gratings": _collect_gratings(dll, device_id),
        "Optical geometry": _collect_optics(dll, device_id),
        "Accessories": _collect_accessories(dll, device_id),
    }
    return device_snapshot("andor_shamrock", sections)


def get_shamrock_gratings(dll, device):
    """Return concise grating data for config cross-checking."""
    count = _get_int(dll, "ShamrockGetNumberGratings", device)
    gratings = []
    for index in range(1, count + 1):
        lines = ctypes.c_float()
        blaze = ctypes.create_string_buffer(_STRING_SIZE)
        home = ctypes.c_int()
        offset = ctypes.c_int()
        _call(
            dll, "ShamrockGetGratingInfo", device, index,
            ctypes.byref(lines), blaze, ctypes.byref(home), ctypes.byref(offset),
        )
        low = ctypes.c_float()
        high = ctypes.c_float()
        _call(
            dll, "ShamrockGetWavelengthLimits", device, index,
            ctypes.byref(low), ctypes.byref(high),
        )
        gratings.append({
            "index": index,
            "grooves": int(round(lines.value)),
            "blaze": blaze.value.decode(errors="replace").strip(),
            "home": home.value,
            "offset": offset.value,
            "wavelength_limits_nm": {"min": low.value, "max": high.value},
        })
    return gratings


def _collect_identity(dll, device):
    return [_query_item("serial_number", "Serial number", lambda: _get_string(dll, "ShamrockGetSerialNumber", device))]


def _collect_position(dll, device):
    return [
        _query_item("centre_wavelength", "Centre wavelength", lambda: _get_float(dll, "ShamrockGetWavelength", device), "nm"),
        _query_item("grating", "Current grating", lambda: _get_int(dll, "ShamrockGetGrating", device)),
        _query_item("turret", "Turret", lambda: _get_int(dll, "ShamrockGetTurret", device)),
        _query_item("zero_order", "At zero order", lambda: bool(_get_int(dll, "ShamrockAtZeroOrder", device))),
    ]


def _collect_gratings(dll, device):
    try:
        count = _get_int(dll, "ShamrockGetNumberGratings", device)
    except Exception as exc:
        return [item("grating_count", "Grating count", state="error", error=exc)]

    rows = [item("grating_count", "Grating count", count)]
    for index in range(1, count + 1):
        try:
            lines = ctypes.c_float()
            blaze = ctypes.create_string_buffer(_STRING_SIZE)
            home = ctypes.c_int()
            offset = ctypes.c_int()
            _call(
                dll, "ShamrockGetGratingInfo", device, index,
                ctypes.byref(lines), blaze, ctypes.byref(home), ctypes.byref(offset),
            )
            low = ctypes.c_float()
            high = ctypes.c_float()
            _call(dll, "ShamrockGetWavelengthLimits", device, index, ctypes.byref(low), ctypes.byref(high))
            value = {
                "lines_per_mm": lines.value,
                "blaze": blaze.value.decode(errors="replace").strip(),
                "home": home.value,
                "offset": offset.value,
                "wavelength_min_nm": low.value,
                "wavelength_max_nm": high.value,
            }
            rows.append(item(f"grating_{index}", f"Grating {index}", value))
        except Exception as exc:
            rows.append(item(f"grating_{index}", f"Grating {index}", state="error", error=exc))
    return rows


def _collect_optics(dll, device):
    try:
        focal = ctypes.c_float()
        deviation = ctypes.c_float()
        tilt = ctypes.c_float()
        _call(dll, "ShamrockEepromGetOpticalParams", device, ctypes.byref(focal), ctypes.byref(deviation), ctypes.byref(tilt))
        return [
            item("focal_length", "Focal length", focal.value, "mm"),
            item("angular_deviation", "Angular deviation", deviation.value, "deg"),
            item("focal_tilt", "Focal tilt", tilt.value, "deg"),
        ]
    except Exception as exc:
        return [item("optical_geometry", "Optical geometry", state="error", error=exc)]


def _collect_accessories(dll, device):
    rows = []
    slit_names = ("Input side slit", "Input direct slit", "Output side slit", "Output direct slit")
    for index, label in enumerate(slit_names, start=1):
        _append_if_present(
            rows, dll, device, "ShamrockAutoSlitIsPresent", index,
            f"auto_slit_{index}", label,
            lambda idx=index: _get_float(dll, "ShamrockGetAutoSlitWidth", device, idx), "um",
        )
    _append_if_present(rows, dll, device, "ShamrockShutterIsPresent", None, "shutter", "Shutter mode", lambda: _get_int(dll, "ShamrockGetShutter", device))
    _append_if_present(rows, dll, device, "ShamrockFilterIsPresent", None, "filter", "Filter", lambda: _filter_value(dll, device))
    for index in (1, 2):
        _append_if_present(rows, dll, device, "ShamrockFlipperMirrorIsPresent", index, f"flipper_{index}", f"Flipper mirror {index}", lambda idx=index: _get_int(dll, "ShamrockGetFlipperMirror", device, idx))
    _append_focus_mirror(rows, dll, device)
    for index, label in ((0, "Direct-port iris"), (1, "Side-port iris")):
        _append_if_present(rows, dll, device, "ShamrockIrisIsPresent", index, f"iris_{index}", label, lambda idx=index: _get_int(dll, "ShamrockGetIris", device, idx))
    _append_accessory_lines(rows, dll, device)
    return rows or [item("accessories", "Detected accessories", "None")]


def _append_if_present(rows, dll, device, presence_name, index, key, label, getter, unit=None):
    try:
        args = (device,) if index is None else (device, index)
        if _get_int(dll, presence_name, *args):
            rows.append(_query_item(key, label, getter, unit))
    except Exception as exc:
        if not isinstance(exc, AttributeError):
            rows.append(item(key, label, state="error", error=exc))


def _append_focus_mirror(rows, dll, device):
    try:
        if _get_int(dll, "ShamrockFocusMirrorIsPresent", device):
            value = {
                "position": _get_int(dll, "ShamrockGetFocusMirror", device),
                "max_steps": _get_int(dll, "ShamrockGetFocusMirrorMaxSteps", device),
            }
            rows.append(item("focus_mirror", "Focus mirror", value))
    except Exception as exc:
        if not isinstance(exc, AttributeError):
            rows.append(item("focus_mirror", "Focus mirror", state="error", error=exc))


def _append_accessory_lines(rows, dll, device):
    try:
        if _get_int(dll, "ShamrockAccessoryIsPresent", device):
            for line in (1, 2):
                rows.append(item(f"accessory_{line}", f"Accessory line {line}", _get_int(dll, "ShamrockGetAccessoryState", device, line)))
    except Exception as exc:
        if not isinstance(exc, AttributeError):
            rows.append(item("accessory_lines", "Accessory lines", state="error", error=exc))


def _filter_value(dll, device):
    position = _get_int(dll, "ShamrockGetFilter", device)
    description = _get_string(dll, "ShamrockGetFilterInfo", device, position)
    return {"position": position, "description": description}


def _query_item(key, label, getter, unit=None):
    try:
        return item(key, label, getter(), unit)
    except Exception as exc:
        state = "unsupported" if isinstance(exc, AttributeError) else "error"
        return item(key, label, state=state, error=exc)


def _get_int(dll, name, *args):
    value = ctypes.c_int()
    _call(dll, name, *args, ctypes.byref(value))
    return value.value


def _get_float(dll, name, *args):
    value = ctypes.c_float()
    _call(dll, name, *args, ctypes.byref(value))
    return value.value


def _get_string(dll, name, *args):
    value = ctypes.create_string_buffer(_STRING_SIZE)
    _call(dll, name, *args, value)
    return value.value.decode(errors="replace").strip()


def _call(dll, name, *args):
    function = getattr(dll, name, None)
    if function is None:
        raise AttributeError(f"{name} is not available in this Shamrock DLL")
    result = function(*args)
    if result != SUCCESS:
        raise ShamrockStatusError(f"{name} failed with Shamrock error {result}")


def _debug_snapshot():
    return device_snapshot(
        "andor_shamrock_debug",
        {
            "Spectrograph identification": [item("serial_number", "Serial number", "DEBUG-SHAMROCK-0000000")],
            "Current position": [
                item("centre_wavelength", "Centre wavelength", 694.0, "nm"),
                item("grating", "Current grating", 1),
                item("turret", "Turret", 1),
                item("zero_order", "At zero order", False),
            ],
            "Installed gratings": [
                item("grating_count", "Grating count", 3),
                item("grating_1", "Grating 1", {"lines_per_mm": 600, "blaze": "500 nm", "wavelength_min_nm": 0, "wavelength_max_nm": 1200}),
                item("grating_2", "Grating 2", {"lines_per_mm": 1200, "blaze": "750 nm", "wavelength_min_nm": 0, "wavelength_max_nm": 1000}),
                item("grating_3", "Grating 3", {"lines_per_mm": 1800, "blaze": "500 nm", "wavelength_min_nm": 0, "wavelength_max_nm": 800}),
            ],
            "Optical geometry": [
                item("focal_length", "Focal length", 303.0, "mm"),
                item("angular_deviation", "Angular deviation", 0.0, "deg"),
                item("focal_tilt", "Focal tilt", 0.0, "deg"),
            ],
            "Accessories": [item("auto_slit_1", "Input side slit", 100.0, "um")],
        },
    )
