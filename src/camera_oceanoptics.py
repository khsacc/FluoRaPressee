import time
import numpy as np
from threading import Lock, Condition
from PyQt6.QtCore import QThread, pyqtSignal
from src.oceanoptics_diagnostics import no_devices_error

# Ocean Optics devices report a factory wavelength calibration but have no grating/centre
# wavelength to move and no cooler/EM gain; see work/work_OceanOptics.md for the full design
# (in particular why seabreeze is imported lazily inside run(), never at module load time, so
# Andor/Princeton Instruments users never need seabreeze installed).

_DEBUG_WAVELENGTH_MIN_NM = 350.0
_DEBUG_WAVELENGTH_MAX_NM = 1050.0
_DEBUG_PIXEL_COUNT = 2048

# Stop acquisition after this many consecutive acquire failures, mirroring the recovery
# thresholds used by camera_andor.py / camera_princeton.py.
_ACQUISITION_ERRORS_BEFORE_STOP = 5


class CameraInitError(Exception):
    """Ocean Optics接続/初期化に失敗した際に、GUIへ伝える理由を保持して送出する例外。"""


class CameraThreadOceanOptics(QThread):
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    init_failed = pyqtSignal(str)
    # (temperature_C, status); Ocean Optics has no cooler, so status is always "unsupported".
    temperature_ready = pyqtSignal(float, str)
    # (has_temperature_control, has_status_enum, min_temp_C, max_temp_C); always
    # (False, False, 0.0, 0.0) - Ocean Optics has no temperature control.
    temperature_capability_ready = pyqtSignal(bool, bool, float, float)
    # (model, serial_number), emitted once after connecting - see
    # ConfigMixin.check_and_record_hardware_identity() and acquisition_mixin.on_camera_identity_ready().
    identity_ready = pyqtSignal(str, str)

    exposure_set_finished = pyqtSignal()
    # (exists, currently_available, minimum, maximum, increment, current); always
    # (False, False, 0, 0, 0, 0) - Ocean Optics has no EM gain.
    em_gain_info_ready = pyqtSignal(bool, bool, int, int, int, int)
    em_gain_set_finished = pyqtSignal(int)
    temperature_set_finished = pyqtSignal(float)
    acquisition_failed = pyqtSignal(str)  # emitted when acquisition is auto-stopped after repeated errors, or the thread crashes while measuring
    hardware_error = pyqtSignal(str)  # emitted when a settings write (exposure) fails on hardware

    def __init__(self, config=None, debug=False):
        super().__init__()
        self.debug = debug
        self.config = config or {}

        self.thread_active = True
        self.is_measuring = False
        self.spec = None

        self._lock = Condition()  # request-state lock (new_exposure/is_measuring/request_temp/etc.)
        self._hw_lock = Lock()  # serializes every real access to self.spec (intensities/integration_time_micros/close)
        self._exposure_request_seq = 0
        self._exposure_applied_seq = 0
        # Set together with _exposure_applied_seq whenever a request fails validation or the
        # hardware write raises, so get_exposure_error() can tell a caller that specific
        # request never actually reached hardware - current_exposure is deliberately left
        # unchanged on failure (see the request-handling loop in run()), so without this a
        # caller like ApiMixin._api_start_acquire() would silently acquire with the old
        # exposure while believing the new one was applied.
        self._exposure_error_seq = 0
        self._exposure_error_message = None
        # (min_us, max_us) cached from spec.integration_time_micros_limits once connected;
        # None until then (or if the device doesn't report it), meaning "cannot pre-validate" -
        # requests are still attempted against hardware in that case.
        self._integration_time_limits_us = None

        # Overwritten once a real device (or --debug) reports its native wavelength array.
        self.det_width = _DEBUG_PIXEL_COUNT
        self.det_height = 1
        # Populated only after CameraThreadOceanOptics validates the array (finite, non-empty,
        # strictly increasing) - see _validate_native_wavelengths(). Read directly by
        # AcquisitionMixin.get_x_axis(); never included wholesale in get_cached_hardware_metadata()
        # (see work/work_OceanOptics.md Step 6 "metadata分離": a multi-thousand-point ndarray isn't
        # JSON-serializable via json_value() and shouldn't be duplicated into every saved file).
        self.native_wavelengths = None

        self.request_temp = False
        self.new_exposure = None

        self.mock_exposure = 0.1
        self.current_exposure = 0.1

        self._requested_dark_counts = bool(self.config.get("correct_dark_counts", True))
        self._requested_nonlinearity = bool(self.config.get("correct_nonlinearity", True))
        # Set by _probe_correction_capabilities() (non-debug) or forced True in --debug.
        self._supports_dark_correction = False
        self._supports_nonlinearity_correction = False

        self._metadata_identity = {"model": None, "serial_number": None}

    @staticmethod
    def _debug_native_wavelengths():
        return np.linspace(_DEBUG_WAVELENGTH_MIN_NM, _DEBUG_WAVELENGTH_MAX_NM, _DEBUG_PIXEL_COUNT)

    def _debug_spectrum(self):
        """Fabricate a ruby-like double-peak spectrum, matching camera_princeton.py's --debug data."""
        x = np.arange(self.det_width)
        y1 = 500 * np.exp(-((x - 700) ** 2) / (2 * 4 ** 2))
        y2 = 250 * np.exp(-((x - 675) ** 2) / (2 * 4 ** 2))
        base = 100 + np.random.normal(0, 10, self.det_width)
        return y1 + y2 + base

    def _connect_spectrometer(self):
        """seabreezeを遅延importして接続する。失敗時はCameraInitErrorを送出する。

        Backend選択は`from seabreeze.spectrometers import Spectrometer`より前に行う必要がある
        (python-seabreeze公式Quickstart)。
        """
        try:
            import seabreeze
        except ImportError as e:
            raise CameraInitError(
                "Ocean Optics support requires seabreeze. Install with: pip install seabreeze "
                "(or run setup_oceanoptics.bat/.sh)"
            ) from e

        backend_name = self.config.get("seabreeze_backend")
        if backend_name:
            try:
                seabreeze.use(backend_name)
            except Exception as e:
                raise CameraInitError(f"Invalid seabreeze_backend {backend_name!r}: {e}") from e

        from seabreeze.spectrometers import Spectrometer, list_devices

        serial_number = self.config.get("serial_number")
        try:
            devices = list_devices()
            if not devices:
                raise CameraInitError(no_devices_error())
            if serial_number:
                spec = Spectrometer.from_serial_number(serial_number)
            else:
                spec = Spectrometer(devices[0])
        except CameraInitError:
            raise
        except Exception as e:
            raise CameraInitError(f"Failed to connect to an Ocean Optics spectrometer: {e}") from e

        self.spec = spec

    @staticmethod
    def _validate_native_wavelengths(wavelengths):
        """波長配列が有効か確認し、無効なら理由の文字列を、有効ならNoneを返す。"""
        array = np.asarray(wavelengths)
        if array.size < 1:
            return "the reported wavelength array is empty"
        if not np.all(np.isfinite(array)):
            return "the reported wavelength array contains non-finite values"
        if array.size > 1 and not np.all(np.diff(array) > 0):
            return "the reported wavelength array is not strictly increasing"
        return None

    def _probe_correction_capabilities(self):
        """dark/nonlinearity補正のサポート有無を、それぞれ独立に1回ずつ試験する。

        python-seabreezeのintensities()はcorrect_dark_counts/correct_nonlinearityを逐次の
        if文でチェックする(dark_countsが先)ため、両方Trueで1回だけ試すとdarkが非対応の場合に
        nonlinearityの対応可否が分からない。そのため2回に分けて独立に試験し、最後に無補正の
        通常取得も試して取得基盤自体が生きていることを確認する。
        """
        from seabreeze.spectrometers import SeaBreezeError

        try:
            self.spec.intensities(correct_dark_counts=True, correct_nonlinearity=False)
            supports_dark = True
        except SeaBreezeError:
            supports_dark = False

        try:
            self.spec.intensities(correct_dark_counts=False, correct_nonlinearity=True)
            supports_nonlinearity = True
        except SeaBreezeError:
            supports_nonlinearity = False

        # Uncorrected acquisition must always succeed; if it doesn't, the acquisition
        # path itself is broken and initialization should fail rather than silently
        # reporting both corrections as unsupported.
        self.spec.intensities(correct_dark_counts=False, correct_nonlinearity=False)

        return supports_dark, supports_nonlinearity

    def _validate_exposure_range(self, exposure_us):
        """Return an error message if exposure_us is outside the cached device limits,
        else None. Limits being unknown (None) means "cannot pre-validate", not "reject" -
        the write is still attempted against hardware in that case."""
        limits = self._integration_time_limits_us
        if limits is None:
            return None
        min_us, max_us = limits
        if exposure_us < min_us or exposure_us > max_us:
            return (
                f"Requested exposure {exposure_us / 1e6:g} s is outside this Ocean Optics "
                f"device's supported range ({min_us / 1e6:g}-{max_us / 1e6:g} s)."
            )
        return None

    def _effective_correction_flags(self):
        return (
            self._requested_dark_counts and self._supports_dark_correction,
            self._requested_nonlinearity and self._supports_nonlinearity_correction,
        )

    def _warn_if_correction_unavailable(self):
        if self._requested_dark_counts and not self._supports_dark_correction:
            print(
                "Warning: correct_dark_counts=True was requested but this Ocean Optics device "
                "does not support dark count correction; acquiring without it."
            )
        if self._requested_nonlinearity and not self._supports_nonlinearity_correction:
            print(
                "Warning: correct_nonlinearity=True was requested but this Ocean Optics device "
                "does not support nonlinearity correction; acquiring without it."
            )

    def run(self):
        try:
            if self.debug:
                print("[DEBUG MODE] Activating dummy Ocean Optics spectrometer...")
                time.sleep(1.0)
                self.native_wavelengths = self._debug_native_wavelengths()
                self.det_width = len(self.native_wavelengths)
                self.det_height = 1
                self._supports_dark_correction = True
                self._supports_nonlinearity_correction = True
                self.temperature_capability_ready.emit(False, False, 0.0, 0.0)
                self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
                self._metadata_identity = {
                    "model": "USB4000 [DEBUG]",
                    "serial_number": "DEBUG-OCEANOPTICS-0000000",
                }
                self.identity_ready.emit(
                    self._metadata_identity["model"], self._metadata_identity["serial_number"]
                )
                self.init_finished.emit()
            else:
                try:
                    self._connect_spectrometer()

                    model = self.spec.model
                    serial_number = self.spec.serial_number
                    wavelengths = self.spec.wavelengths()

                    invalid_reason = self._validate_native_wavelengths(wavelengths)
                    if invalid_reason is not None:
                        raise CameraInitError(
                            "Ocean Optics device reported an invalid wavelength calibration "
                            f"array: {invalid_reason}."
                        )

                    self.native_wavelengths = np.asarray(wavelengths)
                    self.det_width = len(self.native_wavelengths)
                    self.det_height = 1

                    try:
                        self._integration_time_limits_us = self.spec.integration_time_micros_limits
                    except Exception as e:
                        print(f"Could not read Ocean Optics integration time limits: {e}")
                        self._integration_time_limits_us = None

                    self.current_exposure = 0.1
                    self.spec.integration_time_micros(int(self.current_exposure * 1_000_000))

                    (
                        self._supports_dark_correction,
                        self._supports_nonlinearity_correction,
                    ) = self._probe_correction_capabilities()
                    self._warn_if_correction_unavailable()

                    self._metadata_identity = {
                        "model": model or None,
                        "serial_number": serial_number or None,
                    }
                except CameraInitError as e:
                    print(f"Ocean Optics initialization failed: {e}")
                    self.init_failed.emit(str(e))
                    return
                except Exception as e:
                    print(f"Unexpected error during Ocean Optics initialization: {e}")
                    self.init_failed.emit(str(e))
                    return

                self.temperature_capability_ready.emit(False, False, 0.0, 0.0)
                self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
                self.identity_ready.emit(
                    self._metadata_identity["model"] or "",
                    self._metadata_identity["serial_number"] or "",
                )
                self.init_finished.emit()

            _consec_errors = 0

            while self.thread_active:
                with self._lock:
                    new_exposure, self.new_exposure = self.new_exposure, None
                    exposure_request_seq = self._exposure_request_seq
                    request_temp = self.request_temp
                    is_measuring = self.is_measuring

                if new_exposure is not None:
                    exposure_error = None
                    if self.debug:
                        self.mock_exposure = new_exposure
                        self.current_exposure = new_exposure
                    else:
                        exposure_us = int(new_exposure * 1_000_000)
                        exposure_error = self._validate_exposure_range(exposure_us)
                        if exposure_error is not None:
                            print(f"Rejected exposure request: {exposure_error}")
                            self.hardware_error.emit(exposure_error)
                        else:
                            try:
                                with self._hw_lock:
                                    self.spec.integration_time_micros(exposure_us)
                                self.current_exposure = new_exposure
                            except Exception as e:
                                exposure_error = f"Failed to set exposure: {e}"
                                print(exposure_error)
                                self.hardware_error.emit(exposure_error)
                    self.exposure_set_finished.emit()
                    # Wake anyone blocked in wait_for_exposure_applied() (e.g. the API's
                    # _api_start_acquire()) now that current_exposure reflects this request
                    # (applied or not - a failure still resolves the wait rather than hanging
                    # it; callers must check get_exposure_error(seq) to distinguish the two,
                    # since current_exposure is deliberately left at the old value on failure).
                    with self._lock:
                        if exposure_error is not None:
                            self._exposure_error_seq = exposure_request_seq
                            self._exposure_error_message = exposure_error
                        self._exposure_applied_seq = exposure_request_seq
                        self._lock.notify_all()

                if request_temp:
                    # Ocean Optics has no temperature sensor/cooler; this path is unreachable in
                    # practice since temperature_capability_ready(False, ...) hides the relevant
                    # UI (see Step 5), but is implemented defensively. 0.0 (not -999.0) is used
                    # deliberately: on_temperature_read() treats -999.0 as a hard error before it
                    # ever inspects `status`, which would short-circuit the intended "unsupported"
                    # handling.
                    self.temperature_ready.emit(0.0, "unsupported")
                    with self._lock:
                        self.request_temp = False

                if is_measuring:
                    try:
                        if self.debug:
                            spectrum = self._debug_spectrum()
                            self.data_ready.emit("1d", spectrum)
                            time.sleep(self.mock_exposure)
                        else:
                            dark, nonlinearity = self._effective_correction_flags()
                            with self._hw_lock:
                                intensities = self.spec.intensities(
                                    correct_dark_counts=dark,
                                    correct_nonlinearity=nonlinearity,
                                )
                            self.data_ready.emit("1d", np.asarray(intensities))
                        _consec_errors = 0
                    except Exception as e:
                        print(f"Failed to acquire Ocean Optics spectrum: {e}")
                        _consec_errors += 1
                        if _consec_errors >= _ACQUISITION_ERRORS_BEFORE_STOP:
                            error_msg = (
                                f"Stopping acquisition after {_consec_errors} consecutive Ocean "
                                f"Optics errors. Last error: {e}"
                            )
                            print(error_msg)
                            with self._lock:
                                self.is_measuring = False
                            self.acquisition_failed.emit(error_msg)
                            _consec_errors = 0
                        time.sleep(0.05)
                else:
                    _consec_errors = 0
                    time.sleep(0.05)

        except Exception as e:
            print(f"An error occurred in the Ocean Optics camera thread: {e}")
            # Without this, an exception escaping the loop above would kill the thread silently:
            # the GUI never learns about it and stays stuck showing "measuring" indefinitely.
            with self._lock:
                crashed_while_measuring, self.is_measuring = self.is_measuring, False
            if crashed_while_measuring:
                self.acquisition_failed.emit(str(e))
        finally:
            # Only run() (this thread) ever calls spec.close(), so it can never race a
            # concurrent intensities() call made from here under _hw_lock - see
            # work/work_OceanOptics.md Step 1 "close()の所有権を明確にする".
            if self.spec is not None:
                try:
                    self.spec.close()
                except Exception as e:
                    print(f"Failed to close Ocean Optics spectrometer: {e}")
                self.spec = None

    def read_temperature(self):
        with self._lock:
            self.request_temp = True

    def get_cached_hardware_metadata(self):
        """Return acquisition metadata without touching the seabreeze SDK.

        Deliberately excludes the native wavelength array itself (see the comment on
        self.native_wavelengths in __init__); only a small summary is included here.
        """
        with self._lock:
            native_wavelength_range = None
            if self.native_wavelengths is not None and len(self.native_wavelengths) > 0:
                native_wavelength_range = {
                    "count": int(len(self.native_wavelengths)),
                    "min_nm": float(np.min(self.native_wavelengths)),
                    "max_nm": float(np.max(self.native_wavelengths)),
                }
            hardware_dark_corrected, nonlinearity_corrected = self._effective_correction_flags()
            return {
                "identity": dict(self._metadata_identity),
                "detector_size_px": {"width": self.det_width, "height": self.det_height},
                "exposure_s": float(self.current_exposure),
                "temperature": {"setpoint_c": None},
                "hardware_dark_corrected": hardware_dark_corrected,
                "nonlinearity_corrected": nonlinearity_corrected,
                "native_wavelength_range": native_wavelength_range,
            }

    def update_exposure(self, exp_time):
        """Request an exposure change (thread-safe) and return a token identifying this
        request; pass it to wait_for_exposure_applied() to block until run() has pushed it
        to hardware (or a newer request superseded it)."""
        with self._lock:
            self.new_exposure = exp_time
            self._exposure_request_seq += 1
            return self._exposure_request_seq

    def wait_for_exposure_applied(self, seq, timeout=None):
        """Block until the exposure request identified by `seq` has been applied by run(),
        or `timeout` seconds elapse. Returns True if applied, False on timeout."""
        with self._lock:
            return self._lock.wait_for(lambda: self._exposure_applied_seq >= seq, timeout=timeout)

    def get_exposure_error(self, seq):
        """Return the failure message if the exposure request identified by `seq` (a token
        from update_exposure()) failed validation or the hardware write, else None. Callers
        should check this after wait_for_exposure_applied() returns, since a failed request
        still resolves that wait rather than hanging until timeout."""
        with self._lock:
            if self._exposure_error_seq == seq:
                return self._exposure_error_message
            return None

    def update_temperature(self, temp):
        """No-op: Ocean Optics has no cooler. Kept for interface parity with
        CameraThreadAndor/CameraThreadPI - the cooler UI stays hidden (Step 5) so this is
        never actually invoked by the GUI, but the method must exist since
        spin_cooler_temp.editingFinished is wired unconditionally in ui.py."""

    def update_em_gain(self, gain):
        """No-op: Ocean Optics has no EM gain. Kept for interface parity - see
        update_temperature()'s docstring; never actually invoked since
        em_gain_info_ready(False, ...) disables the calling GUI path."""

    def update_roi_settings(self, mode, vstart=0, vend=256):
        """Accepted but ignored: Ocean Optics is a fixed 1-row detector with no ROI to apply.
        Exists so callers that unconditionally call this (e.g. apply_roi_settings()) don't
        need an Ocean-Optics-specific branch."""

    def start_measuring(self):
        with self._lock:
            self.is_measuring = True

    def stop_measuring(self):
        with self._lock:
            self.is_measuring = False

    def stop_thread(self):
        self.thread_active = False
        self.wait()
