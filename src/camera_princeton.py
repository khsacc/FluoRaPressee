import os
import sys
import time
import json
import numpy as np
from threading import Lock
from PyQt5.QtCore import QThread, pyqtSignal

def _get_pvcam_dll_path():
    """PVCamのDLLパスを取得する。

    spectrometerConfig.json に "pvcam_dll_path" キーがあればそれを使う。
    無ければ従来通り System32 (32bit環境での標準的な配置場所) をデフォルトとする。
    """
    default_path = "C:\\Windows\\System32"
    config_path = "spectrometerConfig.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return config.get("pvcam_dll_path", default_path)
        except Exception as e:
            print(f"Failed to read config file: {e}. Using default PVCam DLL path.")
    return default_path

# PVCamのDLLパス (独自の場所にある場合は spectrometerConfig.json の "pvcam_dll_path" で上書き可能)
dll_path = _get_pvcam_dll_path()

if hasattr(os, 'add_dll_directory'):
    try:
        os.add_dll_directory(dll_path)
    except Exception as e:
        print("add_dll_directory failed", e)

os.environ["PATH"] = dll_path + os.pathsep + os.environ.get("PATH", "")

try:
    import pylablib
    # PVCam用のモジュールをインポート
    from pylablib.devices import PrincetonInstruments
    print("PVCam cameras:", PrincetonInstruments.list_cameras_pvcam())
    # pylablibの内部パス設定をPVCam用に変更
    pylablib.par["devices/dlls/pvcam"] = dll_path  
         
except Exception as e:
    print(f"Error during loading pylablib PVCam: {repr(e)}")
    PrincetonInstruments = None

