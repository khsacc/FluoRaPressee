import time
import numpy as np
from threading import Lock
from PyQt5.QtCore import QThread, pyqtSignal
from scipy.optimize import OptimizeWarning

# ダミーモード時はエラーを回避するためtry-exceptで囲む
try:
    from pylablib.devices import Andor
except ImportError:
    Andor = None

class CameraThreadAndor(QThread):
    """Andor カメラの制御と画像取得を行うスレッド"""
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    temperature_ready = pyqtSignal(float)
    
    exposure_set_finished = pyqtSignal()
    temperature_set_finished = pyqtSignal()

    # カメラ仕様の定数
    DEFAULT_DETECTOR_WIDTH = 1024
    DEFAULT_DETECTOR_HEIGHT = 127
    DEFAULT_TEMP = -65
    DEFAULT_EXPOSURE = 0.1
    TEMP_TOLERANCE = 0.5  # デバッグモード時の温度ゆらぎ(C)
    SLEEP_INTERVAL = 0.05  # スレッドループの休止間隔(s)
    
    def __init__(self, debug=False):
        super().__init__()
        self.debug = debug
        self.thread_active = True
        self.is_measuring = False
        self.cam = None
        self._lock = Lock()  # スレッド安全性のためのロック
        
        self.det_width = self.DEFAULT_DETECTOR_WIDTH
        self.det_height = self.DEFAULT_DETECTOR_HEIGHT

        self.roi_mode = "1d_roi"
        self.roi_vstart = 45
        self.roi_vend = 65
        self.settings_changed = True
        
        self.request_temp = False
        self.new_exposure = None
        self.new_temperature = None
        
        # デバッグ用の仮想設定値
        self.mock_exposure = self.DEFAULT_EXPOSURE
        self.mock_temp = self.DEFAULT_TEMP

    def run(self):
        try:
            if self.debug:
                print("[DEBUG MODE] Activating dummy camera...")
                self.det_width, self.det_height = self.DEFAULT_DETECTOR_WIDTH, self.DEFAULT_DETECTOR_HEIGHT
                self.init_finished.emit()
            else:
                if Andor is None:
                    raise RuntimeError("Andor SDK not installed. Install pylablib to use hardware camera.")
                print("Connecting to camera and initializing cooler...")
                try:
                    self.cam = Andor.AndorSDK2Camera()
                    self.det_width, self.det_height = self.cam.get_detector_size()
                except Exception as e:
                    print(f"Failed to initialize Andor camera: {e}")
                    raise
                self.det_width, self.det_height = self.cam.get_detector_size()
                print(f"Connected to Andor camera. Detector size: {self.det_width}x{self.det_height}")
                self.cam.set_temperature(-65)
                self.cam.set_cooler(True)
                self.cam.set_exposure(0.1) 
                self.init_finished.emit()
            
            was_measuring = False
            
            while self.thread_active:
                if self.new_exposure is not None:
                    if self.debug:
                        self.mock_exposure = self.new_exposure
                        print(f"[DEBUG] Exposure set to {self.mock_exposure} s")
                    else:
                        try:
                            self.cam.set_exposure(self.new_exposure)
                            print(f"Exposure set to {self.new_exposure} s")
                        except Exception as e:
                            print(f"Failed to set exposure: {e}")
                    self.new_exposure = None
                    self.exposure_set_finished.emit()

                if self.new_temperature is not None:
                    if self.debug:
                        self.mock_temp = self.new_temperature
                        print(f"[DEBUG] Target temperature set to {self.mock_temp} C")
                    else:
                        try:
                            self.cam.set_temperature(self.new_temperature)
                            print(f"Target temperature set to {self.new_temperature} C")
                        except Exception as e:
                            print(f"Failed to set temperature: {e}")
                    self.new_temperature = None
                    self.temperature_set_finished.emit()

                if self.request_temp:
                    if self.debug:
                        # デバッグ時は指定温度にゆらぎを持たせて返す
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
                    self.request_temp = False

                if self.is_measuring:
                    if not was_measuring:
                        was_measuring = True

                    if self.settings_changed:
                        if not self.debug:
                            self._apply_camera_settings()
                        self.settings_changed = False

                    if self.debug:
                        # === デバッグ用ダミーデータ生成 ===
                        x = np.arange(self.det_width)
                        # ルビーのR1, R2線を模したダブルピーク + 背景ノイズ
                        y1 = 500 * np.exp(-((x - 700)**2) / (2 * 4**2))
                        y2 = 250 * np.exp(-((x - 675)**2) / (2 * 4**2))
                        base = 100 + np.random.normal(0, 10, self.det_width)
                        spectrum = y1 + y2 + base
                        
                        if self.roi_mode == "2d":
                            data = np.tile(spectrum, (self.det_height, 1))
                            self.data_ready.emit("2d", data)
                        else:
                            self.data_ready.emit("1d", spectrum)
                            
                        time.sleep(self.mock_exposure) # 露光時間分待機
                    else:
                        data = self.cam.snap()
                        if self.roi_mode == "2d":
                            self.data_ready.emit("2d", data)
                        else:
                            if data.ndim == 2:
                                spectrum = np.sum(data, axis=0)
                            else:
                                spectrum = data
                            self.data_ready.emit("1d", spectrum)
                else:
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
    
    def get_temperature(self) -> float:
        """現在の目標温度（または最後に取得した温度）を返す"""
        with self._lock:
            return self.mock_temp if self.debug else (self.new_temperature if self.new_temperature is not None else -60.0)

    @property
    def camera(self):
        """calibration_ui から self.camera_thread.camera.acquire_single_image() と呼ばれるためのプロキシ"""
        return self

    def acquire_single_image(self, acq_time: float = None) -> np.ndarray:
        """Calibration UI等のために、スレッドをブロックして1枚だけ同期的に撮影する（疑似処理）"""
        if acq_time is not None:
            self.update_exposure(acq_time)
            time.sleep(0.1) # 露光設定の反映待ち

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
                data = self.cam.snap()
                return data
            except Exception as e:
                print(f"Failed to acquire single image: {e}")
                return None

    def start_measuring(self):
        self.is_measuring = True

    def stop_measuring(self):
        self.is_measuring = False

    def stop_thread(self):
        self.thread_active = False
        self.wait()