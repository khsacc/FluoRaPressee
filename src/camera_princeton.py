import os
import time
import numpy as np
from threading import Lock, Condition
from PyQt5.QtCore import QThread, pyqtSignal

# Wrapped in try-except so a missing SDK doesn't raise an error when running in debug (dummy) mode
try:
    import pylablib
    from pylablib.devices import PrincetonInstruments
    from pylablib.devices.PrincetonInstruments import picam as picam_module
except ImportError:
    pylablib = None
    PrincetonInstruments = None
    picam_module = None

# Default install location for the PICam Runtime
_DEFAULT_PICAM_RUNTIME_PATH = r"C:\Program Files\Princeton Instruments\PICam\Runtime"

# A real ProEM CCD frame always contains a bias pedestal and read noise, even
# with the shutter closed.  An ndarray whose every pixel is exactly zero is
# therefore an unfilled/invalid PICam receive buffer, not a dark exposure.
_ZERO_FRAMES_BEFORE_RECOVERY = 3
_ERRORS_BEFORE_RECOVERY = 2
_MAX_ACQUISITION_RECOVERIES = 2
_ACQUISITION_ERRORS_BEFORE_STOP = 5

# Fallback settable-temperature range reported by temperature_capability_ready: in --debug
# mode (no real camera to query), and on real hardware in the unlikely case the "Sensor
# Temperature Set Point" attribute's Range constraint can't be determined even though
# has_control is True. Matches the pre-existing hardcoded spin_cooler_temp range in
# ui.py / config_wizard.py.
_FALLBACK_TEMP_MIN = -100.0
_FALLBACK_TEMP_MAX = 20.0


def _get_picam_runtime_path(config):
    # Keep using the existing "PIcam_dll_path" config key (may be renamed to "picam_runtime_path" later)
    return (config or {}).get("PIcam_dll_path", _DEFAULT_PICAM_RUNTIME_PATH)


class CameraInitError(Exception):
    """カメラ初期化に失敗した際に、GUIへ伝える理由を保持して送出する例外。"""


