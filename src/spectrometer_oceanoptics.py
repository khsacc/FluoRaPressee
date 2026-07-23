from PyQt6.QtCore import QThread, pyqtSignal

from src.instrument_status import unavailable_device

# Tolerance (nm) used by set_wavelength() to decide whether a requested centre wavelength
# matches the device's actual fixed position - see work/work_OceanOptics.md 方針2/Step 2 for
# why this must reject mismatches rather than silently accepting any value.
_WAVELENGTH_MATCH_TOLERANCE_NM = 1e-3


class SpectrometerControllerOceanOptics:
    """Ocean Opticsは物理的に固定された分光器(可動グレーティング/中心波長を持たない)なので、
    このコントローラはハードウェアに一切触れないno-opとして実装する。

    実際のUSB接続・識別情報・native wavelength配列は全て`CameraThreadOceanOptics`
    (src/camera_oceanoptics.py)が所有する。これは1台の物理USBデバイスをこの2つのオブジェクトが
    別々に開こうとして衝突するのを避けるための設計であり、詳細は
    work/work_OceanOptics.md 方針2を参照。
    """

    def __init__(self, config=None, debug=False):
        self.debug = debug
        self.config = config or {}

        # There is nothing to actually connect to at this layer (see class docstring), so
        # this is always True - unlike Andor/Princeton, there is no "dummy mode" distinction
        # for SpectrometerMoveThread.run() to branch on.
        self.is_initialized = True

        default_center = self.config.get("default_center_wavelength_nm")
        self._current_wavelength_nm = float(default_center) if default_center is not None else 0.0
        self._current_grating = 1

    def initialize(self):
        self.is_initialized = True
        return True

    def get_wavelength(self):
        return self._current_wavelength_nm

    def get_grating(self):
        return self._current_grating

    def get_gratings(self):
        """Matches the single synthetic grating entry expected in spectrometerConfig.json
        (方針3) so the startup grating-mismatch check in ui.py never fires for Ocean Optics."""
        return [{"index": 1, "grooves": 0}]

    def set_reference_center(self, wavelength_nm):
        """GUI専用の内部API: カメラ接続後に実測したnative wavelengthの中央値を1回だけ
        登録するために使う(Step 4)。"移動"ではなく"実測値の記録"であることを明示するため
        set_wavelength()とは別名にしてある。物理操作は行わない。"""
        self._current_wavelength_nm = float(wavelength_nm)

    def set_wavelength(self, wavelength_nm):
        """固定分光器なので、要求値が現在の固定値と一致する場合のみ成功を返す。

        当初案(渡された値をそのまま内部状態へ上書きして常に成功を返す)は採用しない:
        Configuration Loadや将来のAPI操作が異なるtarget_center_wavelength_nmを持つ設定の
        適用を試みた場合、物理的に移動できないOcean Opticsが「移動成功」を返してしまうと、
        実際のデータとは異なる中心波長を前提にした較正がそのまま適用されてしまうため。
        """
        return abs(float(wavelength_nm) - self._current_wavelength_nm) < _WAVELENGTH_MATCH_TOLERANCE_NM

    def set_grating(self, grating_index):
        return int(grating_index) == self._current_grating

    def get_device_identity(self):
        """常に空を返す: 実体の識別情報はカメラ側(identity_ready)が唯一の情報源であり、
        ここで別途ハードウェアへ問い合わせることはしない(方針2)。"""
        return {"model": None, "serial_number": None}

    def get_cached_hardware_metadata(self):
        return {
            "serial_number": None,
            "grating": {"index": self._current_grating, "grooves_per_mm": 0},
            "center_wavelength_nm": self._current_wavelength_nm,
            "wavelength_limits_nm": None,
        }

    def get_capabilities(self):
        return {"supports_grating": False, "supports_movable_center": False}

    def get_status_snapshot(self):
        return unavailable_device(
            "oceanoptics",
            "Integrated with the camera; there is no separate spectrometer connection.",
        )

    def close(self):
        pass


class SpectrometerMoveThread(QThread):
    finished_signal = pyqtSignal()

    def __init__(self, spec_ctrl, grating_index, wavelength):
        super().__init__()
        self.spec_ctrl = spec_ctrl
        self.grating_index = grating_index
        self.wavelength = wavelength
        self.success = None
        self.error_message = ""
        self.cancelled = False

    def run(self):
        # Unlike spectrometer_andor.py's SpectrometerMoveThread (which never sets
        # self.success at all) this must check both return values, since
        # SpectrometerControllerOceanOptics.set_wavelength()/set_grating() legitimately
        # return False for a mismatched request - see work/work_OceanOptics.md 方針6.
        grating_ok = self.spec_ctrl.set_grating(self.grating_index)
        wavelength_ok = self.spec_ctrl.set_wavelength(self.wavelength)
        self.success = grating_ok and wavelength_ok
        if not self.success:
            self.error_message = (
                "Ocean Optics is a fixed spectrometer; the requested grating/centre "
                "wavelength does not match the connected device's fixed position."
            )
        self.finished_signal.emit()
