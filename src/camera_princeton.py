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
    # exists, currently_available, minimum, maximum, increment, current
    em_gain_info_ready = pyqtSignal(bool, bool, int, int, int, int)
    em_gain_set_finished = pyqtSignal(int)
    temperature_set_finished = pyqtSignal(float)
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
        self.new_em_gain = None
        self.new_temperature = None

        self.mock_exposure = 0.1
        self.mock_em_gain = 1
        self.mock_temp = -70
        self.current_exposure = 0.1
        self.current_em_gain = None
        self.current_temperature_setpoint = float(self.mock_temp)

    def _commit_parameters(self):
        """Commit pending PICam parameters immediately.

        pylablib normally commits them when an acquisition is prepared. Gain and
        temperature changes need to take effect while the camera is idle as well.
        """
        commit = getattr(self.cam, "_commit_parameters", None)
        if commit is None:
            raise RuntimeError("The installed pylablib does not expose PICam parameter commit")
        commit()

    def _refresh_attributes(self):
        """Refresh cached PICam relevance flags after changing dependent settings."""
        refresh = getattr(self.cam, "_update_attributes", None)
        if refresh is not None:
            refresh(replace=True)

    def _query_attribute_capability(self, name):
        """PICamパラメータの exists/relevant/writable/制約候補/現在値を1つの辞書で返す。

        属性が存在しない・読めない場合も例外を伝播させず、
        ``{"exists": False, ...}`` を返す(`_report_em_gain_capability`と同じ防御姿勢)。
        制約が"Collection"の場合は`values`に候補値リスト、"Range"の場合は
        `min`/`max`/`inc`を入れる(どちらでもない場合は両方とも空/Noneのまま)。
        """
        result = {
            "exists": False, "relevant": False, "writable": False,
            "values": None, "min": None, "max": None, "inc": None,
            "current": None,
        }
        try:
            attr = self.cam.get_attribute(name, error_on_missing=False)
        except Exception as e:
            print(f"Failed to query attribute capability for {name}: {e}")
            return result

        if attr is None or not attr.exists:
            return result

        result["exists"] = True
        result["relevant"] = bool(attr.relevant)
        result["writable"] = bool(attr.writable)
        try:
            attr.update_limits(force=True)
            if attr.cons_type == "Collection":
                result["values"] = list(attr.values)
            elif attr.cons_type == "Range":
                result["min"] = attr.min
                result["max"] = attr.max
                result["inc"] = attr.inc
            result["current"] = self.cam.get_attribute_value(name)
        except Exception as e:
            print(f"Failed to inspect attribute capability for {name}: {e}")
        return result

    def _apply_attribute_value(self, name, value, *, ensure_relevant=None):
        """PICamパラメータへ値を設定し、commit・relevance再取得の後、実際に適用された値を
        読み戻して返す。

        `ensure_relevant`が渡された場合、設定前提を整えるコールバック(例:
        `_ensure_em_readout_mode`)を先に呼ぶ。
        """
        if ensure_relevant is not None:
            ensure_relevant()
        self.cam.set_attribute_value(name, value, truncate=False)
        self._commit_parameters()
        self._refresh_attributes()
        return self.cam.get_attribute_value(name)

    def _select_valid_dependent_value(self, name):
        """Move a dependent collection parameter to a valid device-reported value."""
        cap = self._query_attribute_capability(name)
        if not cap["writable"] or not cap["values"]:
            return
        current = cap["current"]
        if current in cap["values"]:
            return
        default = None
        attr = self.cam.get_attribute(name, error_on_missing=False)
        if attr is not None:
            default = attr.default
        selected = default if default in cap["values"] else cap["values"][0]
        self.cam.set_attribute_value(name, selected, truncate=False)
        print(f"{name} adjusted for Electron Multiplied mode: {current} -> {selected}")

    def _ensure_em_readout_mode(self):
        """Select the ProEM multiplication port before applying an EM Gain value."""
        quality_attr = self.cam.get_attribute("ADC Quality", error_on_missing=False)
        if quality_attr is None or not quality_attr.writable:
            raise RuntimeError("ADC Quality cannot be changed to Electron Multiplied")

        current_quality = self.cam.get_attribute_value("ADC Quality")
        if current_quality == "Electron Multiplied":
            return

        self.cam.set_attribute_value(
            "ADC Quality", "Electron Multiplied", truncate=False
        )
        # PICam constraints for these values depend on the selected ADC quality.
        # Preserve the current value when valid; otherwise use the camera default
        # (or the first device-reported valid value).
        for name in ("ADC Speed", "ADC Analog Gain", "ADC Bit Depth"):
            self._select_valid_dependent_value(name)
        print(f"ADC Quality changed: {current_quality} -> Electron Multiplied")
        self._report_orientation_capability("adc_quality_changed")

    def _report_em_gain_capability(self):
        """Inspect the connected PICam camera and report its EM-gain capability."""
        if self.debug:
            # Emulate a ProEM-like detector so the conditional GUI can be tested
            # without hardware. This value is not persisted to the JSON config.
            self.current_em_gain = self.mock_em_gain
            self.em_gain_info_ready.emit(True, True, 1, 1000, 1, self.mock_em_gain)
            return

        try:
            attr = self.cam.get_attribute("EM Gain", error_on_missing=False)
        except Exception as e:
            # EM Gain is optional. Failure to inspect it must not prevent the
            # rest of the camera from initializing.
            print(f"Failed to query EM Gain capability: {e}")
            self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
            return

        exists = attr is not None and bool(attr.exists)
        if not exists:
            self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
            return

        try:
            attr.update_limits(force=True)
            # A ProEM reports EM Gain as irrelevant while the Low Noise readout
            # port is selected. It is still configurable: update_em_gain() will
            # switch ADC Quality to Electron Multiplied before committing.
            available = bool(attr.writable)
            minimum = int(attr.min) if attr.min is not None else 0
            maximum = int(attr.max) if attr.max is not None else minimum
            increment = max(1, int(attr.inc)) if attr.inc is not None else 1
            current = int(self.cam.get_attribute_value("EM Gain"))
            self.current_em_gain = current
            print(
                "EM Gain detected: "
                f"current={current}, range={minimum}-{maximum}, increment={increment}, "
                f"relevant={attr.relevant}, writable={attr.writable}, "
                f"no_valid_value={attr.cons_novalid}, available={available}"
            )
            self.em_gain_info_ready.emit(
                True, available, minimum, maximum, increment, current
            )
        except Exception as e:
            # The parameter exists, so keep the component visible, but do not
            # allow writes when its limits/current value could not be verified.
            print(f"Failed to inspect EM Gain capability: {e}")
            self.em_gain_info_ready.emit(True, False, 0, 0, 0, 0)

    def _report_orientation_capability(self, context):
        """Orientation関連PICamパラメータ(Orientation/Normalize Orientation/
        Readout Orientation/Correct Pixel Bias)の存在・relevant・writable・現在値を
        調査してログ出力するだけの調査コード(Step 1、work/work_princeton.md参照)。

        TODO(実機確認待ち): ここで得られるログを基に、Low Noise/Electron Multiplied間で
        画像方向が反転するかどうかの契約(a)/(b)/(c)を確定し、該当する分岐のみ実装する。
        契約確定後は、Correct Pixel Biasが存在する場合にTrueへ設定する処理もここに追加する。
        それまではこの属性群を読むだけで、値は一切変更しない。
        """
        for name in ("Orientation", "Normalize Orientation", "Readout Orientation", "Correct Pixel Bias"):
            try:
                attr = self.cam.get_attribute(name, error_on_missing=False)
                exists = attr is not None and bool(attr.exists)
                if not exists:
                    print(f"[Orientation調査/{context}] {name}: not present on this camera")
                    continue
                current = self.cam.get_attribute_value(name)
                print(
                    f"[Orientation調査/{context}] {name}: exists={attr.exists}, "
                    f"relevant={attr.relevant}, writable={attr.writable}, current={current}"
                )
            except Exception as e:
                # This attribute group is optional/exploratory; a failure here must not
                # prevent the rest of camera initialization from proceeding.
                print(f"[Orientation調査/{context}] Failed to query {name}: {e}")

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
                self._report_em_gain_capability()
                self.temperature_set_finished.emit(self.current_temperature_setpoint)
                self.init_finished.emit()
            else:
                try:
                    self._connect_camera()
                    self.det_width, self.det_height = self.cam.get_detector_size()
                    print(f"Connected. Detector size: {self.det_width}x{self.det_height}")
                    self._report_orientation_capability("connect")
                    self.current_exposure = self.cam.set_exposure(0.1)
                    self._report_em_gain_capability()
                    self.current_temperature_setpoint = float(
                        self.cam.get_attribute_value("Sensor Temperature Set Point")
                    )
                    self.temperature_set_finished.emit(self.current_temperature_setpoint)
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
                    new_em_gain = self.new_em_gain
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

                if new_em_gain is not None:
                    actual_gain = self.current_em_gain
                    if self.debug:
                        self.mock_em_gain = int(new_em_gain)
                        self.current_em_gain = self.mock_em_gain
                        actual_gain = self.mock_em_gain
                        print(f"[DEBUG] EM Gain set to {actual_gain}x")
                    else:
                        try:
                            with self._hw_lock:
                                self._ensure_em_readout_mode()
                                self.cam.set_attribute_value(
                                    "EM Gain", int(new_em_gain), truncate=False
                                )
                                self._commit_parameters()
                                self._refresh_attributes()
                                actual_gain = int(
                                    self.cam.get_attribute_value("EM Gain")
                                )
                            self.current_em_gain = actual_gain
                            print(f"EM Gain set to {actual_gain}x")
                        except Exception as e:
                            print(f"Failed to set EM Gain: {e}")
                            self.hardware_error.emit(f"Failed to set EM Gain: {e}")
                    with self._lock:
                        self.new_em_gain = None
                    self.em_gain_set_finished.emit(
                        int(actual_gain) if actual_gain is not None else int(new_em_gain)
                    )

                if new_temperature is not None:
                    actual_temperature = self.current_temperature_setpoint
                    if self.debug:
                        self.mock_temp = float(new_temperature)
                        self.current_temperature_setpoint = self.mock_temp
                        actual_temperature = self.mock_temp
                    else:
                        try:
                            with self._hw_lock:
                                self.cam.set_attribute_value(
                                    "Sensor Temperature Set Point",
                                    float(new_temperature),
                                    truncate=False,
                                )
                                self._commit_parameters()
                                actual_temperature = float(
                                    self.cam.get_attribute_value(
                                        "Sensor Temperature Set Point"
                                    )
                                )
                            self.current_temperature_setpoint = actual_temperature
                            print(f"Temperature set point applied: {actual_temperature} C")
                        except Exception as e:
                            print(f"Failed to set temperature: {e}")
                            self.hardware_error.emit(f"Failed to set temperature: {e}")
                    with self._lock:
                        self.new_temperature = None
                    self.temperature_set_finished.emit(float(actual_temperature))

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

    def update_em_gain(self, gain):
        with self._lock:
            self.new_em_gain = int(gain)

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
