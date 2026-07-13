import os
import time
import numpy as np
from threading import Lock
from PyQt5.QtCore import QThread, pyqtSignal

# Wrapped in try-except so a missing SDK doesn't raise an error when running in debug (dummy) mode
try:
    import pylablib
    from pylablib.devices import PrincetonInstruments
except ImportError:
    pylablib = None
    PrincetonInstruments = None

# Default install location for the PICam Runtime
_DEFAULT_PICAM_RUNTIME_PATH = r"C:\Program Files\Princeton Instruments\PICam\Runtime"


def _get_picam_runtime_path(config):
    # Keep using the existing "PIcam_dll_path" config key (may be renamed to "picam_runtime_path" later)
    return (config or {}).get("PIcam_dll_path", _DEFAULT_PICAM_RUNTIME_PATH)


class CameraInitError(Exception):
    """カメラ初期化に失敗した際に、GUIへ伝える理由を保持して送出する例外。"""


class CameraThreadPI(QThread):
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    init_failed = pyqtSignal(str)  # emitted when hardware initialization fails, with a human-readable reason
    temperature_ready = pyqtSignal(float)

    exposure_set_finished = pyqtSignal()
    temperature_set_finished = pyqtSignal()
    acquisition_failed = pyqtSignal(str)  # emitted when acquisition is auto-stopped after repeated errors
    hardware_error = pyqtSignal(str)  # emitted when a settings write (exposure/temperature) fails on hardware

    def __init__(self, config=None, debug=False):
        super().__init__()
        self.debug = debug
        self.config = config or {}

        self.thread_active = True
        self.is_measuring = False
        self.cam = None
        self._dll_dir_cookie = None
        self._lock = Lock()
        self._hw_lock = Lock()  # Lock for exclusive access to hardware (snap / applying settings)

        # Defaults matching a PIXIS: 100F (overwritten by get_detector_size() once a real camera is connected)
        self.det_width = 1340
        self.det_height = 100

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

    def _connect_camera(self):
        """PICamカメラを列挙・選択して接続する。失敗時は CameraInitError を送出する。"""
        if PrincetonInstruments is None:
            raise CameraInitError("pylablib is not installed; cannot access PICam cameras.")

        runtime_path = _get_picam_runtime_path(self.config)
        if hasattr(os, 'add_dll_directory'):
            try:
                self._dll_dir_cookie = os.add_dll_directory(runtime_path)
            except Exception as e:
                print(f"add_dll_directory failed for PICam runtime path '{runtime_path}': {e}")
        os.environ["PATH"] = runtime_path + os.pathsep + os.environ.get("PATH", "")
        pylablib.par["devices/dlls/picam"] = runtime_path

        try:
            cameras = PrincetonInstruments.list_cameras()
        except Exception as e:
            raise CameraInitError(f"Failed to enumerate PICam cameras: {e}")

        if not cameras:
            raise CameraInitError(
                "No PICam camera detected. Check the USB connection and PICam Runtime installation."
            )

        wanted_serial = self.config.get("camera_serial_number")
        if wanted_serial:
            target = next((c for c in cameras if c.serial_number == wanted_serial), None)
            if target is None:
                found = ", ".join(c.serial_number for c in cameras)
                raise CameraInitError(
                    f"Camera with serial number '{wanted_serial}' not found. "
                    f"Detected serial number(s): {found}"
                )
        elif len(cameras) == 1:
            target = cameras[0]
        else:
            found = ", ".join(f"{c.model}/{c.serial_number}" for c in cameras)
            raise CameraInitError(
                f"Multiple PICam cameras detected ({found}) but no 'camera_serial_number' is set "
                "in spectrometerConfig.json. Please specify which camera to use."
            )

        print(f"Connecting to PICam camera: {target.model} / {target.serial_number} / {target.interface}")
        self.cam = PrincetonInstruments.PicamCamera(serial_number=target.serial_number)

    def run(self):
        try:
            if self.debug:
                print("[DEBUG MODE] Activating dummy camera...")
                time.sleep(1.0)
                self.init_finished.emit()
            else:
                try:
                    self._connect_camera()
                    self.det_width, self.det_height = self.cam.get_detector_size()
                    print(f"Connected. Detector size: {self.det_width}x{self.det_height}")
                    self.current_exposure = self.cam.set_exposure(0.1)
                except CameraInitError as e:
                    print(f"Camera initialization failed: {e}")
                    self.init_failed.emit(str(e))
                    return
                except Exception as e:
                    print(f"Unexpected error during camera initialization: {e}")
                    self.init_failed.emit(str(e))
                    return

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
                        self.current_exposure = new_exposure
                    else:
                        try:
                            # PICam converts seconds<->milliseconds internally and returns the actual
                            # value applied after the device rounds it
                            self.current_exposure = self.cam.set_exposure(new_exposure)
                        except Exception as e:
                            print(f"Failed to set exposure: {e}")
                            self.hardware_error.emit(f"Failed to set exposure: {e}")
                    with self._lock:
                        self.new_exposure = None
                    self.exposure_set_finished.emit()

                if new_temperature is not None:
                    if self.debug:
                        self.mock_temp = new_temperature
                    else:
                        try:
                            self.cam.set_attribute_value("Sensor Temperature Set Point", float(new_temperature))
                        except Exception as e:
                            print(f"Failed to set temperature: {e}")
                            self.hardware_error.emit(f"Failed to set temperature: {e}")
                    with self._lock:
                        self.new_temperature = None
                    self.temperature_set_finished.emit()

                if request_temp:
                    if self.debug:
                        self.temperature_ready.emit(self.mock_temp + np.random.uniform(-0.5, 0.5))
                    else:
                        try:
                            temp = self.cam.get_attribute_value("Sensor Temperature Reading")
                            self.temperature_ready.emit(float(temp))
                        except Exception as e:
                            print(f"Failed to read temperature: {e}")
                            self.temperature_ready.emit(-999.0)
                    with self._lock:
                        self.request_temp = False

                if is_measuring:
                    if not was_measuring:
                        was_measuring = True

                    if settings_changed:
                        if self.debug:
                            with self._lock:
                                self.settings_changed = False
                        else:
                            try:
                                with self._hw_lock:
                                    self._apply_camera_settings()
                            except Exception as e:
                                # Do not clear settings_changed: the old ROI is still in effect on the
                                # hardware, so retry applying the same intended settings next time
                                # instead of silently measuring with stale/undefined ROI.
                                print(f"Failed to apply ROI settings; stopping acquisition: {e}")
                                with self._lock:
                                    self.is_measuring = False
                                self.acquisition_failed.emit(str(e))
                                time.sleep(0.05)
                                continue
                            # Only clear the flag once the hardware confirms the new ROI was applied.
                            with self._lock:
                                self.settings_changed = False

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
                            with self._hw_lock:
                                data = self.cam.snap(timeout=snap_timeout)
                            if data is None:
                                time.sleep(0.05)
                                continue
                            if self.roi_mode == "2d":
                                self.data_ready.emit("2d", data)
                            else:
                                self.data_ready.emit("1d", self._extract_spectrum(data))
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
            if self._dll_dir_cookie is not None:
                try:
                    self._dll_dir_cookie.close()
                except Exception:
                    pass
                self._dll_dir_cookie = None

    @staticmethod
    def _extract_spectrum(data):
        """PicamCamera.snap() が返す2次元フレームを1次元スペクトルへ正規化する。"""
        if data.ndim == 1:
            return data
        if data.ndim == 2:
            if data.shape[0] == 1:
                return data[0]
            return np.sum(data, axis=0)
        raise ValueError(f"Unexpected frame shape from camera: {data.shape}")

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
        """ROI/binningをハードウェアへ適用する。失敗時は例外をそのまま呼び出し元へ伝播させる
        (呼び出し元が古いROIのまま測定を継続しないよう、成否を判断できる必要があるため)。"""
        if self.cam is None: return
        if self.roi_mode == "2d":
            applied = self.cam.set_roi(0, self.det_width, 0, self.det_height, hbin=1, vbin=1)
        elif self.roi_mode == "1d_full":
            applied = self.cam.set_roi(0, self.det_width, 0, self.det_height, hbin=1, vbin=self.det_height)
        elif self.roi_mode == "1d_roi":
            v_size = self.roi_vend - self.roi_vstart
            if v_size <= 0:
                raise ValueError(
                    f"Invalid vertical ROI: start={self.roi_vstart}, end={self.roi_vend}"
                )
            applied = self.cam.set_roi(
                0, self.det_width, self.roi_vstart, self.roi_vend,
                hbin=1, vbin=v_size,
            )
        else:
            raise ValueError(f"Unknown ROI mode: {self.roi_mode}")
        if applied is not None:
            # set_roi() may round values to satisfy hardware constraints; log what was actually applied.
            print(f"ROI applied (hstart, hend, vstart, vend, hbin, vbin): {applied}")

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
                try:
                    with self._hw_lock:
                        self._apply_camera_settings()
                except Exception as e:
                    print(f"Failed to apply ROI settings: {e}")
                    return None
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
