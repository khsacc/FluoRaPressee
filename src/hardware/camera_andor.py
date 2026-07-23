import time
import numpy as np
from threading import Lock, Condition
from PyQt6.QtCore import QThread, pyqtSignal
from scipy.optimize import OptimizeWarning

from src.hardware.status.andor_camera_status import collect_andor_camera_status, debug_andor_camera_status
from src.hardware.pylablib_loader import import_pylablib_module

# Wrapped in try-except so a missing SDK doesn't raise an error when running in debug (dummy) mode
try:
    Andor = import_pylablib_module("pylablib.devices.Andor")
except ImportError:
    Andor = None

class CameraThreadAndor(QThread):
    """Andor カメラの制御と画像取得を行うスレッド"""
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    init_failed = pyqtSignal(str)  # emitted when hardware initialization fails, with a human-readable reason
    # (temperature_C, status) where status in {"locked", "unlocked", "drifted", "off", "unknown"}.
    # Wired to Andor SDK2's get_temperature_status() (see _read_temperature_status()). Andor
    # has no fault-equivalent status, so "faulted" is never emitted by this backend (it still
    # exists in the shared vocabulary for camera_princeton.py's PICam cooling faults).
    temperature_ready = pyqtSignal(float, str)
    # (has_temperature_control, has_status_enum, min_temp_C, max_temp_C), emitted once after
    # connecting. Andor cameras used by this app always have a cooler and always expose
    # get_temperature_status(), so the first two are unconditionally (True, True); the range
    # comes from get_temperature_range() and is used to clamp spin_cooler_temp's input range.
    temperature_capability_ready = pyqtSignal(bool, bool, float, float)
    # (model, serial_number), emitted once after connecting, so the GUI can cross-check it
    # against spectrometerConfig.json's recorded "hardware_identity.camera" (see
    # ConfigMixin.check_and_record_hardware_identity()).
    identity_ready = pyqtSignal(str, str)
    status_ready = pyqtSignal(dict)
    exposure_applied = pyqtSignal(float, bool, str)
    roi_applied = pyqtSignal(dict)

    exposure_set_finished = pyqtSignal()
    # Keep the camera-backend interface uniform. This backend does not expose
    # EM Gain through the application yet, so the GUI keeps the component hidden.
    em_gain_info_ready = pyqtSignal(bool, bool, int, int, int, int)
    em_gain_set_finished = pyqtSignal(int)
    temperature_set_finished = pyqtSignal(float)
    acquisition_failed = pyqtSignal(str)  # emitted when acquisition is auto-stopped after repeated errors, or the thread crashes while measuring
    hardware_error = pyqtSignal(str)  # emitted when a settings write (exposure/temperature) fails on hardware

    # Constants describing the camera hardware
    DEFAULT_DETECTOR_WIDTH = 1024
    DEFAULT_DETECTOR_HEIGHT = 127
    DEFAULT_TEMP = -65
    DEFAULT_FAN_MODE = "full"
    DEFAULT_EXPOSURE = 0.1
    SLEEP_INTERVAL = 0.05  # Sleep interval between iterations of the thread loop (s)
    # Fallback settable-temperature range reported in --debug mode (no real camera to query
    # get_temperature_range() from). Matches the pre-existing hardcoded spin_cooler_temp
    # range in ui.py / config_wizard.py.
    DEBUG_TEMP_MIN = -100.0
    DEBUG_TEMP_MAX = 20.0

    # Maps AndorSDK2's get_temperature_status() strings to the status vocabulary shared with
    # camera_princeton.py's on_temperature_read() consumer in acquisition_mixin.py. Andor SDK2
    # has no fault-equivalent status, so "faulted" is never produced by this map.
    _TEMP_STATUS_MAP = {
        "stabilized": "locked",
        "not_reached": "unlocked",
        "not_stabilized": "unlocked",
        "drifted": "drifted",
        "off": "off",
    }

    def __init__(self, config=None, debug=False):
        super().__init__()
        self.debug = debug
        self.config = config or {}
        self.thread_active = True
        self.is_measuring = False
        self.cam = None
        self._lock = Condition()  # also used to wait for a pending exposure to actually reach hardware
        self._hw_lock = Lock()  # Lock for exclusive access to hardware (snap / applying settings)
        self._exposure_request_seq = 0
        self._exposure_applied_seq = 0

        self.det_width = self.DEFAULT_DETECTOR_WIDTH
        self.det_height = self.DEFAULT_DETECTOR_HEIGHT

        self.roi_mode = "1d_roi"
        self.roi_vstart = 45
        self.roi_vend = 65
        self.settings_changed = True
        self._settings_request_seq = 0
        self._applied_roi = None
        
        self.request_temp = False
        self.status_requested = False
        self.new_exposure = None
        self.new_temperature = None
        
        # Simulated setting values used in debug mode
        self.mock_exposure = self.DEFAULT_EXPOSURE
        self.mock_temp = self.config.get("default_temperature", self.DEFAULT_TEMP)
        self.current_exposure = self.DEFAULT_EXPOSURE
        self._metadata_identity = {"controller_model": None, "model": None, "serial_number": None}
        self._metadata_pixel_pitch_um = {"width": None, "height": None}
        self._metadata_temperature = {
            "current_c": None,
            "setpoint_c": float(self.mock_temp),
            "status": None,
        }

        # --debug convergence simulation for temperature status (mirrors
        # camera_princeton.py's _debug_temperature_sample()); lets the GUI's
        # Locked/Drifted/... stabilisation UI be exercised without hardware.
        self._debug_sim_temp = self.mock_temp + 10.0
        self._debug_forced_temp_status = (
            str(self.config.get("debug_force_temperature_status") or "").strip().lower() or None
        )

    def run(self):
        try:
            if self.debug:
                print("[DEBUG MODE] Activating dummy camera...")
                self.det_width, self.det_height = self.DEFAULT_DETECTOR_WIDTH, self.DEFAULT_DETECTOR_HEIGHT
                self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
                self.temperature_capability_ready.emit(True, True, self.DEBUG_TEMP_MIN, self.DEBUG_TEMP_MAX)
                self.temperature_set_finished.emit(float(self.mock_temp))
                # Fabricated so --debug mode can exercise the hardware_identity check.
                self.identity_ready.emit("Andor Camera [DEBUG]", "DEBUG-0000000")
                self._metadata_identity = {
                    "controller_model": "DEBUG controller",
                    "model": "Andor Camera [DEBUG]",
                    "serial_number": "DEBUG-0000000",
                }
                self._metadata_pixel_pitch_um = {"width": 26.0, "height": 26.0}
                self.init_finished.emit()
            else:
                try:
                    if Andor is None:
                        raise RuntimeError("Andor SDK not installed. Install pylablib to use hardware camera.")
                    print("Connecting to camera and initializing cooler...")
                    self.cam = Andor.AndorSDK2Camera()
                    self.det_width, self.det_height = self.cam.get_detector_size()
                    pixel_width, pixel_height = self.cam.get_pixel_size()
                    self._metadata_pixel_pitch_um = {
                        "width": pixel_width * 1e6,
                        "height": pixel_height * 1e6,
                    }
                    print(f"Connected to Andor camera. Detector size: {self.det_width}x{self.det_height}")
                    temp_min, temp_max = self.cam.get_temperature_range()
                    target_temp = self.config.get("default_temperature", self.DEFAULT_TEMP)
                    applied_temp = min(max(target_temp, temp_min), temp_max)
                    if applied_temp != target_temp:
                        print(
                            f"Warning: configured default_temperature {target_temp}C is outside "
                            f"the camera's settable range ({temp_min}..{temp_max}C); "
                            f"clamping to {applied_temp}C"
                        )
                    self.cam.set_temperature(applied_temp)
                    self.cam.set_cooler(True)
                    self.cam.set_fan_mode(self.config.get("default_fan_mode", self.DEFAULT_FAN_MODE))
                    self.current_exposure = float(self.cam.set_exposure(0.1))
                except Exception as e:
                    print(f"Failed to initialize Andor camera: {e}")
                    self.init_failed.emit(str(e))
                    return
                self.temperature_set_finished.emit(float(applied_temp))
                self._metadata_temperature["setpoint_c"] = float(applied_temp)
                self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
                self.temperature_capability_ready.emit(True, True, float(temp_min), float(temp_max))
                try:
                    device_info = self.cam.get_device_info()
                    identity_model, identity_serial = device_info.head_model, str(device_info.serial_number)
                    self._metadata_identity = {
                        "controller_model": device_info.controller_model,
                        "model": identity_model,
                        "serial_number": identity_serial,
                    }
                except Exception as e:
                    print(f"Failed to read camera identity: {e}")
                    identity_model, identity_serial = "", ""
                self.identity_ready.emit(identity_model or "", identity_serial or "")
                self.init_finished.emit()
            
            was_measuring = False
            _consec_errors = 0

            while self.thread_active:
                with self._lock:
                    # Swap-and-clear here (not after applying) so a newer request that
                    # arrives while the old one is still being applied to hardware is
                    # not silently overwritten by an unconditional clear afterwards.
                    new_exposure, self.new_exposure = self.new_exposure, None
                    exposure_request_seq = self._exposure_request_seq
                    new_temperature, self.new_temperature = self.new_temperature, None
                    request_temp = self.request_temp
                    status_requested = self.status_requested
                    is_measuring = self.is_measuring
                    settings_changed = self.settings_changed
                    settings_request_seq = self._settings_request_seq

                if new_exposure is not None:
                    applied_exposure = self.current_exposure
                    exposure_success = False
                    exposure_error = ""
                    if self.debug:
                        self.mock_exposure = new_exposure
                        applied_exposure = float(new_exposure)
                        exposure_success = True
                        print(f"[DEBUG] Exposure set to {self.mock_exposure} s")
                    else:
                        try:
                            # Held under _hw_lock so this never races a concurrent snap()/
                            # acquire_single_image() touching self.cam.
                            with self._hw_lock:
                                applied_exposure = float(self.cam.set_exposure(new_exposure))
                            exposure_success = True
                            print(f"Exposure set to {applied_exposure} s")
                        except Exception as e:
                            exposure_error = str(e)
                            print(f"Failed to set exposure: {e}")
                            self.hardware_error.emit(f"Failed to set exposure: {e}")
                    if exposure_success:
                        self.current_exposure = applied_exposure
                    self.exposure_applied.emit(
                        float(self.current_exposure), exposure_success, exposure_error
                    )
                    self.exposure_set_finished.emit()
                    # Wake anyone blocked in wait_for_exposure_applied() (e.g. acquire_single_image())
                    # now that self.current_exposure reflects this request (applied or not - failure
                    # still resolves the wait rather than hanging it).
                    with self._lock:
                        self._exposure_applied_seq = exposure_request_seq
                        self._lock.notify_all()

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
                    self._metadata_temperature["setpoint_c"] = float(new_temperature)

                if request_temp:
                    if self.debug:
                        temp, status = self._debug_temperature_sample()
                        self._metadata_temperature.update(current_c=float(temp), status=status)
                        self.temperature_ready.emit(temp, status)
                    else:
                        try:
                            if self.cam is None:
                                print("Warning: Camera not initialized, returning default temp")
                                self.temperature_ready.emit(self.DEFAULT_TEMP, "unknown")
                            else:
                                temp = self.cam.get_temperature()
                                status = self._read_temperature_status()
                                self._metadata_temperature.update(current_c=float(temp), status=status)
                                self.temperature_ready.emit(temp, status)
                        except Exception as e:
                            print(f"Error reading temperature: {e}")
                            self.temperature_ready.emit(-999.0, "unknown")
                    with self._lock:
                        self.request_temp = False

                if status_requested:
                    if self.debug:
                        snapshot = debug_andor_camera_status(
                            self.det_width, self.det_height, self.mock_exposure, self.mock_temp
                        )
                    else:
                        try:
                            with self._hw_lock:
                                snapshot = collect_andor_camera_status(self.cam)
                        except Exception as e:
                            print(f"Failed to query Andor camera status: {e}")
                            snapshot = {
                                "backend": "andor_sdk2",
                                "available": False,
                                "error": str(e),
                                "sections": {},
                            }
                    self.status_ready.emit(snapshot)
                    with self._lock:
                        self.status_requested = False

                if is_measuring:
                    if not was_measuring:
                        was_measuring = True

                    if settings_changed:
                        try:
                            if self.debug:
                                self._apply_debug_camera_settings()
                            else:
                                with self._hw_lock:
                                    self._apply_camera_settings()
                        except Exception as e:
                            print(f"Failed to apply Andor ROI/read mode: {e}")
                            with self._lock:
                                self.is_measuring = False
                            self.acquisition_failed.emit(str(e))
                            time.sleep(self.SLEEP_INTERVAL)
                            continue
                        with self._lock:
                            if self._settings_request_seq == settings_request_seq:
                                self.settings_changed = False

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
            # Without this, an exception escaping the loop above (uncaught by any of the
            # per-section try/except blocks) would kill the thread silently: the GUI never
            # learns about it and stays stuck showing "measuring" indefinitely.
            with self._lock:
                crashed_while_measuring, self.is_measuring = self.is_measuring, False
            if crashed_while_measuring:
                self.acquisition_failed.emit(str(e))
        finally:
            if self.cam is not None:
                self.cam.close()
                self.cam = None

    def read_temperature(self) -> None:
        """温度読み込みをリクエスト（スレッドセーフ）"""
        with self._lock:
            self.request_temp = True

    def request_status(self) -> None:
        """Request a read-only status snapshot from the camera thread."""
        with self._lock:
            self.status_requested = True

    def get_cached_hardware_metadata(self):
        """Return acquisition metadata without touching the camera SDK."""
        with self._lock:
            metadata = {
                "identity": dict(self._metadata_identity),
                "detector_size_px": {"width": self.det_width, "height": self.det_height},
                "pixel_pitch_um": dict(self._metadata_pixel_pitch_um),
                "exposure_s": float(self.current_exposure),
                "temperature": dict(self._metadata_temperature),
            }
            if self._applied_roi is not None:
                applied = dict(self._applied_roi)
                metadata.update({
                    "roi": {
                        "mode": applied["mode"],
                        "horizontal_start": applied["horizontal_start"],
                        "horizontal_end": applied["horizontal_end"],
                        "vertical_start": applied["vertical_start"],
                        "vertical_end": applied["vertical_end"],
                    },
                    "binning": {
                        "horizontal": applied["horizontal_binning"],
                        "vertical": applied["vertical_binning"],
                    },
                    "read_mode": applied["read_mode"],
                    "output_rows": applied["output_rows"],
                    "software_vertical_sum": applied["software_vertical_sum"],
                })
            return metadata

    def _read_temperature_status(self) -> str:
        """Read and normalize AndorSDK2's get_temperature_status() via _TEMP_STATUS_MAP."""
        try:
            raw = self.cam.get_temperature_status()
            return self._TEMP_STATUS_MAP.get(str(raw).strip().lower(), "unknown")
        except Exception as e:
            print(f"Failed to read temperature status: {e}")
            return "unknown"

    def _debug_temperature_sample(self):
        """Simulate temperature convergence and locked/unlocked status for --debug mode
        (mirrors camera_princeton.py's _debug_temperature_sample()), so the GUI's
        stabilisation UI can be exercised without hardware. `debug_force_temperature_status`
        in spectrometerConfig.json (e.g. "drifted") pins the status for manual verification
        of that path.
        """
        diff = self.mock_temp - self._debug_sim_temp
        self._debug_sim_temp += diff * 0.3 + np.random.uniform(-0.15, 0.15)
        if self._debug_forced_temp_status in ("locked", "unlocked", "drifted", "off"):
            status = self._debug_forced_temp_status
        else:
            status = "locked" if abs(self._debug_sim_temp - self.mock_temp) < 0.3 else "unlocked"
        return self._debug_sim_temp, status

    def update_exposure(self, exp_time: float) -> int:
        """露光時間を更新（スレッドセーフ）。この要求を識別するトークンを返す
        （wait_for_exposure_applied()に渡すとハードウェアへ反映されるまでブロックできる）。"""
        with self._lock:
            self.new_exposure = exp_time
            self._exposure_request_seq += 1
            return self._exposure_request_seq

    def wait_for_exposure_applied(self, seq: int, timeout: float = None) -> bool:
        """update_exposure()が返したトークンで指定した要求をrun()が処理し終える
        （成功・失敗いずれの場合も含む）か、timeout秒経過するまでブロックする。
        適用されればTrue、タイムアウトすればFalseを返す。"""
        with self._lock:
            return self._lock.wait_for(lambda: self._exposure_applied_seq >= seq, timeout=timeout)

    def update_temperature(self, temp: float) -> None:
        """目標温度を更新（スレッドセーフ）"""
        with self._lock:
            self.new_temperature = temp

    def _apply_camera_settings(self) -> dict:
        """Apply and record the actual Andor read mode/ROI (hardware lock required)."""
        if self.cam is None:
            raise RuntimeError("Andor camera is not initialized")
        if self.roi_mode == "2d":
            applied = self._set_exact_image_roi(0, self.det_height, 1)
            return self._record_applied_roi("image", applied)
        elif self.roi_mode == "1d_full":
            try:
                read_mode = self.cam.set_read_mode("fvb")
                if read_mode is None:
                    raise RuntimeError("FVB read mode is not supported")
                applied = (0, self.det_width, 0, self.det_height, 1, self.det_height)
                return self._record_applied_roi("fvb", applied)
            except Exception as fvb_error:
                print(f"FVB unavailable; using exact image-mode summation: {fvb_error}")
                vbin = self._largest_exact_vertical_binning(self.det_height)
                applied = self._set_exact_image_roi(0, self.det_height, vbin)
                return self._record_applied_roi("image", applied)
        elif self.roi_mode == "1d_roi":
            v_size = self.roi_vend - self.roi_vstart
            if not (0 <= self.roi_vstart < self.roi_vend <= self.det_height):
                raise ValueError(
                    f"Invalid vertical ROI [{self.roi_vstart}, {self.roi_vend}) "
                    f"for detector height {self.det_height}"
                )
            vbin = self._largest_exact_vertical_binning(v_size)
            applied = self._set_exact_image_roi(self.roi_vstart, self.roi_vend, vbin)
            return self._record_applied_roi("image", applied)
        raise ValueError(f"Unknown Andor ROI mode: {self.roi_mode}")

    def _set_exact_image_roi(self, vstart: int, vend: int, vbin: int):
        applied = self.cam.set_roi(
            0, self.det_width, vstart, vend, hbin=1, vbin=vbin
        )
        if applied is None:
            raise RuntimeError("Andor SDK did not return an applied ROI")
        if tuple(applied[:4]) != (0, self.det_width, vstart, vend) and vbin != 1:
            applied = self.cam.set_roi(
                0, self.det_width, vstart, vend, hbin=1, vbin=1
            )
        if tuple(applied[:4]) != (0, self.det_width, vstart, vend):
            print(
                "Andor SDK adjusted ROI: "
                f"requested={(0, self.det_width, vstart, vend)}, applied={tuple(applied[:4])}"
            )
        return tuple(int(value) for value in applied)

    def _largest_exact_vertical_binning(self, height: int) -> int:
        try:
            _, vertical_limits = self.cam.get_roi_limits(hbin=1, vbin=1)
            max_binning = int(vertical_limits.maxbin)
        except Exception:
            max_binning = 1
        for candidate in range(min(height, max_binning), 0, -1):
            if height % candidate == 0:
                return candidate
        return 1

    def _record_applied_roi(self, read_mode: str, applied) -> dict:
        hstart, hend, vstart, vend, hbin, vbin = applied
        output_rows = 1 if read_mode == "fvb" else (vend - vstart) // vbin
        snapshot = {
            "mode": self.roi_mode,
            "read_mode": read_mode,
            "horizontal_start": hstart,
            "horizontal_end": hend,
            "vertical_start": vstart,
            "vertical_end": vend,
            "horizontal_binning": hbin,
            "vertical_binning": vbin,
            "output_rows": output_rows,
            "software_vertical_sum": self.roi_mode != "2d" and output_rows > 1,
        }
        with self._lock:
            self._applied_roi = dict(snapshot)
        self.roi_applied.emit(dict(snapshot))
        return snapshot

    def _apply_debug_camera_settings(self):
        if self.roi_mode == "2d":
            applied = (0, self.det_width, 0, self.det_height, 1, 1)
            read_mode = "image"
        elif self.roi_mode == "1d_full":
            applied = (0, self.det_width, 0, self.det_height, 1, self.det_height)
            read_mode = "fvb"
        elif self.roi_mode == "1d_roi":
            if not (0 <= self.roi_vstart < self.roi_vend <= self.det_height):
                raise ValueError(
                    f"Invalid vertical ROI [{self.roi_vstart}, {self.roi_vend}) "
                    f"for detector height {self.det_height}"
                )
            applied = (
                0, self.det_width, self.roi_vstart, self.roi_vend,
                1, self.roi_vend - self.roi_vstart,
            )
            read_mode = "image"
        else:
            raise ValueError(f"Unknown Andor ROI mode: {self.roi_mode}")
        return self._record_applied_roi(read_mode, applied)

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
            self._settings_request_seq += 1
    
    @property
    def camera(self):
        """calibration_ui から self.camera_thread.camera.acquire_single_image() と呼ばれるためのプロキシ"""
        return self

    def acquire_single_image(self, acq_time: float = None) -> np.ndarray:
        """Calibration UI等のために、スレッドをブロックして1枚だけ同期的に撮影する（疑似処理）"""
        if acq_time is not None:
            # run()が連続測定中の長い露光でsnap()にブロックされている間はrun()側のループが
            # 露光要求を拾えないため、固定sleep(0.1)ではなく実際に適用されるまで待つ。
            # タイムアウトは変更前の露光時間(その分run()がブロックされ得る)に余裕を足した値。
            wait_timeout = self.current_exposure + 15
            seq = self.update_exposure(acq_time)
            if not self.wait_for_exposure_applied(seq, timeout=wait_timeout):
                print(
                    "Warning: timed out waiting for the new exposure to reach hardware; "
                    "proceeding with acquisition anyway"
                )

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

            with self._lock:
                settings_changed = self.settings_changed
                settings_request_seq = self._settings_request_seq
            if settings_changed:
                try:
                    with self._hw_lock:
                        self._apply_camera_settings()
                    with self._lock:
                        if self._settings_request_seq == settings_request_seq:
                            self.settings_changed = False
                except Exception as e:
                    print(f"Failed to apply Andor ROI/read mode: {e}")
                    self.hardware_error.emit(f"Failed to apply ROI/read mode: {e}")
                    return None

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
