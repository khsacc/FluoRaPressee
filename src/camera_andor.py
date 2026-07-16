import time
import numpy as np
from threading import Lock
from PyQt5.QtCore import QThread, pyqtSignal
from scipy.optimize import OptimizeWarning

# Wrapped in try-except so a missing SDK doesn't raise an error when running in debug (dummy) mode
try:
    from pylablib.devices import Andor
except ImportError:
    Andor = None

class CameraThreadAndor(QThread):
    """Andor カメラの制御と画像取得を行うスレッド"""
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    init_failed = pyqtSignal(str)  # emitted when hardware initialization fails, with a human-readable reason
    temperature_ready = pyqtSignal(float)

    exposure_set_finished = pyqtSignal()
    # Keep the camera-backend interface uniform. This backend does not expose
    # EM Gain through the application yet, so the GUI keeps the component hidden.
    em_gain_info_ready = pyqtSignal(bool, bool, int, int, int, int)
    em_gain_set_finished = pyqtSignal(int)
    temperature_set_finished = pyqtSignal(float)
    acquisition_failed = pyqtSignal(str)  # emitted when acquisition is auto-stopped after repeated errors
    hardware_error = pyqtSignal(str)  # emitted when a settings write (exposure/temperature) fails on hardware

    # Constants describing the camera hardware
    DEFAULT_DETECTOR_WIDTH = 1024
    DEFAULT_DETECTOR_HEIGHT = 127
    DEFAULT_TEMP = -65
    DEFAULT_EXPOSURE = 0.1
    TEMP_TOLERANCE = 0.5  # Simulated temperature fluctuation in debug mode (C)
    SLEEP_INTERVAL = 0.05  # Sleep interval between iterations of the thread loop (s)
    
    def __init__(self, config=None, debug=False):
        super().__init__()
        self.debug = debug
        self.config = config or {}
        self.thread_active = True
        self.is_measuring = False
        self.cam = None
        self._lock = Lock()  # Lock guarding thread-safe access to shared state
        self._hw_lock = Lock()  # Lock for exclusive access to hardware (snap / applying settings)

        self.det_width = self.DEFAULT_DETECTOR_WIDTH
        self.det_height = self.DEFAULT_DETECTOR_HEIGHT

        self.roi_mode = "1d_roi"
        self.roi_vstart = 45
        self.roi_vend = 65
        self.settings_changed = True
        
        self.request_temp = False
        self.new_exposure = None
        self.new_temperature = None
        
        # Simulated setting values used in debug mode
        self.mock_exposure = self.DEFAULT_EXPOSURE
        self.mock_temp = self.config.get("default_temperature", self.DEFAULT_TEMP)
        self.current_exposure = self.DEFAULT_EXPOSURE

    def run(self):
        try:
            if self.debug:
                print("[DEBUG MODE] Activating dummy camera...")
                self.det_width, self.det_height = self.DEFAULT_DETECTOR_WIDTH, self.DEFAULT_DETECTOR_HEIGHT
                self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
                self.init_finished.emit()
            else:
                try:
                    if Andor is None:
                        raise RuntimeError("Andor SDK not installed. Install pylablib to use hardware camera.")
                    print("Connecting to camera and initializing cooler...")
                    self.cam = Andor.AndorSDK2Camera()
                    self.det_width, self.det_height = self.cam.get_detector_size()
                    print(f"Connected to Andor camera. Detector size: {self.det_width}x{self.det_height}")
                    target_temp = self.config.get("default_temperature", self.DEFAULT_TEMP)
                    self.cam.set_temperature(target_temp)
                    self.cam.set_cooler(True)
                    self.cam.set_exposure(0.1)
                except Exception as e:
                    print(f"Failed to initialize Andor camera: {e}")
                    self.init_failed.emit(str(e))
                    return
                self.temperature_set_finished.emit(float(target_temp))
                self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
                self.init_finished.emit()
            
            was_measuring = False
            _consec_errors = 0

            while self.thread_active:
                with self._lock:
                    # Swap-and-clear here (not after applying) so a newer request that
                    # arrives while the old one is still being applied to hardware is
                    # not silently overwritten by an unconditional clear afterwards.
                    new_exposure, self.new_exposure = self.new_exposure, None
                    new_temperature, self.new_temperature = self.new_temperature, None
                    request_temp = self.request_temp
                    is_measuring = self.is_measuring
                    settings_changed = self.settings_changed

                if new_exposure is not None:
                    if self.debug:
                        self.mock_exposure = new_exposure
                        print(f"[DEBUG] Exposure set to {self.mock_exposure} s")
                    else:
                        try:
                            self.cam.set_exposure(new_exposure)
                            print(f"Exposure set to {new_exposure} s")
                        except Exception as e:
                            print(f"Failed to set exposure: {e}")
                            self.hardware_error.emit(f"Failed to set exposure: {e}")
                    self.current_exposure = new_exposure
                    self.exposure_set_finished.emit()

                if new_temperature is not None:
                    if self.debug:
                        self.mock_temp = new_temperature
                        print(f"[DEBUG] Target temperature set to {self.mock_temp} C")
                    else:
                        try:
                            self.cam.set_temperature(new_temperature)
                            print(f"Target temperature set to {new_temperature} C")
                        except Exception as e:
                            print(f"Failed to set temperature: {e}")
                            self.hardware_error.emit(f"Failed to set temperature: {e}")
                    self.temperature_set_finished.emit(float(new_temperature))

                if request_temp:
                    if self.debug:
                        self.temperature_ready.emit(self.mock_temp + np.random.uniform(-self.TEMP_TOLERANCE, self.TEMP_TOLERANCE))
                    else:
                        try:
                            if self.cam is None:
                                print("Warning: Camera not initialized, returning default temp")
                                self.temperature_ready.emit(self.DEFAULT_TEMP)
                            else:
                                temp = self.cam.get_temperature()
                                self.temperature_ready.emit(temp)
                        except Exception as e:
                            print(f"Error reading temperature: {e}")
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
                            with self._hw_lock:
                                self._apply_camera_settings()

                    try:
                        if self.debug:
                            # === Generate dummy data for debug mode ===
                            x = np.arange(self.det_width)
                            # Double peak mimicking the ruby R1/R2 lines, plus background noise
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
                            with self._hw_lock:
                                data = self.cam.snap(timeout=snap_timeout)
                            if data is None:
                                time.sleep(self.SLEEP_INTERVAL)
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
                        time.sleep(self.SLEEP_INTERVAL)
                else:
                    _consec_errors = 0
                    was_measuring = False
                    time.sleep(self.SLEEP_INTERVAL)
                
        except Exception as e:
            print(f"An error occurred in the camera thread: {e}")
        finally:
            if self.cam is not None:
                self.cam.close()
                self.cam = None

    def read_temperature(self) -> None:
        """温度読み込みをリクエスト（スレッドセーフ）"""
        with self._lock:
            self.request_temp = True

    def update_exposure(self, exp_time: float) -> None:
        """露光時間を更新（スレッドセーフ）"""
        with self._lock:
            self.new_exposure = exp_time

    def update_temperature(self, temp: float) -> None:
        """目標温度を更新（スレッドセーフ）"""
        with self._lock:
            self.new_temperature = temp

    def _apply_camera_settings(self) -> None:
        """カメラ設定を適用（ロック必須）"""
        if self.cam is None: return
        if self.roi_mode == "2d":
            self.cam.set_roi(0, self.det_width, 0, self.det_height, hbin=1, vbin=1)
        elif self.roi_mode == "1d_full":
            self.cam.set_roi(0, self.det_width, 0, self.det_height, hbin=1, vbin=self.det_height)
        elif self.roi_mode == "1d_roi":
            v_size = self.roi_vend - self.roi_vstart
            if v_size > 0:
                self.cam.set_roi(0, self.det_width, self.roi_vstart, self.roi_vend, hbin=1, vbin=v_size)

    def update_roi_settings(self, mode: str, vstart: int = 0, vend: int = 256) -> None:
        """ROI設定を更新（スレッドセーフ）
        
        Args:
            mode: ROIモード ("1d_roi", "1d_full", "2d")
            vstart: 開始ピクセル
            vend: 終了ピクセル
        """
        with self._lock:
            self.roi_mode = mode
            self.roi_vstart = vstart
            self.roi_vend = vend
            self.settings_changed = True
    
    @property
    def camera(self):
        """calibration_ui から self.camera_thread.camera.acquire_single_image() と呼ばれるためのプロキシ"""
        return self

    def acquire_single_image(self, acq_time: float = None) -> np.ndarray:
        """Calibration UI等のために、スレッドをブロックして1枚だけ同期的に撮影する（疑似処理）"""
        if acq_time is not None:
            self.update_exposure(acq_time)
            time.sleep(0.1) # Wait for the new exposure setting to take effect

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
                with self._hw_lock:
                    self._apply_camera_settings()
                self.settings_changed = False

            try:
                snap_timeout = self.current_exposure + 10
                with self._hw_lock:
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