class CameraThreadPI(QThread):
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    temperature_ready = pyqtSignal(float)

    exposure_set_finished = pyqtSignal()
    temperature_set_finished = pyqtSignal()
    acquisition_failed = pyqtSignal(str)  # emitted when acquisition is auto-stopped after repeated errors

    def __init__(self, config=None, debug=False):
        super().__init__()
        self.debug = debug
        self.config = config or {}

        self.thread_active = True
        self.is_measuring = False
        self.cam = None
        self._lock = Lock()
        
        self.det_width = 1024 
        self.det_height = 1024 

        self.roi_mode = "1d_roi"
        self.roi_vstart = 45
        self.roi_vend = 65
        self.settings_changed = True
        
        self.request_temp = False
        self.new_exposure = None
        self.new_temperature = None
        
        self.mock_exposure = 0.1
        self.mock_temp = -70
        self.current_exposure = 0.1

    def run(self):
        try:
            if self.debug or PrincetonInstruments is None:
                print("[DEBUG MODE] Activating dummy camera...")
                time.sleep(1.0)
                self.init_finished.emit()
            else:      
                print("Connecting to PVCam (Princeton Instruments)...")
                # PicamCamera ではなく PVCamCamera を使用
                self.cam = PrincetonInstruments.PVCamCamera()

                # 検知器サイズの取得
                self.det_width, self.det_height = self.cam.get_detector_size()
                print(f"Connected. Detector size: {self.det_width}x{self.det_height}")
                
                # 初期設定
                self.cam.set_exposure(0.1)
                try:
                    # PVCamでの温度設定パラメータ名は通常 "setpoint"
                    self.cam.set_attribute_value("setpoint", -7000) # PVCamは0.01度単位の整数値が必要な場合があります
                except Exception as e:
                    print(f"Notice: Could not set default temperature. {e}")

                self.init_finished.emit()
            
            was_measuring = False
            _consec_errors = 0

            while self.thread_active:
                with self._lock:
                    new_exposure = self.new_exposure
                    new_temperature = self.new_temperature
                    request_temp = self.request_temp
                    is_measuring = self.is_measuring
                    settings_changed = self.settings_changed

                if new_exposure is not None:
                    if self.debug:
                        self.mock_exposure = new_exposure
                    else:
                        try:
                            self.cam.set_exposure(new_exposure)
                        except Exception as e:
                            print(f"Failed to set exposure: {e}")
                    self.current_exposure = new_exposure
                    with self._lock:
                        self.new_exposure = None
                    self.exposure_set_finished.emit()

                if new_temperature is not None:
                    if self.debug:
                        self.mock_temp = new_temperature
                    else:
                        try:
                            # PVCamの仕様に合わせ、必要に応じて値を100倍（-70.0 -> -7000）にします
                            self.cam.set_attribute_value("setpoint", int(float(new_temperature) * 100))
                        except Exception as e:
                            print(f"Failed to set temperature: {e}")
                    with self._lock:
                        self.new_temperature = None
                    self.temperature_set_finished.emit()

                if request_temp:
                    if self.debug:
                        self.temperature_ready.emit(self.mock_temp + np.random.uniform(-0.5, 0.5))
                    else:
                        try:
                            # PVCamでの現在の温度取得 (cur_tempは通常0.01度単位)
                            temp_raw = self.cam.get_attribute_value("cur_temp")
                            self.temperature_ready.emit(temp_raw / 100.0)
                        except Exception as e:
                            print(f"Failed to read temperature: {e}")
                            self.temperature_ready.emit(-999.0)
                    with self._lock:
                        self.request_temp = False

                if is_measuring:
                    if not was_measuring:
                        was_measuring = True

                    if settings_changed:
                        # Clear flag before applying so a new update arriving during
                        # _apply_camera_settings() is not silently dropped.
                        with self._lock:
                            self.settings_changed = False
                        if not self.debug:
                            self._apply_camera_settings()

                    try:
                        if self.debug:
                            x = np.arange(self.det_width)
                            y1 = 500 * np.exp(-((x - 700)**2) / (2 * 4**2))
                            y2 = 250 * np.exp(-((x - 675)**2) / (2 * 4**2))
                            base = 100 + np.random.normal(0, 10, self.det_width)
                            spectrum = y1 + y2 + base

                            if self.roi_mode == "2d":
                                data = np.tile(spectrum, (self.det_height, 1))
                                self.data_ready.emit("2d", data)
                            else:
                                self.data_ready.emit("1d", spectrum)
                            time.sleep(self.mock_exposure)
                        else:
                            snap_timeout = self.current_exposure + 10
                            data = self.cam.snap(timeout=snap_timeout)
                            if data is None:
                                time.sleep(0.05)
                                continue
                            if self.roi_mode == "2d":
                                self.data_ready.emit("2d", data)
                            else:
                                if data.ndim == 2:
                                    spectrum = np.sum(data, axis=0)
                                else:
                                    spectrum = data
                                self.data_ready.emit("1d", spectrum)
                        _consec_errors = 0
                    except Exception as e:
                        print(f"Failed to acquire camera data: {e}")
                        _consec_errors += 1
                        if _consec_errors >= 5:
                            print("Stopping acquisition after 5 consecutive camera errors.")
                            with self._lock:
                                self.is_measuring = False
                            self.acquisition_failed.emit(str(e))
                            _consec_errors = 0
                        time.sleep(0.05)
                else:
                    _consec_errors = 0
                    was_measuring = False
                    time.sleep(0.05)
                
        except Exception as e:
            print(f"An error occurred in the camera thread: {e}")
        finally:
            if self.cam is not None:
                self.cam.close()
                self.cam = None

    def read_temperature(self):
        with self._lock:
            self.request_temp = True

    def update_exposure(self, exp_time):
        with self._lock:
            self.new_exposure = exp_time

    def update_temperature(self, temp):
        with self._lock:
            self.new_temperature = temp

    def _apply_camera_settings(self):
        if self.cam is None: return
        try:
            if self.roi_mode == "2d":
                self.cam.set_roi(0, self.det_width, 0, self.det_height, hbin=1, vbin=1)
            elif self.roi_mode == "1d_full":
                self.cam.set_roi(0, self.det_width, 0, self.det_height, hbin=1, vbin=self.det_height)
            elif self.roi_mode == "1d_roi":
                v_size = self.roi_vend - self.roi_vstart
                if v_size > 0:
                    # PVCamでも同様の引数(hstart, hend, vstart, vend, hbin, vbin)が使えます
                    self.cam.set_roi(0, self.det_width, self.roi_vstart, self.roi_vend, hbin=1, vbin=v_size)
        except Exception as e:
            print(f"Failed to apply ROI settings: {e}")

    def update_roi_settings(self, mode, vstart=0, vend=256):
        with self._lock:
            self.roi_mode = mode
            self.roi_vstart = vstart
            self.roi_vend = vend
            self.settings_changed = True
    
    @property
    def camera(self):
        return self

    def acquire_single_image(self, acq_time=None):
        if acq_time is not None:
            self.update_exposure(acq_time)
            time.sleep(0.1)

        if self.debug:
            x = np.arange(self.det_width)
            y1 = 500 * np.exp(-((x - 700)**2) / (2 * 4**2))
            y2 = 250 * np.exp(-((x - 675)**2) / (2 * 4**2))
            base = 100 + np.random.normal(0, 10, self.det_width)
            spectrum = y1 + y2 + base
            
            if self.roi_mode == "2d":
                return np.tile(spectrum, (self.det_height, 1))
            else:
                return spectrum
        else:
            if self.cam is None: return None
            
            if self.settings_changed:
                self._apply_camera_settings()
                self.settings_changed = False

            try:
                snap_timeout = self.current_exposure + 10
                data = self.cam.snap(timeout=snap_timeout)
                return data
            except Exception as e:
                print(f"Failed to acquire single image: {e}")
                return None

    def start_measuring(self):
        with self._lock:
            self.is_measuring = True

    def stop_measuring(self):
        with self._lock:
            self.is_measuring = False

    def stop_thread(self):
        self.thread_active = False
        self.wait()