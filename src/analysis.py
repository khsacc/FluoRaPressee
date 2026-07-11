import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning
from scipy.signal import find_peaks
from typing import Tuple, Dict, Optional
import warnings

class DataAnalyzer:
    """リアルタイムスペクトル解析・フィッティング処理を行うクラス"""
    
    # フィッティングのための定数
    MIN_FIT_POINTS = 10
    FWHM_FRACTION = 0.02  # X軸範囲のこの割合をFWHM初期値とする
    FWHM_MIN = 0.0001
    PEAK_DISTANCE = 5  # find_peaks で用いるピーク間の最小距離（ピクセル）
    PEAK_PROMINENCE_FACTOR = 0.1  # 振幅のこの割合をプロミネンス閾値とする
    PEAK_SPACING_FACTOR = 0.1  # ダブルピーク初期値の間隔係数
    SECOND_PEAK_AMP_FACTOR = 0.5  # 第2ピークの振幅推定係数
    PSEUDO_VOIGT_ETA_INIT = 0.5  # Pseudo Voigt の混合比初期値
    PSEUDO_VOIGT_ETA_MIN = 0.0
    PSEUDO_VOIGT_ETA_MAX = 1.0
    MOFFAT_BETA_INIT = 2.0
    MOFFAT_BETA_MIN = 0.1
    MOFFAT_BETA_MAX = 100.0
    MIN_PEAK_COUNT = 1
    MAX_PEAK_COUNT = 5

    def __init__(self):
        """DataAnalyzer を初期化する"""
        pass

    # ==========================================
    # --- ベース関数群 ---
    # ==========================================
    def gaussian(self, x, a, x0, fwhm, offset):
        """fwhmを用いたガウス関数"""
        return a * np.exp(-4 * np.log(2) * ((x - x0) / fwhm)**2) + offset

    def lorentzian(self, x, a, x0, fwhm, offset):
        """fwhmを用いたローレンツ関数"""
        return a / (1 + 4 * ((x - x0) / fwhm)**2) + offset

    def pseudo_voigt(self, x, a, x0, fwhm, eta, offset):
        """ガウス関数とローレンツ関数を合成したPseudo-Voigt関数"""
        g_val = self.gaussian(x, a, x0, fwhm, offset=0.0)
        l_val = self.lorentzian(x, a, x0, fwhm, offset=0.0)
        return (1 - eta) * g_val + eta * l_val + offset

    def moffat(self, x, a, x0, width, beta, offset):
        """Moffat function with a shared background offset."""
        u = ((x - x0) / width) ** 2
        return a / (1 + u) ** beta + offset

    def double_gaussian(self, x, a1, x01, fwhm1, a2, x02, fwhm2, offset):
        return self.gaussian(x, a1, x01, fwhm1, 0) + self.gaussian(x, a2, x02, fwhm2, 0) + offset

    def double_lorentzian(self, x, a1, x01, fwhm1, a2, x02, fwhm2, offset):
        return self.lorentzian(x, a1, x01, fwhm1, 0) + self.lorentzian(x, a2, x02, fwhm2, 0) + offset

    def double_pseudo_voigt(self, x, a1, x01, fwhm1, eta1, a2, x02, fwhm2, eta2, offset):
        return self.pseudo_voigt(x, a1, x01, fwhm1, eta1, 0) + self.pseudo_voigt(x, a2, x02, fwhm2, eta2, 0) + offset

    def _fit_strict(self, func, x, y, p0, bounds):
        """curve_fit ラッパー。scipy は共分散行列を推定できない場合などに
        OptimizeWarning を警告として発するだけで例外にはしないため、
        このスコープ内だけ warning を例外に変換して呼び出し元の except で拾えるようにする。"""
        with warnings.catch_warnings():
            warnings.simplefilter("error", OptimizeWarning)
            return curve_fit(func, x, y, p0=p0, bounds=bounds)

    def _base_function_value(self, func_type, x, params, offset=0.0):
        if func_type == "Gauss":
            return self.gaussian(x, params[0], params[1], params[2], offset)
        if func_type == "Lorentz":
            return self.lorentzian(x, params[0], params[1], params[2], offset)
        if func_type == "Pseudo Voigt":
            return self.pseudo_voigt(x, params[0], params[1], params[2], params[3], offset)
        if func_type == "Moffat":
            return self.moffat(x, params[0], params[1], params[2], params[3], offset)
        raise ValueError(f"Unknown fitting function: {func_type!r}")

    def _params_per_peak(self, func_type):
        return 3 if func_type in ["Gauss", "Lorentz"] else 4

    def _multi_peak_model(self, func_type, peak_count):
        params_per_peak = self._params_per_peak(func_type)

        def model(x, *params):
            offset = params[-1]
            y = np.zeros_like(x, dtype=np.float64) + offset
            for i in range(peak_count):
                start = i * params_per_peak
                y += self._base_function_value(
                    func_type, x, params[start:start + params_per_peak], offset=0.0
                )
            return y

        return model

    def _component_curve(self, func_type, x, peak_params, offset):
        return self._base_function_value(func_type, x, peak_params, offset=offset)

    def _initial_peak_positions(self, x_fit, y_fit, peak_count, amp_guess, offset_guess):
        peaks, _ = find_peaks(
            y_fit,
            distance=self.PEAK_DISTANCE,
            prominence=amp_guess * self.PEAK_PROMINENCE_FACTOR,
        )
        candidates = []
        if len(peaks) > 0:
            for p in sorted(peaks, key=lambda idx: y_fit[idx], reverse=True):
                candidates.append((float(x_fit[p]), float(max(y_fit[p] - offset_guess, amp_guess * 0.1))))

        max_idx = int(np.argmax(y_fit))
        candidates.append((float(x_fit[max_idx]), float(max(y_fit[max_idx] - offset_guess, amp_guess))))

        if peak_count > 1:
            fallback_positions = np.linspace(float(np.min(x_fit)), float(np.max(x_fit)), peak_count + 2)[1:-1]
        else:
            fallback_positions = [float(x_fit[max_idx])]
        for pos in fallback_positions:
            candidates.append((float(pos), float(max(amp_guess * self.SECOND_PEAK_AMP_FACTOR, amp_guess * 0.1))))

        selected = []
        min_sep = max((float(np.max(x_fit)) - float(np.min(x_fit))) * 1e-6, 1e-12)
        for pos, amp in candidates:
            if all(abs(pos - existing[0]) > min_sep for existing in selected):
                selected.append((pos, amp))
            if len(selected) >= peak_count:
                break

        while len(selected) < peak_count:
            idx = len(selected)
            pos = float(fallback_positions[min(idx, len(fallback_positions) - 1)])
            selected.append((pos, float(max(amp_guess * self.SECOND_PEAK_AMP_FACTOR, amp_guess * 0.1))))

        return selected

    def _sort_peak_records(self, records, sort_order):
        reverse = sort_order in ["x_desc", "intensity_desc"]
        if sort_order in ["x_desc", "x_asc"]:
            key = lambda item: item["position"]
        elif sort_order in ["intensity_desc", "intensity_asc"]:
            key = lambda item: item["intensity"]
        else:
            key = lambda item: item["position"]
            reverse = True
        return sorted(records, key=key, reverse=reverse)

    def _add_legacy_peak_keys(self, res, peaks):
        if not peaks:
            return
        res["Peak"] = peaks[0]["position"]
        res["Peak_Err"] = peaks[0]["position_err"]
        res["Width"] = peaks[0]["width"]
        res["Width_Err"] = peaks[0]["width_err"]
        for i, peak in enumerate(peaks, start=1):
            res[f"Peak{i}"] = peak["position"]
            res[f"Peak{i}_Err"] = peak["position_err"]
            res[f"Width{i}"] = peak["width"]
            res[f"Width{i}_Err"] = peak["width_err"]

    # ==========================================
    # --- フィッティング処理 ---
    # ==========================================
    def fit_spectrum(self, x_data: np.ndarray, y_data: np.ndarray, func_type: str = "Pseudo Voigt",
                     fit_start: Optional[float] = None, fit_end: Optional[float] = None,
                     peak_count: int = 1, peak_sort_order: str = "x_desc") -> Tuple:
        """スペクトルのピークフィッティングを行う（指定されたX軸の範囲内で実行）
        
        Args:
            x_data: X 軸データ
            y_data: Y 軸データ
            func_type: フィッティング関数型 ("Pseudo Voigt", "Moffat", "Gauss", "Lorentz")
            fit_start: フィッティング範囲の開始値
            fit_end: フィッティング範囲の終了値
            peak_count: フィットするピーク数 (1-5)
            peak_sort_order: ピーク番号の並び順
            
        Returns:
            (x_fit, y_fit_curve, res) のタプル。フィッティング失敗時は (None, None, None)
        """
        
        # 範囲によるマスクの作成
        if fit_start is not None and fit_end is not None:
            start_val = min(fit_start, fit_end)
            end_val = max(fit_start, fit_end)
            mask = (x_data >= start_val) & (x_data <= end_val)
        else:
            mask = np.ones(len(x_data), dtype=bool)

        x_fit = x_data[mask]
        y_fit = y_data[mask]

        if len(x_fit) < self.MIN_FIT_POINTS:
            return None, None, None

        amp_guess = np.max(y_fit) - np.min(y_fit)
        offset_guess = np.min(y_fit)
        x_range = np.max(x_fit) - np.min(x_fit)
        
        # FWHMの初期値はX軸のスケールに依存するため、範囲の設定割合程度と推測する
        fwhm_guess = x_range * self.FWHM_FRACTION
        if fwhm_guess <= 0: fwhm_guess = 1.0
        width_upper = max(x_range, self.FWHM_MIN * 10)
        fwhm_guess = min(max(fwhm_guess, self.FWHM_MIN), width_upper)
        
        peak_count = int(peak_count)
        if peak_count < self.MIN_PEAK_COUNT or peak_count > self.MAX_PEAK_COUNT:
            raise ValueError(f"peak_count must be between {self.MIN_PEAK_COUNT} and {self.MAX_PEAK_COUNT}")
        if func_type not in ["Pseudo Voigt", "Moffat", "Gauss", "Lorentz"]:
            raise ValueError(f"Unknown fitting function: {func_type!r}")
        
        try:
            params_per_peak = self._params_per_peak(func_type)
            initial_peaks = self._initial_peak_positions(x_fit, y_fit, peak_count, amp_guess, offset_guess)
            p0 = []
            lower = []
            upper = []
            for peak_x, peak_amp in initial_peaks:
                p0.extend([peak_amp, peak_x, fwhm_guess])
                lower.extend([0, min(x_fit), self.FWHM_MIN])
                upper.extend([np.inf, max(x_fit), width_upper])
                if func_type == "Pseudo Voigt":
                    p0.append(self.PSEUDO_VOIGT_ETA_INIT)
                    lower.append(self.PSEUDO_VOIGT_ETA_MIN)
                    upper.append(self.PSEUDO_VOIGT_ETA_MAX)
                elif func_type == "Moffat":
                    p0.append(self.MOFFAT_BETA_INIT)
                    lower.append(self.MOFFAT_BETA_MIN)
                    upper.append(self.MOFFAT_BETA_MAX)

            p0.append(offset_guess)
            lower.append(-np.inf)
            upper.append(np.inf)

            model = self._multi_peak_model(func_type, peak_count)
            popt, pcov = self._fit_strict(model, x_fit, y_fit, p0, (lower, upper))
            y_fit_curve = model(x_fit, *popt)
            perr = np.sqrt(np.maximum(np.diag(pcov), 0))

            offset = popt[-1]
            records = []
            for i in range(peak_count):
                start = i * params_per_peak
                peak_params = popt[start:start + params_per_peak]
                peak_errs = perr[start:start + params_per_peak]
                records.append({
                    "position": peak_params[1],
                    "position_err": peak_errs[1],
                    "width": peak_params[2],
                    "width_err": peak_errs[2],
                    "amplitude": peak_params[0],
                    "amplitude_err": peak_errs[0],
                    "intensity": peak_params[0],
                    "params": peak_params.copy(),
                    "errors": peak_errs.copy(),
                    "y_fit": self._component_curve(func_type, x_fit, peak_params, offset),
                })

            sorted_peaks = self._sort_peak_records(records, peak_sort_order)
            for i, peak in enumerate(sorted_peaks, start=1):
                peak["index"] = i

            res = {
                "is_double": peak_count == 2,
                "is_multi": peak_count > 1,
                "peak_count": peak_count,
                "peak_sort_order": peak_sort_order,
                "peaks": [
                    {k: v for k, v in peak.items() if k not in ["params", "errors", "y_fit"]}
                    for peak in sorted_peaks
                ],
            }
            for i, peak in enumerate(sorted_peaks, start=1):
                res[f"y_fit{i}"] = peak["y_fit"]
            self._add_legacy_peak_keys(res, sorted_peaks)

            # R2計算
            residuals = y_fit - y_fit_curve
            ss_res = np.sum(residuals**2)
            ss_tot = np.sum((y_fit - np.mean(y_fit))**2)
            res["R2"] = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            return x_fit, y_fit_curve, res

        except OptimizeWarning as w:
            warnings.warn(f"Optimization warning in fit_spectrum ({func_type}): {w}")
            return None, None, None
        except RuntimeError as e:
            print(f"RuntimeError in fitting ({func_type}): {e}")
            return None, None, None
        except ValueError as e:
            print(f"ValueError in fitting ({func_type}): {e}")
            return None, None, None
        except Exception as e:
            print(f"Unexpected error in fitting ({func_type}): {e}")
            return None, None, None
