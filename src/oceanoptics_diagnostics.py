"""Small, dependency-free diagnostics for Ocean Optics discovery failures."""

import os


_OCEAN_OPTICS_USB_VID = "VID_2457"


def windows_device_hint() -> str:
    """Describe an Ocean Optics device known to Windows but hidden from SeaBreeze.

    SeaBreeze returns an empty list both when no instrument is connected and when the
    currently assigned Windows driver exposes the wrong device-interface GUID.  The
    latter is especially common with old OmniDriver/NI-VISA installations, so preserve
    that distinction in the error shown by the setup wizard and camera initialization.
    """
    if os.name != "nt":
        return ""

    try:
        import winreg

        enum_path = r"SYSTEM\CurrentControlSet\Enum\USB"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, enum_path) as usb_key:
            index = 0
            matches = []
            while True:
                try:
                    device_id = winreg.EnumKey(usb_key, index)
                except OSError:
                    break
                index += 1
                if _OCEAN_OPTICS_USB_VID in device_id.upper():
                    matches.append(device_id)
    except (OSError, ImportError):
        return ""

    if not matches:
        return ""
    ids = ", ".join(matches)
    return (
        f" Windows recognizes Ocean Optics USB hardware ({ids}), but SeaBreeze cannot "
        "enumerate it. The assigned driver is likely incompatible; run "
        "setup_oceanoptics.bat as Administrator, then unplug/reconnect the device."
    )


def no_devices_error() -> str:
    return "No Ocean Optics device was detected by SeaBreeze." + windows_device_hint()
