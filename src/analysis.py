import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning
from scipy.signal import find_peaks, savgol_filter
from typing import Tuple, Dict, Optional
import warnings

class DataAnalyzer:
    """リアルタイムスペクトル解析・フィッティング処理を行うクラス"""
    
    # Constants used for fitting
    MIN_FIT_POINTS = 10
    FWHM_FRACTION = 0.02  # Initial FWHM guess as a fraction of the X-axis range
    FWHM_MIN = 0.0001
    PEAK_DISTANCE = 5  # Minimum distance between peaks (pixels), passed to find_peaks
    PEAK_PROMINENCE_FACTOR = 0.1  # Prominence threshold as a fraction of the amplitude guess
    # Smoothing applied only to the signal handed to find_peaks (never to the data that gets
    # fitted), to keep per-pixel noise from being mistaken for extra peaks on spectrometers with
    # many pixels per resolution element. Sized relative to the estimated FWHM in pixel units
    # (derived from the actual x-axis spacing) so coarse-pixel detectors - where a real FWHM may
    # span only a handful of pixels, e.g. closely spaced ruby R1/R2 lines - are left untouched.
    PEAK_SEARCH_MIN_FWHM_PX = 8  # below this estimated peak width (pixels), skip smoothing entirely
    PEAK_SEARCH_SMOOTH_DIVISOR = 5  # smoothing window = estimated FWHM (pixels) / this divisor
    PEAK_SEARCH_SMOOTH_MAX_WINDOW = 15
    PEAK_SEARCH_SMOOTH_POLYORDER = 2
    PEAK_SPACING_FACTOR = 0.1  # Spacing factor for double-peak initial guesses (currently unused)
    SECOND_PEAK_AMP_FACTOR = 0.5  # Amplitude guess factor for peak candidates beyond the primary one
    PSEUDO_VOIGT_ETA_INIT = 0.5  # Initial mixing ratio for the Pseudo Voigt function
    PSEUDO_VOIGT_ETA_MIN = 0.0
    PSEUDO_VOIGT_ETA_MAX = 1.0
    MOFFAT_BETA_INIT = 2.0
    MOFFAT_BETA_MIN = 0.1
    MOFFAT_BETA_MAX = 100.0
    MIN_PEAK_COUNT = 1
    MAX_PEAK_COUNT = 5
    BASELINE_MODE_DEGREES = {
        "Constant": 0,
        "Linear": 1,
        "Quadratic": 2,
    }
    AUTO_BASELINE_MODE = "Auto Polynomial"
    AUTO_BASELINE_BIC_THRESHOLD = 6.0
    DIAMOND_EDGE_FUNCTION = "Diamond Raman Edge"
    EDGE_SMOOTH_WIDTH = 2.0  # cm^-1; only used before numerical differentiation
    EDGE_LOCAL_HALF_WIDTH = 6.0  # cm^-1 around the strongest negative derivative
    EDGE_MAX_SMOOTH_WINDOW = 51

    def __init__(self):
        """DataAnalyzer を初期化する"""
        pass

    # ==========================================
    # --- Base peak-shape functions ---
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

    def _normalize_baseline_model(self, baseline_model):
        normalized = str(baseline_model).strip().lower().replace("_", " ")
        aliases = {
            "constant": "Constant",
            "linear": "Linear",
            "quadratic": "Quadratic",
            "auto polynomial": self.AUTO_BASELINE_MODE,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            allowed = list(self.BASELINE_MODE_DEGREES) + [self.AUTO_BASELINE_MODE]
            raise ValueError(
                f"Unknown baseline model: {baseline_model!r}; expected one of {allowed}"
            ) from exc

    def _baseline_curve(self, x, coefficients, x_min, x_max):
        """Evaluate a degree 0-2 Chebyshev baseline on x normalized to [-1, 1]."""
        x_span = float(x_max) - float(x_min)
        if x_span <= 0:
            raise ValueError("baseline x range must be greater than zero")

        u = 2.0 * (np.asarray(x, dtype=np.float64) - float(x_min)) / x_span - 1.0
        baseline = np.zeros_like(u, dtype=np.float64) + coefficients[0]
        if len(coefficients) >= 2:
            baseline += coefficients[1] * u
        if len(coefficients) >= 3:
            baseline += coefficients[2] * (2.0 * u**2 - 1.0)
        return baseline

    def _multi_peak_model(self, func_type, peak_count, baseline_degree=0,
                          x_min=None, x_max=None):
        params_per_peak = self._params_per_peak(func_type)
        baseline_param_count = baseline_degree + 1

        def model(x, *params):
            baseline_coefficients = params[-baseline_param_count:]
            y = self._baseline_curve(x, baseline_coefficients, x_min, x_max)
            for i in range(peak_count):
                start = i * params_per_peak
                y += self._base_function_value(
                    func_type, x, params[start:start + params_per_peak], offset=0.0
                )
            return y

        return model

    def _component_curve(self, func_type, x, peak_params, baseline):
        return baseline + self._base_function_value(
            func_type, x, peak_params, offset=0.0
        )

    def _fit_baseline_candidate(self, func_type, peak_count, baseline_degree,
                                x_fit, y_fit, peak_p0, peak_lower, peak_upper,
                                offset_guess, nested_p0=None):
        """Fit one peak-plus-polynomial candidate and return its numerical results."""
        baseline_param_count = baseline_degree + 1
        if nested_p0 is None:
            p0 = list(peak_p0) + [offset_guess] + [0.0] * baseline_degree
        else:
            p0 = list(nested_p0) + [0.0]

        lower = list(peak_lower) + [-np.inf] * baseline_param_count
        upper = list(peak_upper) + [np.inf] * baseline_param_count
        model = self._multi_peak_model(
            func_type,
            peak_count,
            baseline_degree=baseline_degree,
            x_min=float(np.min(x_fit)),
            x_max=float(np.max(x_fit)),
        )
        popt, pcov = self._fit_strict(model, x_fit, y_fit, p0, (lower, upper))
        y_fit_curve = model(x_fit, *popt)

        if not np.all(np.isfinite(popt)) or not np.all(np.isfinite(y_fit_curve)):
            raise ValueError("fit returned non-finite parameters or curve")
        if not np.all(np.isfinite(pcov)):
            raise ValueError("fit returned a non-finite covariance matrix")

        residuals = y_fit - y_fit_curve
        rss = float(np.sum(residuals**2))
        if not np.isfinite(rss):
            raise ValueError("fit returned a non-finite residual sum of squares")
        rss_floor = np.finfo(np.float64).eps * max(float(np.sum(y_fit**2)), 1.0)
        rss_for_bic = max(rss, rss_floor)
        parameter_count = len(popt)
        bic = len(y_fit) * np.log(rss_for_bic / len(y_fit)) + parameter_count * np.log(len(y_fit))

        return {
            "degree": baseline_degree,
            "model": model,
            "popt": popt,
            "pcov": pcov,
            "perr": np.sqrt(np.maximum(np.diag(pcov), 0)),
            "y_fit_curve": y_fit_curve,
            "rss": rss,
            "bic": float(bic),
        }

    def _smoothed_for_peak_search(self, x_fit, y_fit, fwhm_guess):
        """find_peaks に渡す信号だけを平滑化する（フィット本体には常に生データを使う）。
        平滑化窓は x_fit の実際の間隔から求めたピクセル分散を使い、推定FWHMをピクセル数に
        換算して決める。ピクセル数の粗い分光器（FWHMが数ピクセルしかない場合）ではウィンドウが
        最小しきい値を下回り、平滑化そのものをスキップする。"""
        n = len(y_fit)
        if fwhm_guess is None or n < 2 * self.PEAK_SEARCH_MIN_FWHM_PX:
            return y_fit

        pixel_steps = np.abs(np.diff(x_fit))
        pixel_steps = pixel_steps[pixel_steps > 0]
        if len(pixel_steps) == 0:
            return y_fit
        pixel_dispersion = float(np.median(pixel_steps))
        fwhm_guess_px = fwhm_guess / pixel_dispersion

        if fwhm_guess_px < self.PEAK_SEARCH_MIN_FWHM_PX:
            return y_fit

        window = int(round(fwhm_guess_px / self.PEAK_SEARCH_SMOOTH_DIVISOR))
        max_window = n if n % 2 == 1 else n - 1
        window = max(3, min(window, self.PEAK_SEARCH_SMOOTH_MAX_WINDOW, max_window))
        if window % 2 == 0:
            window -= 1
        if window < 3:
            return y_fit

        polyorder = min(self.PEAK_SEARCH_SMOOTH_POLYORDER, window - 1)
        try:
            return savgol_filter(y_fit, window_length=window, polyorder=polyorder)
        except ValueError:
            return y_fit

    def _initial_peak_positions(self, x_fit, y_fit, peak_count, amp_guess, offset_guess, fwhm_guess=None):
        y_search = self._smoothed_for_peak_search(x_fit, y_fit, fwhm_guess)
        peaks, _ = find_peaks(
            y_search,
            distance=self.PEAK_DISTANCE,
            prominence=amp_guess * self.PEAK_PROMINENCE_FACTOR,
        )
        candidates = []
        if len(peaks) > 0:
            for p in sorted(peaks, key=lambda idx: y_search[idx], reverse=True):
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
    # --- Fitting ---
    # ==========================================
    def fit_diamond_raman_edge(self, x_data: np.ndarray, y_data: np.ndarray,
                               fit_start: Optional[float] = None,
                               fit_end: Optional[float] = None) -> Tuple:
        """Fit the stressed-diamond high-frequency Raman edge.

        The spectrum is interpolated onto an evenly spaced grid, smoothed only
        for differentiation, and ``-dI/dnu`` is fitted locally with a
        pseudo-Voigt profile plus a linear derivative baseline.  The fitted
        profile centre is the Raman-edge position used by the pressure scales.
        """
        x = np.asarray(x_data, dtype=np.float64)
        y = np.asarray(y_data, dtype=np.float64)
        valid = np.isfinite(x) & np.isfinite(y)
        if fit_start is not None and fit_end is not None:
            start_val, end_val = sorted((float(fit_start), float(fit_end)))
            valid &= (x >= start_val) & (x <= end_val)
        x = x[valid]
        y = y[valid]
        if len(x) < self.MIN_FIT_POINTS:
            return None, None, None

        order = np.argsort(x)
        x = x[order]
        y = y[order]
        x, unique_indices = np.unique(x, return_index=True)
        y = y[unique_indices]
        if len(x) < self.MIN_FIT_POINTS or float(np.ptp(x)) <= 0:
            return None, None, None

        try:
            x_uniform = np.linspace(float(x[0]), float(x[-1]), len(x))
            y_uniform = np.interp(x_uniform, x, y)
            dx = float(x_uniform[1] - x_uniform[0])

            window = int(round(self.EDGE_SMOOTH_WIDTH / dx))
            window = max(5, min(window, self.EDGE_MAX_SMOOTH_WINDOW, len(x_uniform) - 1))
            if window % 2 == 0:
                window -= 1
            if window < 5:
                return None, None, None
            y_smooth = savgol_filter(y_uniform, window_length=window, polyorder=min(3, window - 1))
            derivative = -np.gradient(y_smooth, x_uniform)

            # Savitzky-Golay and numerical differentiation are least reliable at
            # the ROI boundaries.  Excluding their half-window prevents a hard
            # user-selected range edge from being mistaken for the diamond edge.
            derivative_for_search = derivative.copy()
            margin = min(max(window // 2, 2), len(derivative_for_search) // 4)
            derivative_for_search[:margin] = -np.inf
            derivative_for_search[-margin:] = -np.inf
            edge_guess_index = int(np.argmax(derivative_for_search))
            edge_guess = float(x_uniform[edge_guess_index])
            local_mask = np.abs(x_uniform - edge_guess) <= self.EDGE_LOCAL_HALF_WIDTH
            minimum_local_points = 12
            if int(np.count_nonzero(local_mask)) < minimum_local_points:
                lo = max(0, edge_guess_index - minimum_local_points // 2)
                hi = min(len(x_uniform), lo + minimum_local_points)
                lo = max(0, hi - minimum_local_points)
                local_mask = np.zeros(len(x_uniform), dtype=bool)
                local_mask[lo:hi] = True

            x_local = x_uniform[local_mask]
            d_local = derivative[local_mask]
            if len(x_local) < self.MIN_FIT_POINTS or float(np.ptp(x_local)) <= 0:
                return None, None, None

            x_mid = float(np.mean(x_local))
            x_span = float(np.ptp(x_local))

            def edge_model(x_values, amplitude, centre, fwhm, eta, offset, slope):
                profile = self.pseudo_voigt(
                    x_values, amplitude, centre, fwhm, eta, offset=0.0
                )
                return profile + offset + slope * ((x_values - x_mid) / x_span)

            endpoint_count = max(1, min(3, len(d_local) // 4))
            offset_guess = float(np.median(np.r_[d_local[:endpoint_count], d_local[-endpoint_count:]]))
            amplitude_guess = max(float(np.max(d_local) - offset_guess), np.finfo(float).eps)
            fwhm_guess = min(max(2.0, dx * 2.0), x_span)
            p0 = [amplitude_guess, edge_guess, fwhm_guess,
                  self.PSEUDO_VOIGT_ETA_INIT, offset_guess, 0.0]
            bounds = (
                [0.0, float(x_local[0]), max(dx * 0.5, self.FWHM_MIN),
                 self.PSEUDO_VOIGT_ETA_MIN, -np.inf, -np.inf],
                [np.inf, float(x_local[-1]), max(x_span * 2.0, dx),
                 self.PSEUDO_VOIGT_ETA_MAX, np.inf, np.inf],
            )
            popt, pcov = self._fit_strict(edge_model, x_local, d_local, p0, bounds)
            if not np.all(np.isfinite(popt)) or not np.all(np.isfinite(pcov)):
                return None, None, None
            perr = np.sqrt(np.maximum(np.diag(pcov), 0.0))
            derivative_fit = edge_model(x_local, *popt)
            residuals = d_local - derivative_fit
            ss_res = float(np.sum(residuals**2))
            ss_tot = float(np.sum((d_local - np.mean(d_local))**2))
            r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

            edge_record = {
                "index": 1,
                "position": float(popt[1]),
                "position_err": float(perr[1]),
                "width": float(popt[2]),
                "width_err": float(perr[2]),
                "amplitude": float(popt[0]),
                "amplitude_err": float(perr[0]),
                "intensity": float(popt[0]),
            }
            derivative_baseline = popt[4] + popt[5] * ((x_local - x_mid) / x_span)
            res = {
                "analysis_type": "diamond_raman_edge",
                "is_double": False,
                "is_multi": False,
                "peak_count": 1,
                "peak_sort_order": "x_desc",
                "peaks": [edge_record],
                "edge_position": edge_record["position"],
                "edge_position_err": edge_record["position_err"],
                "edge_width": edge_record["width"],
                "edge_width_err": edge_record["width_err"],
                "x_derivative": x_local,
                "y_derivative": d_local,
                "y_derivative_fit": derivative_fit,
                "y_derivative_baseline": derivative_baseline,
                # The regular plot overlays the smoothed source spectrum; the
                # fitted edge centre is shown separately by the UI marker.
                "y_baseline": np.full_like(x_uniform, np.nan),
                "baseline": {
                    "requested": "Derivative Linear",
                    "selected": "Derivative Linear",
                    "degree": 1,
                    "basis": "linear",
                    "coefficients": [float(popt[4]), float(popt[5])],
                    "coefficient_errors": [float(perr[4]), float(perr[5])],
                    "x_min": float(x_local[0]),
                    "x_max": float(x_local[-1]),
                },
                "R2": r_squared,
            }
            self._add_legacy_peak_keys(res, [edge_record])
            return x_uniform, y_smooth, res
        except (OptimizeWarning, RuntimeError, ValueError, FloatingPointError) as exc:
            print(f"Diamond Raman edge fitting failed: {exc}")
            return None, None, None

    def fit_spectrum(self, x_data: np.ndarray, y_data: np.ndarray, func_type: str = "Pseudo Voigt",
                     fit_start: Optional[float] = None, fit_end: Optional[float] = None,
                     peak_count: int = 1, peak_sort_order: str = "x_desc",
                     baseline_model: str = "Constant") -> Tuple:
        """スペクトルのピークフィッティングを行う（指定されたX軸の範囲内で実行）
        
        Args:
            x_data: X 軸データ
            y_data: Y 軸データ
            func_type: フィッティング関数型 ("Pseudo Voigt", "Moffat", "Gauss", "Lorentz")
            fit_start: フィッティング範囲の開始値
            fit_end: フィッティング範囲の終了値
            peak_count: フィットするピーク数 (1-5)
            peak_sort_order: ピーク番号の並び順
            baseline_model: ベースラインモデル
                ("Constant", "Linear", "Quadratic", "Auto Polynomial")
            
        Returns:
            (x_fit, y_fit_curve, res) のタプル。フィッティング失敗時は (None, None, None)
        """
        
        if func_type == self.DIAMOND_EDGE_FUNCTION:
            if int(peak_count) != 1:
                raise ValueError("Diamond Raman Edge fitting requires peak_count=1")
            return self.fit_diamond_raman_edge(x_data, y_data, fit_start, fit_end)

        # Build a mask restricting the data to the requested fit range
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
        
        # The initial FWHM guess depends on the X-axis scale, so estimate it as a fraction of the fit range
        fwhm_guess = x_range * self.FWHM_FRACTION
        if fwhm_guess <= 0: fwhm_guess = 1.0
        width_upper = max(x_range, self.FWHM_MIN * 10)
        fwhm_guess = min(max(fwhm_guess, self.FWHM_MIN), width_upper)
        
        peak_count = int(peak_count)
        if peak_count < self.MIN_PEAK_COUNT or peak_count > self.MAX_PEAK_COUNT:
            raise ValueError(f"peak_count must be between {self.MIN_PEAK_COUNT} and {self.MAX_PEAK_COUNT}")
        if func_type not in ["Pseudo Voigt", "Moffat", "Gauss", "Lorentz"]:
            raise ValueError(f"Unknown fitting function: {func_type!r}")
        requested_baseline = self._normalize_baseline_model(baseline_model)
        
        try:
            params_per_peak = self._params_per_peak(func_type)
            initial_peaks = self._initial_peak_positions(x_fit, y_fit, peak_count, amp_guess, offset_guess, fwhm_guess)
            peak_p0 = []
            peak_lower = []
            peak_upper = []
            for peak_x, peak_amp in initial_peaks:
                peak_p0.extend([peak_amp, peak_x, fwhm_guess])
                peak_lower.extend([0, min(x_fit), self.FWHM_MIN])
                peak_upper.extend([np.inf, max(x_fit), width_upper])
                if func_type == "Pseudo Voigt":
                    peak_p0.append(self.PSEUDO_VOIGT_ETA_INIT)
                    peak_lower.append(self.PSEUDO_VOIGT_ETA_MIN)
                    peak_upper.append(self.PSEUDO_VOIGT_ETA_MAX)
                elif func_type == "Moffat":
                    peak_p0.append(self.MOFFAT_BETA_INIT)
                    peak_lower.append(self.MOFFAT_BETA_MIN)
                    peak_upper.append(self.MOFFAT_BETA_MAX)

            candidate_results = {}
            candidate_failures = []
            if requested_baseline == self.AUTO_BASELINE_MODE:
                nested_p0 = None
                for label, degree in self.BASELINE_MODE_DEGREES.items():
                    parameter_count = len(peak_p0) + degree + 1
                    if len(x_fit) <= parameter_count:
                        candidate_failures.append(label)
                        nested_p0 = None
                        continue
                    try:
                        candidate = self._fit_baseline_candidate(
                            func_type, peak_count, degree, x_fit, y_fit,
                            peak_p0, peak_lower, peak_upper, offset_guess,
                            nested_p0=nested_p0,
                        )
                    except (OptimizeWarning, RuntimeError, ValueError, FloatingPointError):
                        candidate_failures.append(label)
                        nested_p0 = None
                        continue
                    candidate_results[label] = candidate
                    nested_p0 = candidate["popt"]

                if not candidate_results:
                    return None, None, None

                minimum_bic = min(item["bic"] for item in candidate_results.values())
                parsimonious = [
                    (item["degree"], label, item)
                    for label, item in candidate_results.items()
                    if item["bic"] <= minimum_bic + self.AUTO_BASELINE_BIC_THRESHOLD
                ]
                _, selected_baseline, fit_result = min(parsimonious, key=lambda item: item[0])
            else:
                degree = self.BASELINE_MODE_DEGREES[requested_baseline]
                fit_result = self._fit_baseline_candidate(
                    func_type, peak_count, degree, x_fit, y_fit,
                    peak_p0, peak_lower, peak_upper, offset_guess,
                )
                candidate_results[requested_baseline] = fit_result
                selected_baseline = requested_baseline

            popt = fit_result["popt"]
            perr = fit_result["perr"]
            y_fit_curve = fit_result["y_fit_curve"]
            baseline_degree = fit_result["degree"]
            baseline_param_count = baseline_degree + 1
            baseline_coefficients = popt[-baseline_param_count:]
            baseline_errors = perr[-baseline_param_count:]
            y_baseline = self._baseline_curve(
                x_fit, baseline_coefficients, float(np.min(x_fit)), float(np.max(x_fit))
            )
            records = []
            for i in range(peak_count):
                start = i * params_per_peak
                peak_params = popt[start:start + params_per_peak]
                peak_errs = perr[start:start + params_per_peak]
                y_peak = self._base_function_value(
                    func_type, x_fit, peak_params, offset=0.0
                )
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
                    "y_peak": y_peak,
                    "y_fit": self._component_curve(
                        func_type, x_fit, peak_params, y_baseline
                    ),
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
                    {k: v for k, v in peak.items()
                     if k not in ["params", "errors", "y_peak", "y_fit"]}
                    for peak in sorted_peaks
                ],
                "baseline": {
                    "requested": requested_baseline,
                    "selected": selected_baseline,
                    "degree": baseline_degree,
                    "basis": "chebyshev",
                    "coefficients": [float(value) for value in baseline_coefficients],
                    "coefficient_errors": [float(value) for value in baseline_errors],
                    "x_min": float(np.min(x_fit)),
                    "x_max": float(np.max(x_fit)),
                    "bic": fit_result["bic"],
                },
                "y_baseline": y_baseline,
            }
            if requested_baseline == self.AUTO_BASELINE_MODE:
                res["baseline"]["candidate_bic"] = {
                    label: item["bic"] for label, item in candidate_results.items()
                }
                res["baseline"]["selection_threshold"] = self.AUTO_BASELINE_BIC_THRESHOLD
                if candidate_failures:
                    res["baseline"]["candidate_failures"] = candidate_failures
            for i, peak in enumerate(sorted_peaks, start=1):
                res[f"y_fit{i}"] = peak["y_fit"]
                res[f"y_peak{i}"] = peak["y_peak"]
            self._add_legacy_peak_keys(res, sorted_peaks)

            # Compute R2 (coefficient of determination)
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
