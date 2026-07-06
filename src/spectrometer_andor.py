import ctypes
import time
import json  
import os    
from PyQt5.QtCore import QThread, pyqtSignal

class SpectrometerControllerAndor:
    """Andor Kymera / Shamrock Spectrometer Controller"""
    
    SHAMROCK_SUCCESS = 20202

    def __init__(self, debug=False):
        self.debug = debug
        self.is_initialized = False
        self.device_id = 0
        self.shamrock = None

    def initialize(self):
        if self.debug:
            print("[DEBUG MODE] Spectrometer dummy mode forced.")
            self.is_initialized = False
            return False

        print("Spectrometer initialisation...")

        dll_path = "ShamrockCIF.dll" # デフォルト値
        config_path = "spectrometerConfig.json"

        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # JSON内に "dll_path" キーがあれば取得、なければデフォルト値
                    dll_path = config.get("dll_path", "ShamrockCIF.dll")
            except Exception as e:
                print(f"Failed to read config file: {e}. Using default path.")

        try:
            self.shamrock = ctypes.windll.LoadLibrary(dll_path)
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
            return 694.0 # ダミー値
        try:
            wl = ctypes.c_float()
            ret = self.shamrock.ShamrockGetWavelength(self.device_id, ctypes.byref(wl))
            if ret == self.SHAMROCK_SUCCESS:
                return wl.value
        except Exception as e:
            pass
        return 694.0

    def get_grating(self):
        if not self.is_initialized or not self.shamrock:
            return 1 # ダミー値
        try:
            grating = ctypes.c_int()
            ret = self.shamrock.ShamrockGetGrating(self.device_id, ctypes.byref(grating))
            if ret == self.SHAMROCK_SUCCESS:
                return grating.value
        except Exception as e:
            pass
        return 1

    def set_wavelength(self, wavelength_nm):
        if not self.is_initialized:
            print(f"(Dummy) Setting spectrometer wavelength to {wavelength_nm} nm...")
            time.sleep(1.5) 
            return False
            
        print(f"Setting spectrometer wavelength to {wavelength_nm} nm...")
        try:
            ret = self.shamrock.ShamrockSetWavelength(self.device_id, ctypes.c_float(wavelength_nm))
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
            ret = self.shamrock.ShamrockSetGrating(self.device_id, ctypes.c_int(grating_index))
            return ret == self.SHAMROCK_SUCCESS
        except Exception as e:
            return False

    def close(self):
        if self.is_initialized and self.shamrock:
            try:
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