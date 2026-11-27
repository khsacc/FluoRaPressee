"""Find connected Ocean Optics USB devices and their best matching Windows INF."""

import ctypes
from ctypes import wintypes as wt
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from uuid import UUID

_DIGCF_PRESENT = 0x02
_DIGCF_ALLCLASSES = 0x04
_DIGCF_DEVICEINTERFACE = 0x10
_SPDRP_HARDWAREID = 1
_SPDIT_COMPATDRIVER = 2
_DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x800
_DNF_BAD_DRIVER = 0x800
_ERROR_INVALID_DATA = 13
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_NO_MORE_ITEMS = 259
_ERROR_NO_COMPAT_DRIVERS = 0xE0000228
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_SEABREEZE_INTERFACE = UUID("dbbad306-1786-4f2e-a8ab-340d45f0653f")


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SetupApiStructure(ctypes.Structure):
    # setupapi.h uses packing of 8 for Win64 and 1 for Win32.
    _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1


class _DeviceInfo(_SetupApiStructure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("ClassGuid", _Guid), ("DevInst", wt.DWORD),
        ("Reserved", ctypes.c_size_t),
    ]


class _InstallParams(_SetupApiStructure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("Flags", wt.DWORD), ("FlagsEx", wt.DWORD),
        ("hwndParent", wt.HWND), ("InstallMsgHandler", ctypes.c_void_p),
        ("InstallMsgHandlerContext", ctypes.c_void_p), ("FileQueue", wt.HANDLE),
        ("ClassInstallReserved", ctypes.c_size_t), ("Reserved", wt.DWORD),
        ("DriverPath", wt.WCHAR * wt.MAX_PATH),
    ]


class _DriverInfo(_SetupApiStructure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("DriverType", wt.DWORD), ("Reserved", ctypes.c_size_t),
        ("Description", wt.WCHAR * 256), ("MfgName", wt.WCHAR * 256),
        ("ProviderName", wt.WCHAR * 256), ("DriverDate", wt.FILETIME),
        ("DriverVersion", ctypes.c_uint64),
    ]


class _DriverDetail(_SetupApiStructure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("InfDate", wt.FILETIME), ("CompatIDsOffset", wt.DWORD),
        ("CompatIDsLength", wt.DWORD), ("Reserved", ctypes.c_size_t),
        ("SectionName", wt.WCHAR * 256), ("InfFileName", wt.WCHAR * wt.MAX_PATH),
        ("DrvDescription", wt.WCHAR * 256), ("HardwareID", wt.WCHAR * 1),
    ]


class _DriverInstallParams(_SetupApiStructure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("Rank", wt.DWORD), ("Flags", wt.DWORD),
        ("PrivateData", ctypes.c_size_t), ("Reserved", wt.DWORD),
    ]


@dataclass(frozen=True)
class UsbDevice:
    instance_id: str
    hardware_ids: tuple[str, ...]
    info: _DeviceInfo


def _load_setupapi():
    api = ctypes.WinDLL("setupapi.dll", use_last_error=True)
    device = ctypes.POINTER(_DeviceInfo)
    params = ctypes.POINTER(_InstallParams)
    driver = ctypes.POINTER(_DriverInfo)
    handle = wt.HANDLE
    signatures = (
        ("SetupDiGetClassDevsW", handle, (ctypes.POINTER(_Guid), wt.LPCWSTR, wt.HWND, wt.DWORD)),
        ("SetupDiDestroyDeviceInfoList", wt.BOOL, (handle,)),
        ("SetupDiEnumDeviceInfo", wt.BOOL, (handle, wt.DWORD, device)),
        ("SetupDiGetDeviceInstanceIdW", wt.BOOL, (handle, device, wt.LPWSTR, wt.DWORD, wt.LPDWORD)),
        ("SetupDiGetDeviceRegistryPropertyW", wt.BOOL,
         (handle, device, wt.DWORD, wt.LPDWORD, ctypes.c_void_p, wt.DWORD, wt.LPDWORD)),
        ("SetupDiGetDeviceInstallParamsW", wt.BOOL, (handle, device, params)),
        ("SetupDiSetDeviceInstallParamsW", wt.BOOL, (handle, device, params)),
        ("SetupDiBuildDriverInfoList", wt.BOOL, (handle, device, wt.DWORD)),
        ("SetupDiDestroyDriverInfoList", wt.BOOL, (handle, device, wt.DWORD)),
        ("SetupDiEnumDriverInfoW", wt.BOOL, (handle, device, wt.DWORD, wt.DWORD, driver)),
        ("SetupDiGetDriverInstallParamsW", wt.BOOL,
         (handle, device, driver, ctypes.POINTER(_DriverInstallParams))),
        ("SetupDiGetDriverInfoDetailW", wt.BOOL,
         (handle, device, driver, ctypes.POINTER(_DriverDetail), wt.DWORD, wt.LPDWORD)),
    )
    for name, result_type, argument_types in signatures:
        function = getattr(api, name)
        function.restype = result_type
        function.argtypes = argument_types
    return api


@contextmanager
def _device_set(api, flags, interface=None):
    # With DIGCF_DEVICEINTERFACE, Enumerator must be a full device instance ID
    # or NULL for all devices. The bus name "USB" is only used for device sets.
    enumerator = None if flags & _DIGCF_DEVICEINTERFACE else "USB"
    handle = api.SetupDiGetClassDevsW(interface, enumerator, None, _DIGCF_PRESENT | flags)
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield handle
    finally:
        api.SetupDiDestroyDeviceInfoList(handle)


