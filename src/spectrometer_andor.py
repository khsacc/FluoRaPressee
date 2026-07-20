import ctypes
import time
import json  
import os    
from threading import RLock
from PyQt5.QtCore import QThread, pyqtSignal

from src.andor_spectrometer_status import (
    collect_shamrock_status,
    configure_status_prototypes,
    get_shamrock_gratings,
)

class SpectrometerControllerAndor:
    """Andor Kymera / Shamrock Spectrometer Controller"""
    
    SHAMROCK_SUCCESS = 20202

    def __init__(self, debug=False):
        self.debug = debug
        self.is_initialized = False
        self.device_id = 0
        self.shamrock = None
        self._hw_lock = RLock()
        self._serial_number = None
        self._gratings = []
        self._current_grating = 1
        self._current_wavelength_nm = 694.0

    def initialize(self):
        if self.debug:
            print("[DEBUG MODE] Spectrometer dummy mode forced.")
            self.is_initialized = False
            return False

        print("Spectrometer initialisation...")

        dll_path = "ShamrockCIF.dll" # Default value
        config_path = "spectrometerConfig.json"

        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Use the "dll_path" key from the JSON if present, otherwise fall back to the default
                    dll_path = config.get("dll_path", "ShamrockCIF.dll")
            except Exception as e:
                print(f"Failed to read config file: {e}. Using default path.")

        try:
            self.shamrock = ctypes.windll.LoadLibrary(dll_path)
            configure_status_prototypes(self.shamrock)
            ini_path = ctypes.create_string_buffer(b"")
            ret = self.shamrock.ShamrockInitialize(ini_path)
            
            if ret != self.SHAMROCK_SUCCESS:
                print(f"Shamrock initialization failed with code: {ret}")
                return False

            num_devices = ctypes.c_int()
            self.shamrock.ShamrockGetNumberDevices(ctypes.byref(num_devices))
            if num_devices.value < 1:
                print("No Shamrock spectrometer found.")
                return False

            self.device_id = 0 
            print(f"Found {num_devices.value} Shamrock device(s). Using device {self.device_id}.")
            
            self.is_initialized = True
            return True
            
        except OSError as e:
            print(f"[Warning] Failed to load Shamrock DLL. Running in dummy mode. Error: {e}")
            self.is_initialized = False
            return False
        except Exception as e:
            print(f"An error occurred during initialization: {e}")
            return False

    def get_wavelength(self):
        if not self.is_initialized or not self.shamrock:
            return 694.0 # Dummy value (used when not initialized/connected)
        try:
            wl = ctypes.c_float()
            with self._hw_lock:
                ret = self.shamrock.ShamrockGetWavelength(self.device_id, ctypes.byref(wl))
            if ret == self.SHAMROCK_SUCCESS:
                self._current_wavelength_nm = float(wl.value)
                return wl.value
        except Exception as e:
            pass
        return 694.0

    def get_grating(self):
        if not self.is_initialized or not self.shamrock:
            return 1 # Dummy value (used when not initialized/connected)
        try:
            grating = ctypes.c_int()
            with self._hw_lock:
                ret = self.shamrock.ShamrockGetGrating(self.device_id, ctypes.byref(grating))
            if ret == self.SHAMROCK_SUCCESS:
                self._current_grating = int(grating.value)
                return grating.value
        except Exception as e:
            pass
        return 1

    def get_device_identity(self):
        """Return {"model": None, "serial_number": str|None} for hardware_identity
        cross-checking (see ConfigMixin.check_and_record_hardware_identity()).

        The ShamrockCIF SDK has no call to read back a model designation, only
        ShamrockGetSerialNumber -- so "model" is always None here.
        """
        if self.debug:
            # Fabricated so --debug mode can exercise the identity check; kept out of
            # "model" since real Shamrock hardware never reports one either.
            self._serial_number = "DEBUG-SHAMROCK-0000000"
            return {"model": None, "serial_number": self._serial_number}
        if not self.is_initialized or not self.shamrock:
            return {"model": None, "serial_number": None}
        try:
            serial_buf = ctypes.create_string_buffer(256)
            with self._hw_lock:
                ret = self.shamrock.ShamrockGetSerialNumber(self.device_id, serial_buf)
            if ret == self.SHAMROCK_SUCCESS:
                serial = serial_buf.value.decode(errors="replace").strip()
                self._serial_number = serial or None
                return {"model": None, "serial_number": serial or None}
        except Exception as e:
            print(f"Failed to read spectrometer serial number: {e}")
        return {"model": None, "serial_number": None}

    def get_status_snapshot(self):
        """Return a complete read-only spectrograph status snapshot."""
        with self._hw_lock:
            return collect_shamrock_status(
                self.shamrock, self.device_id, self.is_initialized, debug=self.debug
            )

    def get_gratings(self):
        if self.debug:
            self._gratings = [
                {"index": 1, "grooves": 600, "blaze": "500 nm", "wavelength_limits_nm": {"min": 0.0, "max": 1200.0}},
                {"index": 2, "grooves": 1200, "blaze": "750 nm", "wavelength_limits_nm": {"min": 0.0, "max": 1000.0}},
                {"index": 3, "grooves": 1800, "blaze": "500 nm", "wavelength_limits_nm": {"min": 0.0, "max": 800.0}},
            ]
            return [dict(grating) for grating in self._gratings]
        if not self.is_initialized or self.shamrock is None:
            return []
        try:
            with self._hw_lock:
                self._gratings = get_shamrock_gratings(self.shamrock, self.device_id)
                return [dict(grating) for grating in self._gratings]
        except Exception as exc:
            print(f"Failed to read installed gratings: {exc}")
            return []

    def set_wavelength(self, wavelength_nm):
        if not self.is_initialized:
            print(f"(Dummy) Setting spectrometer wavelength to {wavelength_nm} nm...")
            time.sleep(1.5) 
            return False
            
        print(f"Setting spectrometer wavelength to {wavelength_nm} nm...")
        try:
            with self._hw_lock:
                ret = self.shamrock.ShamrockSetWavelength(self.device_id, ctypes.c_float(wavelength_nm))
                if ret == self.SHAMROCK_SUCCESS:
                    actual = ctypes.c_float()
                    read_ret = self.shamrock.ShamrockGetWavelength(
                        self.device_id, ctypes.byref(actual)
                    )
                    self._current_wavelength_nm = (
                        float(actual.value)
                        if read_ret == self.SHAMROCK_SUCCESS
                        else float(wavelength_nm)
                    )
            return ret == self.SHAMROCK_SUCCESS
        except Exception as e:
            return False

    def set_grating(self, grating_index):
        if not self.is_initialized:
            print(f"(Dummy) Changing grating to index {grating_index}...")
            time.sleep(2.0) 
            return False
            
        print(f"Changing grating to index {grating_index}...")
        try:
            with self._hw_lock:
                ret = self.shamrock.ShamrockSetGrating(self.device_id, ctypes.c_int(grating_index))
                if ret == self.SHAMROCK_SUCCESS:
                    actual = ctypes.c_int()
                    read_ret = self.shamrock.ShamrockGetGrating(
                        self.device_id, ctypes.byref(actual)
                    )
                    self._current_grating = (
                        int(actual.value)
                        if read_ret == self.SHAMROCK_SUCCESS
                        else int(grating_index)
                    )
            return ret == self.SHAMROCK_SUCCESS
        except Exception as e:
            return False

    def get_cached_hardware_metadata(self):
        """Return spectrograph metadata without issuing DLL calls."""
        with self._hw_lock:
            if self.debug and not self._gratings:
                self.get_gratings()
            selected = next(
                (dict(grating) for grating in self._gratings if grating.get("index") == self._current_grating),
                {},
            )
            limits = selected.pop("wavelength_limits_nm", None)
            return {
                "serial_number": self._serial_number,
                "grating": {
                    "index": self._current_grating,
                    "grooves_per_mm": selected.get("grooves"),
                    "blaze": selected.get("blaze"),
                },
                "center_wavelength_nm": self._current_wavelength_nm,
                "wavelength_limits_nm": limits,
            }

    def close(self):
        if self.is_initialized and self.shamrock:
            try:
                with self._hw_lock:
                    self.shamrock.ShamrockClose()
            except Exception as e:
                pass
            finally:
                self.is_initialized = False


class SpectrometerMoveThread(QThread):
    finished_signal = pyqtSignal()

    def __init__(self, spec_ctrl, grating_index, wavelength):
        super().__init__()
        self.spec_ctrl = spec_ctrl
        self.grating_index = grating_index
        self.wavelength = wavelength

    def run(self):
        self.spec_ctrl.set_grating(self.grating_index)
        self.spec_ctrl.set_wavelength(self.wavelength)
        self.finished_signal.emit()