class CameraThreadPI(QThread):
    data_ready = pyqtSignal(str, np.ndarray)
    init_finished = pyqtSignal()
    init_failed = pyqtSignal(str)  # emitted when hardware initialization fails, with a human-readable reason
    # (temperature_C, status) where status in {"locked", "unlocked", "faulted", "unknown", "unsupported"}
    temperature_ready = pyqtSignal(float, str)
    # (has_temperature_control, has_status_enum, min_temp_C, max_temp_C), emitted once after
    # connecting. min/max come from the "Sensor Temperature Set Point" PICam attribute's Range
    # constraint and are used to clamp spin_cooler_temp's input range in acquisition_mixin.py.
    temperature_capability_ready = pyqtSignal(bool, bool, float, float)
    # (model, serial_number), emitted once after connecting, so the GUI can cross-check it
    # against spectrometerConfig.json's recorded "hardware_identity.camera" (see
    # ConfigMixin.check_and_record_hardware_identity()).
    identity_ready = pyqtSignal(str, str)

    exposure_set_finished = pyqtSignal()
    # exists, currently_available, minimum, maximum, increment, current
    em_gain_info_ready = pyqtSignal(bool, bool, int, int, int, int)
    em_gain_set_finished = pyqtSignal(int)
    temperature_set_finished = pyqtSignal(float)
    acquisition_failed = pyqtSignal(str)  # emitted when acquisition is auto-stopped after repeated errors, or the thread crashes while measuring
    hardware_error = pyqtSignal(str)  # emitted when a settings write (exposure/temperature) fails on hardware
    # emitted in response to request_status(): {section title: [(label, value_str), ...], ...}
    status_ready = pyqtSignal(dict)

    def __init__(self, config=None, debug=False):
        super().__init__()
        self.debug = debug
        self.config = config or {}

        self.thread_active = True
        self.is_measuring = False
        self.cam = None
        self._dll_dir_cookie = None
        self._lock = Condition()  # also used to wait for a pending exposure to actually reach hardware
        self._hw_lock = Lock()  # Lock for exclusive access to hardware (snap / applying settings)
        self._exposure_request_seq = 0
        self._exposure_applied_seq = 0

        # Defaults matching a PIXIS: 100F (overwritten by get_detector_size() once a real camera is connected)
        self.det_width = 1340
        self.det_height = 100

        self.roi_mode = "1d_roi"
        self.roi_vstart = 45
        self.roi_vend = 65
        self.settings_changed = True

        self.request_temp = False
        self.status_requested = False
        self.new_exposure = None
        self.new_em_gain = None
        self.new_temperature = None

        self.mock_exposure = 0.1
        self.mock_em_gain = 1
        self.mock_temp = self.config.get("default_temperature", -70)
        self.current_exposure = 0.1
        self.current_em_gain = None
        self.current_temperature_setpoint = float(self.mock_temp)
        self._metadata_identity = {"model": None, "serial_number": None}
        self._metadata_pixel_pitch_um = {"width": None, "height": None}

        # --debug convergence simulation for Sensor Temperature Status (see
        # _debug_temperature_sample()); lets the GUI's Locked/Stabilised path be
        # exercised without hardware.
        self._debug_sim_temp = self.mock_temp + 10.0
        self._debug_temp_status = "unlocked"
        self._debug_forced_temp_status = (
            str(self.config.get("debug_force_temperature_status") or "").strip().lower() or None
        )

        # Set by _report_temperature_capability(); cached so read_temperature() doesn't
        # re-check attribute existence on every poll.
        self._temp_status_supported = False

    @staticmethod
    def _is_all_zero_frame(data):
        """Return True only for a non-empty frame whose values are all exactly zero."""
        array = np.asarray(data)
        return array.size > 0 and not np.any(array)

    def _frame_diagnostics(self, data):
        """Build a compact hardware-oriented description for acquisition logs."""
        array = np.asarray(data)
        try:
            roi = self.cam.get_roi() if self.cam is not None else None
        except Exception as e:
            roi = f"unavailable ({e})"
        try:
            in_progress = (
                self.cam.acquisition_in_progress() if self.cam is not None else None
            )
        except Exception as e:
            in_progress = f"unavailable ({e})"
        return (
            f"shape={array.shape}, dtype={array.dtype}, roi={roi}, "
            f"exposure={self.current_exposure:.6g}s, "
            f"acquisition_in_progress={in_progress}"
        )

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

    # Sections shown by the "Check Camera Status" dialog (src/menu/camera_status_dialog.py).
    # Each entry is (display label, PICam attribute name) except "model"/"serial_number"/
    # "sensor_name", which come from get_device_info() rather than a PICam attribute.
    _STATUS_FIELDS = (
        ("Camera identification", (
            ("Model", "model"),
            ("Serial number", "serial_number"),
            ("Sensor name", "sensor_name"),
            ("Sensor width (px)", "Sensor Active Width"),
            ("Sensor height (px)", "Sensor Active Height"),
            ("Pixel width (um)", "Pixel Width"),
            ("Pixel height (um)", "Pixel Height"),
            ("Sensor type", "Sensor Type"),
            ("CCD characteristics", "CCD Characteristics"),
            ("Readout port count", "Readout Port Count"),
        )),
        ("Exposure / acquisition", (
            ("Exposure time (ms)", "Exposure Time"),
            ("Readout count", "Readout Count"),
            ("Accumulations", "Accumulations"),
            ("Readout control mode", "Readout Control Mode"),
            ("Kinetics window height", "Kinetics Window Height"),
            ("Readout time calculation (ms)", "Readout Time Calculation"),
            ("Frame rate calculation (fps)", "Frame Rate Calculation"),
        )),
        ("Readout amplifier / ADC / EM gain", (
            ("Readout path", "ADC Quality"),
            ("ADC speed (MHz)", "ADC Speed"),
            ("Analog gain", "ADC Analog Gain"),
            ("EM gain", "EM Gain"),
            ("Pixel bias correction", "Correct Pixel Bias"),
        )),
        ("Shutter", (
            ("Active shutter", "Active Shutter"),
            ("Shutter timing mode", "Shutter Timing Mode"),
            ("Shutter opening delay (ms)", "Shutter Opening Delay"),
            ("Shutter closing delay (ms)", "Shutter Closing Delay"),
            ("Shutter delay resolution (us)", "Shutter Delay Resolution"),
            ("Internal shutter type", "Internal Shutter Type"),
            ("Internal shutter status", "Internal Shutter Status"),
            ("External shutter type", "External Shutter Type"),
            ("External shutter status", "External Shutter Status"),
        )),
        ("Temperature / cooling", (
            ("Target temperature (C)", "Sensor Temperature Set Point"),
            ("Current temperature (C)", "Sensor Temperature Reading"),
            ("Temperature status", "Sensor Temperature Status"),
            ("Cooling fan disabled", "Disable Cooling Fan"),
            ("Cooling fan status", "Cooling Fan Status"),
            ("Sensor window heater enabled", "Enable Sensor Window Heater"),
            ("Vacuum status", "Vacuum Status"),
        )),
    )

    def _build_status_snapshot(self):
        """Read every parameter in `_STATUS_FIELDS` off the connected camera.

        Called only from run() (under `_hw_lock`), matching every other `self.cam` access
        in this file. A parameter absent on this particular camera model (e.g. EM Gain on
        a non-ProEM PICam camera) reads as "N/A" rather than raising.
        """
        info = self.cam.get_device_info()
        device_fields = {"model": info.model, "serial_number": info.serial_number, "sensor_name": info.name}

        snapshot = {}
        try:
            firmware_details = picam_module.lib.Picam_GetFirmwareDetails_ByHandle(
                self.cam.handle
            )
            snapshot["Camera firmware"] = [
                (
                    detail.name.decode(errors="replace"),
                    detail.detail.decode(errors="replace"),
                )
                for detail in firmware_details
            ]
        except Exception as e:
            snapshot["Camera firmware"] = [("Firmware details", f"Unavailable ({e})")]

        for section, fields in self._STATUS_FIELDS:
            rows = []
            for label, key in fields:
                if key in device_fields:
                    rows.append((label, str(device_fields[key])))
                    continue
                cap = self._query_attribute_capability(key)
                if not cap["exists"]:
                    rows.append((label, "N/A (not supported on this camera)"))
                elif cap["current"] is None:
                    rows.append((label, "Unavailable"))
                else:
                    rows.append((label, str(cap["current"])))
            snapshot[section] = rows
        return snapshot

    def _debug_status_snapshot(self):
        """Fabricated status snapshot for --debug mode (no real camera connected)."""
        return {
            "Camera firmware": [
                ("Config", "DEBUG"),
                ("Logic", "DEBUG"),
                ("ADC", "DEBUG"),
                ("Power", "DEBUG"),
            ],
            "Camera identification": [
                ("Model", "ProEM:1600(2) [DEBUG]"),
                ("Serial number", "DEBUG-0000000"),
                ("Sensor name", "Simulated Sensor"),
                ("Sensor width (px)", str(self.det_width)),
                ("Sensor height (px)", str(self.det_height)),
                ("Pixel width (um)", "16.0"),
                ("Pixel height (um)", "16.0"),
                ("Sensor type", "CCD"),
                ("CCD characteristics", "Back Illuminated"),
                ("Readout port count", "1"),
            ],
            "Exposure / acquisition": [
                ("Exposure time (ms)", f"{self.mock_exposure * 1000:.3f}"),
                ("Readout count", "1"),
                ("Accumulations", "1"),
                ("Readout control mode", "Full Frame"),
                ("Kinetics window height", "N/A (not supported on this camera)"),
                ("Readout time calculation (ms)", f"{self.mock_exposure * 1000:.3f}"),
                ("Frame rate calculation (fps)", f"{(1.0 / self.mock_exposure):.3f}" if self.mock_exposure else "N/A"),
            ],
            "Readout amplifier / ADC / EM gain": [
                ("Readout path", "Electron Multiplied"),
                ("ADC speed (MHz)", "10"),
                ("Analog gain", "Low"),
                ("EM gain", str(self.mock_em_gain)),
                ("Pixel bias correction", "True"),
            ],
            "Shutter": [
                ("Active shutter", "Internal"),
                ("Shutter timing mode", "Normal"),
                ("Shutter opening delay (ms)", "0.0"),
                ("Shutter closing delay (ms)", "0.0"),
                ("Shutter delay resolution (us)", "1000"),
                ("Internal shutter type", "Vincent Uniblitz"),
                ("Internal shutter status", "Open"),
                ("External shutter type", "None"),
                ("External shutter status", "N/A (not supported on this camera)"),
            ],
            "Temperature / cooling": [
                ("Target temperature (C)", f"{self.mock_temp:.1f}"),
                ("Current temperature (C)", f"{self.mock_temp:.1f}"),
                ("Temperature status", "Locked"),
                ("Cooling fan disabled", "False"),
                ("Cooling fan status", "On"),
                ("Sensor window heater enabled", "False"),
                ("Vacuum status", "Sufficient"),
            ],
        }

    def _apply_attribute_value(self, name, value, *, ensure_relevant=None, rollback_names=()):
        """PICamパラメータへ値を設定し、commit・relevance再取得の後、実際に適用された値を
        読み戻して返す。

        `ensure_relevant`が渡された場合、設定前提を整えるコールバック(例:
        `_ensure_em_readout_mode`)を先に呼ぶ。pylablibのPICamラッパーは
        set_attribute_value(truncate=False)で範囲検証なしに保留値をセットし、検証は
        commit時に行う。そのため`ensure_relevant`が依存パラメータを変更した直後や、
        その最中に例外が出た場合、不正な保留値がPICam内に残留し、以降のcommit(snap()
        内部のものを含む)が失敗し続けるおそれがある。`rollback_names`に、
        `ensure_relevant`が触れる可能性のある依存パラメータ名を渡しておくと、
        変更前の値を記録しておき、失敗時にbest-effortで戻す。
        """
        rollback_names = tuple(dict.fromkeys((*rollback_names, name)))
        previous_values = {}
        for rname in rollback_names:
            try:
                previous_values[rname] = self.cam.get_attribute_value(rname)
            except Exception as e:
                print(f"Failed to snapshot {rname} before applying {name}: {e}")

        try:
            if ensure_relevant is not None:
                ensure_relevant()
            self.cam.set_attribute_value(name, value, truncate=False)
            self._commit_parameters()
        except Exception:
            self._rollback_attribute_values(previous_values)
            raise
        self._refresh_attributes()
        return self.cam.get_attribute_value(name)

    def _rollback_attribute_values(self, previous_values):
        """commit失敗時(または`ensure_relevant`コールバック内での例外時)、記録しておいた
        変更前の値へbest-effortで戻す。

        ロールバック自体が失敗しても、PICamパラメータモデルの汚染をこれ以上悪化させない
        よう、例外は送出せずログのみ残す。
        """
        if not previous_values:
            return
        for rname, rvalue in previous_values.items():
            try:
                self.cam.set_attribute_value(rname, rvalue, truncate=False)
            except Exception as e:
                print(f"Rollback: failed to restore {rname} to {rvalue!r}: {e}")
        try:
            self._commit_parameters()
        except Exception as e:
            print(f"Rollback: commit of restored parameters failed: {e}")
            return
        try:
            self._refresh_attributes()
        except Exception as e:
            print(f"Rollback: failed to refresh attributes after restore: {e}")

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

    def _report_em_gain_capability(self):
        """Inspect the connected PICam camera and report its EM-gain capability."""
        if self.debug:
            # Emulate a ProEM-like detector so the conditional GUI can be tested
            # without hardware. This value is not persisted to the JSON config.
            self.current_em_gain = self.mock_em_gain
            self.em_gain_info_ready.emit(True, True, 1, 1000, 1, self.mock_em_gain)
            return

        cap = self._query_attribute_capability("EM Gain")
        if not cap["exists"]:
            self.em_gain_info_ready.emit(False, False, 0, 0, 0, 0)
            return

        if cap["current"] is None:
            # The parameter exists, so keep the component visible, but do not
            # allow writes when its limits/current value could not be verified
            # (_query_attribute_capability only leaves "current" unset when the
            # inspection itself raised).
            self.em_gain_info_ready.emit(True, False, 0, 0, 0, 0)
            return

        # A ProEM reports EM Gain as irrelevant while the Low Noise readout port is
        # selected. It is still configurable: update_em_gain() will switch ADC
        # Quality to Electron Multiplied before committing.
        available = cap["writable"]
        minimum = int(cap["min"]) if cap["min"] is not None else 0
        maximum = int(cap["max"]) if cap["max"] is not None else minimum
        increment = max(1, int(cap["inc"])) if cap["inc"] is not None else 1
        current = int(cap["current"])
        self.current_em_gain = current
        print(
            "EM Gain detected: "
            f"current={current}, range={minimum}-{maximum}, increment={increment}, "
            f"relevant={cap['relevant']}, writable={cap['writable']}, available={available}"
        )
        self.em_gain_info_ready.emit(True, available, minimum, maximum, increment, current)

    def _report_temperature_capability(self):
        """Inspect the connected PICam camera and report whether it has temperature
        control, and whether it exposes a Locked/Unlocked/Faulted status enum.

        Unlike EM Gain, a temperature set point has no "irrelevant but recoverable"
        path (no `ensure_relevant` callback to switch modes and retry), so a set
        point that exists but can't currently be read/written is treated as no
        control at all, not as a visible-but-disabled component.
        """
        setpoint_cap = self._query_attribute_capability("Sensor Temperature Set Point")
        reading_cap = self._query_attribute_capability("Sensor Temperature Reading")
        status_cap = self._query_attribute_capability("Sensor Temperature Status")

        has_control = (
            setpoint_cap["exists"] and setpoint_cap["relevant"] and setpoint_cap["writable"]
            and setpoint_cap["current"] is not None
            and reading_cap["exists"] and reading_cap["relevant"]
            and reading_cap["current"] is not None
        )
        self._temp_status_supported = status_cap["exists"]
        temp_min = setpoint_cap["min"] if setpoint_cap["min"] is not None else _FALLBACK_TEMP_MIN
        temp_max = setpoint_cap["max"] if setpoint_cap["max"] is not None else _FALLBACK_TEMP_MAX
        print(
            "Temperature capability detected: "
            f"has_control={has_control}, has_status={self._temp_status_supported}, "
            f"range={temp_min}..{temp_max}"
        )
        self.temperature_capability_ready.emit(has_control, self._temp_status_supported, temp_min, temp_max)
        return has_control, setpoint_cap

    def _debug_temperature_sample(self):
        """Simulate PICam temperature convergence and Locked/Unlocked/Faulted status
        for --debug mode, so the GUI's stabilisation UI can be exercised without
        hardware. `debug_force_temperature_status` in spectrometerConfig.json
        (e.g. "faulted") pins the status for manual verification of that path.
        """
        diff = self.mock_temp - self._debug_sim_temp
        self._debug_sim_temp += diff * 0.3 + np.random.uniform(-0.15, 0.15)
        if self._debug_forced_temp_status in ("locked", "unlocked", "faulted"):
            self._debug_temp_status = self._debug_forced_temp_status
        else:
            self._debug_temp_status = (
                "locked" if abs(self._debug_sim_temp - self.mock_temp) < 0.3 else "unlocked"
            )
        return self._debug_sim_temp, self._debug_temp_status

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
                    print(f"[Orientation investigation/{context}] {name}: not present on this camera")
                    continue
                current = self.cam.get_attribute_value(name)
                print(
                    f"[Orientation investigation/{context}] {name}: exists={attr.exists}, "
                    f"relevant={attr.relevant}, writable={attr.writable}, current={current}"
                )
            except Exception as e:
                # This attribute group is optional/exploratory; a failure here must not
                # prevent the rest of camera initialization from proceeding.
                print(f"[Orientation investigation/{context}] Failed to query {name}: {e}")

    # Attributes inspected by _report_shutter_capability(), in the order given in
    # work/work_PI_shutter.md Section 5.
    _SHUTTER_CAPABILITY_ATTRIBUTES = (
        "Active Shutter",
        "Shutter Timing Mode",
        "Shutter Opening Delay",
        "Shutter Closing Delay",
        "Shutter Delay Resolution",
        "Internal Shutter Type",
        "Internal Shutter Status",
        "External Shutter Type",
        "External Shutter Status",
    )

    def _report_shutter_capability(self, context):
        """Shutter関連PICamパラメータ(Active Shutter/Shutter Timing Mode/Opening・
        Closing Delay/Shutter Delay Resolution/Internal・External Shutter Type・
        Status)の存在・relevant・writable・候補値(またはRange)・現在値を調査して
        ログ出力するだけの調査コード(Step 1、work/work_PI_shutter.md Section 5/17参照)。

        値の書き込み(set_attribute_value)は一切行わない。Section 6の自動判定
        (automation_ready等)やspectrometerConfig.jsonへの保存は後続のStepで実装する。
        属性ごとの例外はログに残すだけでカメラ接続全体を落とさない。
        """
        for name in self._SHUTTER_CAPABILITY_ATTRIBUTES:
            try:
                cap = self._query_attribute_capability(name)
                if not cap["exists"]:
                    print(f"[Shutter investigation/{context}] {name}: not present on this camera")
                    continue
                details = (
                    f"exists={cap['exists']}, relevant={cap['relevant']}, "
                    f"writable={cap['writable']}, current={cap['current']}"
                )
                if cap["values"] is not None:
                    details += f", values={cap['values']}"
                elif cap["min"] is not None or cap["max"] is not None or cap["inc"] is not None:
                    details += f", min={cap['min']}, max={cap['max']}, inc={cap['inc']}"
                print(f"[Shutter investigation/{context}] {name}: {details}")
            except Exception as e:
                print(f"[Shutter investigation/{context}] Failed to query {name}: {e}")

    def _connect_camera(self):
        """PICamカメラを列挙・選択して接続する。失敗時は CameraInitError を送出する。"""
        if PrincetonInstruments is None:
            raise CameraInitError("pylablib is not installed; cannot access PICam cameras.")

        runtime_path = _get_picam_runtime_path(self.config)
        if hasattr(os, 'add_dll_directory') and self._dll_dir_cookie is None:
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

    def _stop_and_clear_acquisition(self):
        """Bring pylablib/PICam back to a known idle state.

        PICam can race between its running-status query and the following wait,
        producing error 27 even though the acquisition has already stopped.  It
        can also briefly report error 20 while the previous readout is winding
        down.  Treat error 27 as an idle indication here only; it is no longer
        ignored indefinitely in the main acquisition loop.
        """
        if self.cam is None:
            return

        try:
            self.cam.stop_acquisition()
        except Exception as e:
            if getattr(e, "code", None) != 27:
                raise
            print(f"PICam recovery: stop reported already idle (error 27): {e}")

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                if not self.cam.acquisition_in_progress():
                    break
            except Exception:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("PICam acquisition did not become idle within 2 seconds")

        try:
            self.cam.clear_acquisition()
        except Exception as e:
            if getattr(e, "code", None) != 27:
                raise
            print(f"PICam recovery: clear reported already idle (error 27): {e}")

    def _reset_acquisition_state(self):
        """Clear the current acquisition and re-apply the intended ROI/binning."""
        with self._hw_lock:
            self._stop_and_clear_acquisition()
            self._apply_camera_settings()
        with self._lock:
            self.settings_changed = False

    def _reopen_camera_connection(self):
        """Reopen PICam once and restore settings owned by this application."""
        with self._hw_lock:
            previous_exposure = self.current_exposure
            previous_temperature = self.current_temperature_setpoint
            previous_quality = None
            previous_em_gain = self.current_em_gain

            if self.cam is not None:
                try:
                    previous_quality = self.cam.get_attribute_value("ADC Quality")
                except Exception as e:
                    print(f"PICam recovery: failed to snapshot ADC Quality: {e}")
                try:
                    self._stop_and_clear_acquisition()
                except Exception as e:
                    print(f"PICam recovery: best-effort acquisition clear failed: {e}")
                try:
                    self.cam.close()
                finally:
                    self.cam = None

            # Give the GigE/PICam device session a short interval to release its
            # old handle before enumerating and opening it again.
            time.sleep(0.25)
            self._connect_camera()
            self.det_width, self.det_height = self.cam.get_detector_size()
            self._report_shutter_capability("reconnect")
            self.current_exposure = self.cam.set_exposure(previous_exposure)

            if previous_quality == "Electron Multiplied" and previous_em_gain is not None:
                self.current_em_gain = int(self._apply_attribute_value(
                    "EM Gain", int(previous_em_gain),
                    ensure_relevant=self._ensure_em_readout_mode,
                    rollback_names=(
                        "ADC Quality", "ADC Speed", "ADC Analog Gain", "ADC Bit Depth",
                    ),
                ))

            temp_attr = self.cam.get_attribute(
                "Sensor Temperature Set Point", error_on_missing=False
            )
            if temp_attr is not None and temp_attr.writable:
                self.cam.set_attribute_value(
                    "Sensor Temperature Set Point", previous_temperature, truncate=False
                )
                self._commit_parameters()
                self.current_temperature_setpoint = float(
                    self.cam.get_attribute_value("Sensor Temperature Set Point")
                )

            self._apply_camera_settings()

        with self._lock:
            self.settings_changed = False
        print(
            "PICam recovery: camera connection reopened and application settings restored"
        )

    def _recover_acquisition(self, reason, recovery_number):
        """Run one bounded recovery stage; callers stop after the configured maximum."""
        if recovery_number == 1:
            action = "clear acquisition state and re-apply ROI"
            print(f"PICam recovery 1/{_MAX_ACQUISITION_RECOVERIES}: {action}; reason: {reason}")
            self._reset_acquisition_state()
        elif recovery_number == 2:
            action = "reopen camera connection"
            print(f"PICam recovery 2/{_MAX_ACQUISITION_RECOVERIES}: {action}; reason: {reason}")
            self._reopen_camera_connection()
        else:
            raise RuntimeError(
                f"PICam recovery limit exceeded ({_MAX_ACQUISITION_RECOVERIES}): {reason}"
            )

    def run(self):
        try:
            if self.debug:
                print("[DEBUG MODE] Activating dummy camera...")
                time.sleep(1.0)
                self._report_em_gain_capability()
                self.temperature_capability_ready.emit(True, True, _FALLBACK_TEMP_MIN, _FALLBACK_TEMP_MAX)
                self.temperature_set_finished.emit(self.current_temperature_setpoint)
                # Fabricated so --debug mode can exercise the hardware_identity check;
                # matches _debug_status_snapshot()'s "Camera identification" values.
                self.identity_ready.emit("ProEM:1600(2) [DEBUG]", "DEBUG-0000000")
                self._metadata_identity = {
                    "model": "ProEM:1600(2) [DEBUG]",
                    "serial_number": "DEBUG-0000000",
                }
                self._metadata_pixel_pitch_um = {"width": 16.0, "height": 16.0}
                self.init_finished.emit()
            else:
                try:
                    self._connect_camera()
                    self.det_width, self.det_height = self.cam.get_detector_size()
                    print(f"Connected. Detector size: {self.det_width}x{self.det_height}")
                    pixel_width = self._query_attribute_capability("Pixel Width").get("current")
                    pixel_height = self._query_attribute_capability("Pixel Height").get("current")
                    self._metadata_pixel_pitch_um = {
                        "width": pixel_width,
                        "height": pixel_height,
                    }
                    self._report_orientation_capability("connect")
                    self._report_shutter_capability("connect")
                    self.current_exposure = self.cam.set_exposure(0.1)
                    self._report_em_gain_capability()
                    has_temp_control, setpoint_cap = self._report_temperature_capability()
                    if has_temp_control:
                        self.current_temperature_setpoint = float(setpoint_cap["current"])
                        self.temperature_set_finished.emit(self.current_temperature_setpoint)
                        default_temp = self.config.get("default_temperature")
                        if default_temp is not None:
                            temp_min = setpoint_cap["min"] if setpoint_cap["min"] is not None else _FALLBACK_TEMP_MIN
                            temp_max = setpoint_cap["max"] if setpoint_cap["max"] is not None else _FALLBACK_TEMP_MAX
                            clamped_temp = min(max(float(default_temp), temp_min), temp_max)
                            if clamped_temp != float(default_temp):
                                print(
                                    f"Warning: configured default_temperature {default_temp}C is outside "
                                    f"the camera's settable range ({temp_min}..{temp_max}C); "
                                    f"clamping to {clamped_temp}C"
                                )
                            if abs(clamped_temp - self.current_temperature_setpoint) > 1e-6:
                                # Drive the cooler to the configured default; picked up and applied
                                # by the main loop's normal new_temperature handling below.
                                self.new_temperature = clamped_temp
                except CameraInitError as e:
                    print(f"Camera initialization failed: {e}")
                    self.init_failed.emit(str(e))
                    return
                except Exception as e:
                    print(f"Unexpected error during camera initialization: {e}")
                    self.init_failed.emit(str(e))
                    return

                try:
                    device_info = self.cam.get_device_info()
                    identity_model, identity_serial = device_info.model, device_info.serial_number
                    self._metadata_identity = {
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
            _consec_zero_frames = 0
            _recovery_attempts = 0

            while self.thread_active:
                with self._lock:
                    # Swap-and-clear here (not after applying) so a newer request that
                    # arrives while the old one is still being applied to hardware is
                    # not silently overwritten by an unconditional clear afterwards.
                    new_exposure, self.new_exposure = self.new_exposure, None
                    exposure_request_seq = self._exposure_request_seq
                    new_em_gain, self.new_em_gain = self.new_em_gain, None
                    new_temperature, self.new_temperature = self.new_temperature, None
                    request_temp = self.request_temp
                    status_requested = self.status_requested
                    is_measuring = self.is_measuring
                    settings_changed = self.settings_changed

                if new_exposure is not None:
                    if self.debug:
                        self.mock_exposure = new_exposure
                        self.current_exposure = new_exposure
                    else:
                        try:
                            # PICam converts seconds<->milliseconds internally and returns the actual
                            # value applied after the device rounds it. Held under _hw_lock so this
                            # never races a concurrent snap()/acquire_single_image() touching self.cam.
                            with self._hw_lock:
                                self.current_exposure = self.cam.set_exposure(new_exposure)
                        except Exception as e:
                            print(f"Failed to set exposure: {e}")
                            self.hardware_error.emit(f"Failed to set exposure: {e}")
                    self.exposure_set_finished.emit()
                    # Wake anyone blocked in wait_for_exposure_applied() (e.g. acquire_single_image())
                    # now that self.current_exposure reflects this request (applied or not - failure
                    # still resolves the wait rather than hanging it).
                    with self._lock:
                        self._exposure_applied_seq = exposure_request_seq
                        self._lock.notify_all()

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
                                actual_gain = int(self._apply_attribute_value(
                                    "EM Gain", int(new_em_gain),
                                    ensure_relevant=self._ensure_em_readout_mode,
                                    rollback_names=(
                                        "ADC Quality", "ADC Speed",
                                        "ADC Analog Gain", "ADC Bit Depth",
                                    ),
                                ))
                                # commit_parameters()/_refresh_attributes() above have already run
                                # (inside _apply_attribute_value), so this reflects the post-switch
                                # attribute state rather than a stale pre-commit cache.
                                self._report_orientation_capability("adc_quality_changed")
                            self.current_em_gain = actual_gain
                            print(f"EM Gain set to {actual_gain}x")
                        except Exception as e:
                            print(f"Failed to set EM Gain: {e}")
                            self.hardware_error.emit(f"Failed to set EM Gain: {e}")
                    self.em_gain_set_finished.emit(
                        int(actual_gain) if actual_gain is not None else int(new_em_gain)
                    )

                if new_temperature is not None:
                    actual_temperature = self.current_temperature_setpoint
                    if self.debug:
                        self.mock_temp = float(new_temperature)
                        self.current_temperature_setpoint = self.mock_temp
                        actual_temperature = self.mock_temp
                        # A new set point invalidates any previous lock; let the
                        # convergence simulation run again (unless a status is forced).
                        if self._debug_forced_temp_status is None:
                            self._debug_temp_status = "unlocked"
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
                    self.temperature_set_finished.emit(float(actual_temperature))

                if request_temp:
                    if self.debug:
                        temp, status = self._debug_temperature_sample()
                        self.temperature_ready.emit(temp, status)
                    else:
                        try:
                            with self._hw_lock:
                                temp = float(self.cam.get_attribute_value("Sensor Temperature Reading"))
                                status = "unsupported"
                                if self._temp_status_supported:
                                    status = "unknown"
                                    try:
                                        raw_status = self.cam.get_attribute_value("Sensor Temperature Status")
                                        normalized = str(raw_status).strip().lower()
                                        if normalized in ("locked", "unlocked", "faulted"):
                                            status = normalized
                                    except Exception as e:
                                        print(f"Failed to read temperature status: {e}")
                            self.temperature_ready.emit(temp, status)
                        except Exception as e:
                            print(f"Failed to read temperature: {e}")
                            fallback_status = "unknown" if self._temp_status_supported else "unsupported"
                            self.temperature_ready.emit(-999.0, fallback_status)
                    with self._lock:
                        self.request_temp = False

                if status_requested:
                    if self.debug:
                        self.status_ready.emit(self._debug_status_snapshot())
                    else:
                        try:
                            with self._hw_lock:
                                snapshot = self._build_status_snapshot()
                            self.status_ready.emit(snapshot)
                        except Exception as e:
                            print(f"Failed to query camera status: {e}")
                            self.status_ready.emit({"Error": [("Failed to query camera status", str(e))]})
                    with self._lock:
                        self.status_requested = False

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
                                raise RuntimeError("PICam snap returned no frame")
                            if self._is_all_zero_frame(data):
                                _consec_zero_frames += 1
                                print(
                                    "Invalid all-zero PICam frame rejected "
                                    f"({_consec_zero_frames}/{_ZERO_FRAMES_BEFORE_RECOVERY}); "
                                    f"{self._frame_diagnostics(data)}"
                                )
                                if _consec_zero_frames < _ZERO_FRAMES_BEFORE_RECOVERY:
                                    time.sleep(0.05)
                                    continue

                                if _recovery_attempts >= _MAX_ACQUISITION_RECOVERIES:
                                    error_msg = (
                                        "PICam repeatedly returned all-zero frames after "
                                        f"{_MAX_ACQUISITION_RECOVERIES} recovery attempts. "
                                        "Check the GigE NIC/eBUS driver and camera firmware."
                                    )
                                    print(error_msg)
                                    with self._lock:
                                        self.is_measuring = False
                                    self.acquisition_failed.emit(error_msg)
                                    _consec_zero_frames = 0
                                    _recovery_attempts = 0
                                    continue

                                _recovery_attempts += 1
                                self._recover_acquisition(
                                    "three consecutive all-zero frames", _recovery_attempts
                                )
                                _consec_zero_frames = 0
                                _consec_errors = 0
                                continue

                            _consec_zero_frames = 0
                            _recovery_attempts = 0
                            if self.roi_mode == "2d":
                                self.data_ready.emit("2d", data)
                            else:
                                self.data_ready.emit("1d", self._extract_spectrum(data))
                        _consec_errors = 0
                    except Exception as e:
                        error_code = getattr(e, "code", None)
                        print(
                            "Failed to acquire camera data"
                            f" (PICam error code={error_code}): {e}"
                        )
                        _consec_errors += 1
                        if (
                            _consec_errors >= _ERRORS_BEFORE_RECOVERY
                            and _recovery_attempts < _MAX_ACQUISITION_RECOVERIES
                        ):
                            _recovery_attempts += 1
                            try:
                                self._recover_acquisition(
                                    f"{_consec_errors} consecutive acquisition errors "
                                    f"(last PICam code={error_code})",
                                    _recovery_attempts,
                                )
                                _consec_errors = 0
                                _consec_zero_frames = 0
                                continue
                            except Exception as recovery_error:
                                print(f"PICam recovery failed: {recovery_error}")

                        if _consec_errors >= _ACQUISITION_ERRORS_BEFORE_STOP:
                            error_msg = (
                                "Stopping acquisition after "
                                f"{_consec_errors} consecutive camera errors. Last error: {e}"
                            )
                            print(error_msg)
                            with self._lock:
                                self.is_measuring = False
                            self.acquisition_failed.emit(error_msg)
                            _consec_errors = 0
                            _consec_zero_frames = 0
                            _recovery_attempts = 0
                        time.sleep(0.05)
                else:
                    _consec_errors = 0
                    _consec_zero_frames = 0
                    _recovery_attempts = 0
                    was_measuring = False
                    time.sleep(0.05)

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

    def request_status(self):
        """Request a camera status snapshot (thread-safe); result arrives via status_ready.

        Only meaningful while idle: the GUI is expected to keep the triggering button
        disabled whenever `is_measuring` is True (see CameraStatusDialog)."""
        with self._lock:
            self.status_requested = True

    def get_cached_hardware_metadata(self):
        """Return acquisition metadata without touching the PICam SDK."""
        with self._lock:
            return {
                "identity": dict(self._metadata_identity),
                "detector_size_px": {"width": self.det_width, "height": self.det_height},
                "pixel_pitch_um": dict(self._metadata_pixel_pitch_um),
                "exposure_s": float(self.current_exposure),
                "temperature": {"setpoint_c": float(self.current_temperature_setpoint)},
            }

    def update_exposure(self, exp_time):
        """Request an exposure change (thread-safe) and return a token identifying
        this request. Pass the token to wait_for_exposure_applied() to block until
        run() has actually pushed it to hardware (or a newer request superseded it)."""
        with self._lock:
            self.new_exposure = exp_time
            self._exposure_request_seq += 1
            return self._exposure_request_seq

    def wait_for_exposure_applied(self, seq, timeout=None):
        """Block until the exposure request identified by `seq` (the return value of
        update_exposure()) has been applied by run(), or `timeout` seconds elapse.

        Returns True if applied, False on timeout. Resolves as soon as run() finishes
        processing the request, whether or not the hardware call itself succeeded, so
        this never hangs waiting for a request that failed on hardware.
        """
        with self._lock:
            return self._lock.wait_for(lambda: self._exposure_applied_seq >= seq, timeout=timeout)

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
            # Block until run() has actually pushed the new exposure to hardware, rather
            # than hoping a fixed sleep is long enough. If run() is mid-snap() on a
            # long-running continuous measurement (holding _hw_lock for the old exposure's
            # duration), it can't reach the top of its loop to apply the change until that
            # snap finishes, so the wait must be bounded by the old exposure, not a flat 0.1s.
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
            if settings_changed:
                try:
                    with self._hw_lock:
                        self._apply_camera_settings()
                except Exception as e:
                    print(f"Failed to apply ROI settings: {e}")
                    return None
                with self._lock:
                    self.settings_changed = False

            try:
                snap_timeout = self.current_exposure + 10
                for attempt in range(2):
                    with self._hw_lock:
                        data = self.cam.snap(timeout=snap_timeout)
                    if data is not None and not self._is_all_zero_frame(data):
                        return data
                    detail = (
                        "no frame" if data is None else self._frame_diagnostics(data)
                    )
                    print(
                        "Invalid PICam frame rejected during single-image acquisition "
                        f"(attempt {attempt + 1}/2): {detail}"
                    )
                    if attempt == 0:
                        self._reset_acquisition_state()
                return None
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