def _device_infos(api, handle):
    for index in count():
        info = _DeviceInfo(cbSize=ctypes.sizeof(_DeviceInfo))
        if not api.SetupDiEnumDeviceInfo(handle, index, ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == _ERROR_NO_MORE_ITEMS:
                return
            raise ctypes.WinError(error)
        yield info


def _instance_id(api, handle, info):
    # MAX_DEVICE_ID_LEN (cfgmgr32.h), including the terminator.
    buffer = ctypes.create_unicode_buffer(200)
    if not api.SetupDiGetDeviceInstanceIdW(handle, ctypes.byref(info), buffer, len(buffer), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value.upper()


def _hardware_ids(api, handle, info):
    get_property = api.SetupDiGetDeviceRegistryPropertyW
    required = wt.DWORD()
    device = ctypes.byref(info)
    if get_property(handle, device, _SPDRP_HARDWAREID, None, None, 0, ctypes.byref(required)):
        return ()
    error = ctypes.get_last_error()
    if error == _ERROR_INVALID_DATA:
        return ()
    if error != _ERROR_INSUFFICIENT_BUFFER:
        raise ctypes.WinError(error)

    buffer = ctypes.create_string_buffer(required.value)
    if not get_property(handle, device, _SPDRP_HARDWAREID, None, buffer, len(buffer), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return tuple(buffer.raw.decode("utf-16-le").upper().rstrip("\0").split("\0"))


def _is_oceanoptics_id(hardware_id):
    # The bundle targets USB devices. A composite device's child interfaces can
    # disappear when its parent switches to the SeaBreeze driver.
    if "&MI_" in hardware_id:
        return False
    # The upstream archive also includes the MMS Raman device with a different VID.
    return (hardware_id.startswith(r"USB\VID_2457&PID_")
            or hardware_id.split("&REV_", 1)[0] == r"USB\VID_184C&PID_0000")


@contextmanager
def connected_devices():
    """Keep the Plug and Play device set alive while matching its present USB devices."""
    api = _load_setupapi()
    with _device_set(api, _DIGCF_ALLCLASSES) as handle:
        devices = []
        for info in _device_infos(api, handle):
            hardware_ids = _hardware_ids(api, handle, info)
            if any(map(_is_oceanoptics_id, hardware_ids)):
                devices.append(UsbDevice(_instance_id(api, handle, info), hardware_ids, info))
        yield api, handle, devices


def seabreeze_interfaces(api):
    """Return USB instance IDs exposing the interface provided by the SeaBreeze INF files."""
    guid = _Guid.from_buffer_copy(_SEABREEZE_INTERFACE.bytes_le)
    with _device_set(api, _DIGCF_DEVICEINTERFACE, ctypes.byref(guid)) as handle:
        return {_instance_id(api, handle, info) for info in _device_infos(api, handle)}


def _ranked_drivers(api, handle, device):
    for index in count():
        driver = _DriverInfo(cbSize=ctypes.sizeof(_DriverInfo))
        if not api.SetupDiEnumDriverInfoW(
            handle, device, _SPDIT_COMPATDRIVER, index, ctypes.byref(driver)
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_NO_MORE_ITEMS:
                return
            raise ctypes.WinError(error)
        install = _DriverInstallParams(cbSize=ctypes.sizeof(_DriverInstallParams))
        if not api.SetupDiGetDriverInstallParamsW(
            handle, device, ctypes.byref(driver), ctypes.byref(install)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if install.Flags & _DNF_BAD_DRIVER:
            continue
        date = (driver.DriverDate.dwHighDateTime << 32) | driver.DriverDate.dwLowDateTime
        yield (install.Rank, -date, -driver.DriverVersion), driver


def _driver_inf_path(api, handle, device, driver):
    detail = _DriverDetail(cbSize=ctypes.sizeof(_DriverDetail))
    if not api.SetupDiGetDriverInfoDetailW(
        handle, device, ctypes.byref(driver), ctypes.byref(detail), ctypes.sizeof(detail), None
    ):
        # The fixed fields, including InfFileName, are filled even when the ID list is too large.
        error = ctypes.get_last_error()
        if error != _ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(error)
    return Path(detail.InfFileName).resolve()


def best_matching_inf(api, handle, usb_device, package_dir: Path) -> Path | None:
    """Ask Windows to rank INF matches for this device and OS in the extracted bundle."""
    device = ctypes.byref(usb_device.info)
    params = _InstallParams(cbSize=ctypes.sizeof(_InstallParams))
    if not api.SetupDiGetDeviceInstallParamsW(handle, device, ctypes.byref(params)):
        raise ctypes.WinError(ctypes.get_last_error())
    params.FlagsEx |= _DI_FLAGSEX_ALLOWEXCLUDEDDRVS
    params.DriverPath = str(package_dir)
    if not api.SetupDiSetDeviceInstallParamsW(handle, device, ctypes.byref(params)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not api.SetupDiBuildDriverInfoList(handle, device, _SPDIT_COMPATDRIVER):
        error = ctypes.get_last_error()
        if (error & 0xFFFFFFFF) == _ERROR_NO_COMPAT_DRIVERS:
            return None
        raise ctypes.WinError(error)
    try:
        # Use Windows' rank/date/version order without changing the device's setup class.
        best = min(_ranked_drivers(api, handle, device), key=lambda ranked: ranked[0], default=None)
        if best is None:
            return None
        _, driver = best
        inf_path = _driver_inf_path(api, handle, device, driver)
    finally:
        api.SetupDiDestroyDriverInfoList(handle, device, _SPDIT_COMPATDRIVER)

    if inf_path.parent != package_dir or inf_path.suffix.lower() != ".inf" or not inf_path.is_file():
        raise OSError(f"Windows selected an INF outside the SeaBreeze package: {inf_path}")
    return inf_path
