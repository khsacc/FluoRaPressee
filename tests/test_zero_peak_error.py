"""Zero-pressure peak (lambda0 / nu0) uncertainty propagation.

The zero-pressure peak error enters the pressure error as its own quadrature
term, ``pressure_err_zero_peak``, next to the peak-position and scale-parameter
parts. Through a temperature correction it is first propagated to the
zero-pressure peak at the current temperature. Every analytic term is checked
against a numerical derivative, so a new scale that forgets its zero-peak term
fails here.
"""
import math
import os
import tempfile
import unittest

import numpy as np

from src.core.file_io import DataFileIO
from src.core.pressureCalc import PressureCalculator

try:
    from src.api.schemas import AcquirePressureRequest, AcquirePressureResponse, TemperatureCorrection
    from pydantic import ValidationError
except ImportError:  # The application API requires Pydantic v2; some test envs still ship v1.
    AcquirePressureRequest = None

try:
    from src.ui.ui_mixins.api_mixin import ApiMixin
except (ImportError, ModuleNotFoundError):  # pragma: no cover - Qt not installed
    ApiMixin = None

try:
    from src.api.server import create_app
except (ImportError, ModuleNotFoundError):  # pragma: no cover - FastAPI not installed
    create_app = None

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtWidgets import QApplication
    from src.ui.pressureCalc_ui import PressureCalculatorWindow
except (ImportError, ModuleNotFoundError):  # pragma: no cover - Qt not installed
    PressureCalculatorWindow = None


# (zero-pressure peak, measured peak, current T) per sensor. Peaks are chosen
# a few GPa up (the SrFCl one above Lorenz 1994's 10 GPa branch point), and
# the temperature is inside the embedded_pt scales' validity ranges.
CASES = {
    "ruby": (694.30, 698.00, 300.0),
    "sm_srb4o7": (685.41, 688.00, 300.0),
    "sm_srfcl": (690.30, 705.00, 300.0),
    "sm_yag_y1": (617.80, 620.00, 300.0),
    "diamond_13c_1st_order": (1287.79, 1310.0, 500.0),
    "cubic_bn_to": (1058.3, 1080.0, 500.0),
    "zircon_b1g": (1008.6, 1030.0, 300.0),
    "quartz_464": (464.4, 470.0, 300.0),
    "quartz_128": (127.9, 135.0, 400.0),
}
PEAK_ERR = 0.004
ZERO_ERR = 0.003
T0 = 298.15


def _pressure_scales():
    for sensor, scales in PressureCalculator.PRESSURE_SCALES.items():
        if sensor not in CASES:
            continue
        for p_scale in scales:
            yield sensor, p_scale


def _calc(sensor, p_scale, *, zero=None, zero_err=0.0, peak_err=PEAK_ERR, **kwargs):
    zero0, peak, current_t = CASES[sensor]
    zero = zero0 if zero is None else zero
    kwargs.setdefault("current_t", current_t)
    kwargs.setdefault("t0", T0)
    return PressureCalculator.calculate(
        sensor=sensor, p_scale=p_scale, peak=peak,
        zero_peak=zero, zero_peak_at_t0=zero,
        peak_err=peak_err, zero_peak_err=zero_err, **kwargs,
    )


def _numerical_slope(func, x, h):
    return (func(x + h) - func(x - h)) / (2.0 * h)


class PressureZeroPeakTermTests(unittest.TestCase):
    def test_every_sensor_has_a_case(self):
        # A sensor missing from CASES would silently skip the derivative checks.
        for sensor, meta in PressureCalculator.SENSORS.items():
            if meta["kind"] != "raman_edge":
                self.assertIn(sensor, CASES, f"add a test case for {sensor!r} to CASES")

    def assertQuadratureSum(self, result):
        self.assertAlmostEqual(
            math.sqrt(result.pressure_err_peak**2
                      + result.pressure_err_zero_peak**2
                      + result.pressure_err_scale**2),
            result.pressure_err, places=12,
        )

    def test_every_scale_matches_the_numerical_derivative(self):
        for sensor, p_scale in _pressure_scales():
            with self.subTest(sensor=sensor, p_scale=p_scale):
                zero = CASES[sensor][0]
                slope = _numerical_slope(
                    lambda z: _calc(sensor, p_scale, zero=z, peak_err=0.0).pressure,
                    zero, 1e-4,
                )
                result = _calc(sensor, p_scale, zero_err=ZERO_ERR)
                self.assertIsNotNone(result.pressure)
                self.assertGreater(abs(slope), 0.0)
                self.assertAlmostEqual(
                    result.pressure_err_zero_peak / (abs(slope) * ZERO_ERR), 1.0, places=6
                )
                self.assertQuadratureSum(result)

    def test_zero_error_leaves_every_other_part_unchanged(self):
        for sensor, p_scale in _pressure_scales():
            with self.subTest(sensor=sensor, p_scale=p_scale):
                without = _calc(sensor, p_scale, zero_err=0.0)
                with_err = _calc(sensor, p_scale, zero_err=ZERO_ERR)
                self.assertEqual(without.pressure_err_zero_peak, 0.0)
                self.assertEqual(with_err.pressure, without.pressure)
                self.assertAlmostEqual(with_err.pressure_err_peak, without.pressure_err_peak, places=10)
                self.assertAlmostEqual(with_err.pressure_err_scale, without.pressure_err_scale, places=10)
                self.assertGreater(with_err.pressure_err, without.pressure_err)

    def test_omitted_zero_error_matches_an_explicit_zero(self):
        zero, peak, _ = CASES["ruby"]
        omitted = PressureCalculator.calculate(
            sensor="ruby", p_scale="ruby_shen_2020", peak=peak, zero_peak=zero, peak_err=PEAK_ERR,
        )
        self.assertEqual(omitted, _calc("ruby", "ruby_shen_2020", zero_err=0.0))
        self.assertEqual(_calc("ruby", "ruby_shen_2020", zero_err=None), omitted)

    def test_diamond_edge_ignores_the_zero_peak_error(self):
        result = PressureCalculator.calculate(
            sensor="diamond_raman_edge", p_scale="diamond_edge_akahama_kawamura_2006",
            peak=1500.0, zero_peak=0.0, peak_err=0.2, zero_peak_err=5.0,
        )
        self.assertEqual(result.pressure_err_zero_peak, 0.0)
        self.assertEqual(result.zero_peak_at_current_t, 1334.0)
        self.assertEqual(result.zero_peak_at_current_t_err, 0.0)

    def test_invalid_zero_error_fails_the_calculation(self):
        for bad in (-0.001, float("nan"), float("inf")):
            with self.subTest(zero_err=bad):
                result = _calc("ruby", "ruby_shen_2020", zero_err=bad)
                self.assertIsNone(result.pressure)
                self.assertIsNone(result.pressure_err_zero_peak)


class EmbeddedTemperatureScaleTests(unittest.TestCase):
    def test_embedded_scales_use_the_t0_error(self):
        for sensor, p_scale in (("cubic_bn_to", "cubic_bn_datchi_2004"),
                                ("diamond_13c_1st_order", "diamond_13c_mysen_yamashita_2010"),
                                ("quartz_128", "quartz_li_2025")):
            with self.subTest(p_scale=p_scale):
                only_t0 = _calc(sensor, p_scale, zero_err=0.0, zero_peak_at_t0_err=ZERO_ERR)
                fallback = _calc(sensor, p_scale, zero_err=ZERO_ERR)
                ignored = _calc(sensor, p_scale, zero_err=ZERO_ERR, zero_peak_at_t0_err=0.0)
                self.assertGreater(only_t0.pressure_err_zero_peak, 0.0)
                self.assertEqual(fallback.pressure_err_zero_peak, only_t0.pressure_err_zero_peak)
                self.assertEqual(ignored.pressure_err_zero_peak, 0.0)

    def test_datchi_2004_reports_the_zero_peak_error_at_current_t(self):
        result = _calc("cubic_bn_to", "cubic_bn_datchi_2004", zero_peak_at_t0_err=0.2)
        self.assertIsNotNone(result.zero_peak_at_current_t)
        self.assertEqual(result.zero_peak_at_current_t_err, 0.2)


class TemperatureCorrectionPropagationTests(unittest.TestCase):
    def _temperature_scales(self):
        for sensor, scales in PressureCalculator.TEMPERATURE_SCALES.items():
            for t_scale, meta in scales.items():
                lo, hi = meta["valid_range"]
                yield sensor, t_scale, max(lo, 60.0) + 0.25 * (hi - max(lo, 60.0))

    def test_every_slope_matches_the_numerical_derivative(self):
        for sensor, t_scale, current_t in self._temperature_scales():
            with self.subTest(sensor=sensor, t_scale=t_scale):
                zero = PressureCalculator.SENSORS[sensor]["initial_value"]

                def corrected(z):
                    return PressureCalculator.get_corrected_zero_peak(
                        sensor=sensor, t_scale=t_scale, current_t=current_t,
                        t0=T0, zero_peak_at_t0=z,
                    )

                correction = PressureCalculator.get_corrected_zero_peak_with_err(
                    sensor=sensor, t_scale=t_scale, current_t=current_t,
                    t0=T0, zero_peak_at_t0=zero, zero_peak_at_t0_err=ZERO_ERR,
                )
                self.assertEqual(correction.value, corrected(zero))
                self.assertAlmostEqual(correction.slope, _numerical_slope(corrected, zero, 1e-3), places=7)
                self.assertAlmostEqual(correction.zero_peak_err, abs(correction.slope) * ZERO_ERR, places=15)
                self.assertEqual(correction.err, math.hypot(correction.zero_peak_err, correction.coefficient_err))
                meta = PressureCalculator.TEMPERATURE_SCALES[sensor][t_scale]
                if "debye_param_covariance" in meta:
                    self.assertGreater(correction.coefficient_err, 0.0)
                else:
                    self.assertEqual(correction.coefficient_err, 0.0)

    def test_offset_scales_pass_the_error_through_unchanged(self):
        correction = PressureCalculator.get_corrected_zero_peak_with_err(
            sensor="ruby", t_scale="ruby_datchi_2007_lt", current_t=80.0, t0=T0,
            zero_peak_at_t0=694.30, zero_peak_at_t0_err=ZERO_ERR,
        )
        self.assertEqual(correction.slope, 1.0)
        self.assertEqual(correction.err, ZERO_ERR)

    def test_wavenumber_scales_scale_the_error_by_the_squared_ratio(self):
        correction = PressureCalculator.get_corrected_zero_peak_with_err(
            sensor="ruby", t_scale="ruby_kobayashi_2026", current_t=30.0, t0=T0,
            zero_peak_at_t0=694.30, zero_peak_at_t0_err=ZERO_ERR,
        )
        self.assertAlmostEqual(correction.slope, (correction.value / 694.30) ** 2, places=15)
        self.assertLess(correction.err, ZERO_ERR)

    def test_corrected_pressure_carries_the_propagated_error(self):
        kwargs = dict(temperature_correction_enabled=True, t_scale="ruby_kobayashi_2026",
                      current_t=30.0, t0=T0)
        result = _calc("ruby", "ruby_shen_2020", zero_err=0.0, zero_peak_at_t0_err=ZERO_ERR, **kwargs)
        correction = PressureCalculator.get_corrected_zero_peak_with_err(
            sensor="ruby", t_scale="ruby_kobayashi_2026", current_t=30.0, t0=T0,
            zero_peak_at_t0=694.30, zero_peak_at_t0_err=ZERO_ERR,
        )
        self.assertEqual(result.zero_peak_at_current_t, correction.value)
        self.assertEqual(result.zero_peak_at_current_t_err, correction.err)

        slope = _numerical_slope(
            lambda z: _calc("ruby", "ruby_shen_2020", zero=z, peak_err=0.0, **kwargs).pressure,
            694.30, 1e-4,
        )
        self.assertAlmostEqual(result.pressure_err_zero_peak / (abs(slope) * ZERO_ERR), 1.0, places=6)

    def test_uncorrected_pressure_ignores_the_t0_error(self):
        result = _calc("ruby", "ruby_shen_2020", zero_err=0.0, zero_peak_at_t0_err=ZERO_ERR)
        self.assertEqual(result.pressure_err_zero_peak, 0.0)
        self.assertEqual(result.zero_peak_at_current_t_err, 0.0)


class KobayashiCoefficientErrorTests(unittest.TestCase):
    """ruby_kobayashi_2026 propagates its Debye-parameter covariance."""
    META = PressureCalculator.TEMPERATURE_SCALES["ruby"]["ruby_kobayashi_2026"]

    def _correction(self, current_t, zero_err=0.0):
        return PressureCalculator.get_corrected_zero_peak_with_err(
            sensor="ruby", t_scale="ruby_kobayashi_2026", current_t=current_t, t0=T0,
            zero_peak_at_t0=694.30, zero_peak_at_t0_err=zero_err,
        )

    @staticmethod
    def _corrected_with(alpha, theta, current_t):
        shift = (PressureCalculator._calc_debye_shift(alpha, theta, current_t)
                 - PressureCalculator._calc_debye_shift(alpha, theta, T0))
        return PressureCalculator._offset_in_wavenumber(694.30, shift)[0]

    def test_covariance_matches_the_published_fit(self):
        cov = np.asarray(self.META["debye_param_covariance"])
        np.testing.assert_array_equal(cov, cov.T)
        self.assertTrue(np.all(np.linalg.eigvalsh(cov) > 0))
        alpha_err, theta_err = np.sqrt(np.diag(cov))
        # Published as alpha1 = -458.9(5) cm-1, theta = 794.0(4) K.
        self.assertEqual(self.META["debye_params"], (-458.9, 794.0))
        self.assertEqual(round(alpha_err, 1), 0.5)
        self.assertEqual(round(theta_err, 1), 0.4)
        self.assertAlmostEqual(cov[0, 1] / (alpha_err * theta_err), -0.996, places=3)

    def test_gradient_matches_the_numerical_derivative(self):
        alpha, theta = self.META["debye_params"]
        for current_t in (0.5, 30.0, 150.0, 300.0, 600.0):
            with self.subTest(current_t=current_t):
                gradient = PressureCalculator._debye_shift_gradient(alpha, theta, current_t)
                numerical = (
                    _numerical_slope(lambda a: PressureCalculator._calc_debye_shift(a, theta, current_t), alpha, 1e-3),
                    _numerical_slope(lambda t: PressureCalculator._calc_debye_shift(alpha, t, current_t), theta, 1e-3),
                )
                np.testing.assert_allclose(gradient, numerical, rtol=1e-6, atol=1e-12)

    def test_coefficient_error_matches_a_numerical_propagation(self):
        alpha, theta = self.META["debye_params"]
        cov = np.asarray(self.META["debye_param_covariance"])
        for current_t in (30.0, 150.0, 250.0, 400.0):
            with self.subTest(current_t=current_t):
                gradient = np.array([
                    _numerical_slope(lambda a: self._corrected_with(a, theta, current_t), alpha, 1e-3),
                    _numerical_slope(lambda t: self._corrected_with(alpha, t, current_t), theta, 1e-3),
                ])
                expected = math.sqrt(gradient @ cov @ gradient)
                self.assertAlmostEqual(self._correction(current_t).coefficient_err / expected, 1.0, places=5)

    def test_coefficient_error_is_small_and_vanishes_at_t0(self):
        self.assertEqual(self._correction(T0).coefficient_err, 0.0)
        # About 1e-4 nm over the calibrated range: smaller than a typical fit error.
        for current_t in (5.0, 30.0, 150.0, 250.0):
            with self.subTest(current_t=current_t):
                self.assertLess(self._correction(current_t).coefficient_err, 2e-4)
                self.assertGreater(self._correction(current_t).coefficient_err, 1e-5)

    def test_coefficient_error_goes_to_the_scale_part(self):
        kwargs = dict(temperature_correction_enabled=True, t_scale="ruby_kobayashi_2026",
                      current_t=30.0, t0=T0)
        correction = self._correction(30.0, zero_err=ZERO_ERR)
        result = _calc("ruby", "ruby_shen_2020", zero_err=0.0, zero_peak_at_t0_err=ZERO_ERR, **kwargs)

        # The same formula at the corrected zero-pressure peak, without any temperature correction.
        _, peak, _ = CASES["ruby"]
        plain = PressureCalculator.calculate(
            sensor="ruby", p_scale="ruby_shen_2020", peak=peak, zero_peak=correction.value,
            peak_err=PEAK_ERR, zero_peak_err=correction.zero_peak_err,
        )
        slope = abs(_numerical_slope(
            lambda z: PressureCalculator.calculate(
                sensor="ruby", p_scale="ruby_shen_2020", peak=peak, zero_peak=z).pressure,
            correction.value, 1e-4,
        ))
        self.assertAlmostEqual(result.pressure_err_peak, plain.pressure_err_peak, places=12)
        self.assertAlmostEqual(result.pressure_err_zero_peak, plain.pressure_err_zero_peak, places=10)
        self.assertAlmostEqual(
            result.pressure_err_scale,
            math.hypot(plain.pressure_err_scale, slope * correction.coefficient_err), places=8,
        )
        self.assertEqual(result.zero_peak_at_current_t_err, correction.err)
        self.assertAlmostEqual(
            math.sqrt(result.pressure_err_peak**2 + result.pressure_err_zero_peak**2
                      + result.pressure_err_scale**2),
            result.pressure_err, places=12,
        )

    def test_coefficient_error_applies_without_a_zero_peak_error(self):
        result = _calc("ruby", "ruby_shen_2020", zero_err=0.0,
                       temperature_correction_enabled=True, t_scale="ruby_kobayashi_2026",
                       current_t=30.0, t0=T0)
        self.assertEqual(result.pressure_err_zero_peak, 0.0)
        self.assertEqual(result.zero_peak_at_current_t_err, self._correction(30.0).coefficient_err)
        self.assertGreater(result.zero_peak_at_current_t_err, 0.0)


class DatchiRubyBelow50KTests(unittest.TestCase):
    def _corrected(self, t_scale, current_t):
        return PressureCalculator.get_corrected_zero_peak(
            sensor="ruby", t_scale=t_scale, current_t=current_t, t0=T0, zero_peak_at_t0=694.30,
        )

    def test_below_50k_is_an_absolute_wavelength(self):
        for t_scale in ("ruby_datchi_2007_lt", "ruby_datchi_2007_ht"):
            with self.subTest(t_scale=t_scale):
                # -0.887 nm from the 296 K line, shifted by the same offset as at T0.
                at_296 = self._corrected(t_scale, 296.0)
                self.assertAlmostEqual(self._corrected(t_scale, 30.0), at_296 - 0.887, places=9)

    def test_lt_scale_is_nearly_continuous_at_50k(self):
        jump = self._corrected("ruby_datchi_2007_lt", 50.0) - self._corrected("ruby_datchi_2007_lt", 49.999)
        self.assertLess(abs(jump), 0.02)


class FittingResultsFileTests(unittest.TestCase):
    def _write(self, pressure_info):
        fit_res = {
            "R2": 0.99,
            "peaks": [{"position": 698.0, "position_err": 0.004, "width": 1.0, "width_err": 0.1}],
            "baseline": {"requested": "Constant", "selected": "Constant"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "data_fitting_results.txt")
            DataFileIO().save_fitting_results(path, fit_res, "Gauss", pressure_info=pressure_info)
            with open(path, encoding="utf-8") as f:
                header, values = (line.rstrip("\n").split(",") for line in f)
        return dict(zip(header, values))

    def _pressure_info(self, **overrides):
        info = {"pressure": 10.0, "pressure_err": 0.05, "scale": "Shen et al. 2020",
                "sensor": "Ruby", "lam0": 694.3, "lam0_err": 0.0003, "lam0_unit": "nm"}
        info.update(overrides)
        return info

    def test_zero_peak_error_column_follows_the_zero_peak(self):
        row = self._write(self._pressure_info())
        self.assertEqual(list(row)[-2:], ["Lambda0_nm", "Lambda0_Err_nm"])
        self.assertEqual(row["Lambda0_Err_nm"], "0.000300")

    def test_raman_unit_and_missing_error(self):
        row = self._write(self._pressure_info(lam0_unit="cm-1", lam0=1058.3, lam0_err=None))
        self.assertEqual(list(row)[-2:], ["Nu0_cm-1", "Nu0_Err_cm-1"])
        self.assertEqual(row["Nu0_Err_cm-1"], "nan")


@unittest.skipIf(ApiMixin is None, "PyQt6 is not installed")
class ApiZeroPeakErrorTests(unittest.TestCase):
    def test_api_pressure_propagates_both_zero_peak_errors(self):
        zero, peak, _ = CASES["ruby"]
        plain = ApiMixin.api_pressure(object(), peak, PEAK_ERR, "ruby", "ruby_shen_2020", zero,
                                      zero_pressure_peak_err=ZERO_ERR)
        expected = _calc("ruby", "ruby_shen_2020", zero_err=ZERO_ERR)
        self.assertEqual(plain["pressure_err"], expected.pressure_err)
        self.assertEqual(plain["pressure_err_zero_peak"], expected.pressure_err_zero_peak)
        self.assertEqual(plain["zero_pressure_peak_at_current_t_err"], ZERO_ERR)

        corrected = ApiMixin.api_pressure(
            object(), peak, PEAK_ERR, "ruby", "ruby_shen_2020", zero,
            temperature_correction={"enabled": True, "scale": "ruby_kobayashi_2026",
                                    "current_t": 30.0, "t0": T0,
                                    "zero_pressure_peak_at_t0": zero,
                                    "zero_pressure_peak_at_t0_err": ZERO_ERR},
        )
        self.assertGreater(corrected["pressure_err_zero_peak"], 0.0)
        self.assertLess(corrected["zero_pressure_peak_at_current_t_err"], ZERO_ERR)

    def test_api_pressure_without_errors_is_unchanged(self):
        zero, peak, _ = CASES["ruby"]
        result = ApiMixin.api_pressure(object(), peak, PEAK_ERR, "ruby", "ruby_shen_2020", zero)
        self.assertEqual(result["pressure_err_zero_peak"], 0.0)
        self.assertEqual(result["pressure_err"], _calc("ruby", "ruby_shen_2020").pressure_err)


class _DirectBridge:
    def call(self, fn):
        return fn()


class _PressureRouteGui:
    """Just enough of SpectrometerGUI for POST /acquire/pressure to compute a pressure."""
    _api_key = "test-key"

    def api_acquire(self, **kwargs):
        return {
            "x": np.array([697.9, 698.0, 698.1]),
            "y_raw": np.array([1.0, 2.0, 1.0]), "y": np.array([1.0, 2.0, 1.0]),
            "mode": "1d", "saturated": False, "exposure_time_s": 0.1, "accumulations": 1,
            "detector_temperature_c": -65.0, "timestamp": "2026-11-20T00:00:00+09:00",
            "configuration": {"axis_mode": "calibrated"}, "hardware_state": {},
            "x_axis": {"source": "calibrated", "unit": "nm", "calibrated": True},
        }

    def api_fit(self, x, y, fit_function, **kwargs):
        peak = {"index": 1, "position": CASES["ruby"][1], "position_err": PEAK_ERR,
                "width": 0.5, "width_err": 0.01}
        return {"success": True, "x_fit": x, "y_fit": y, "fit": {"R2": 0.99, "peaks": [peak]}}

    def api_pressure(self, *args, **kwargs):
        return ApiMixin.api_pressure(self, *args, **kwargs)


@unittest.skipIf(create_app is None or ApiMixin is None or AcquirePressureRequest is None,
                 "FastAPI, Pydantic v2 or PyQt6 is not installed")
class AcquirePressureRouteTests(unittest.TestCase):
    def _post(self, **fields):
        app = create_app(_PressureRouteGui(), _DirectBridge())
        pending = list(app.routes)
        while pending:
            route = pending.pop(0)
            pending.extend(getattr(route, "routes", []))
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                pending.extend(original_router.routes)
            if getattr(route, "path", None) == "/acquire/pressure" and "POST" in getattr(route, "methods", set()):
                return route.endpoint(AcquirePressureRequest(
                    fit_function="Pseudo Voigt", fit_peak_count=1, sensor="ruby",
                    pressure_scale="ruby_shen_2020", zero_pressure_peak=CASES["ruby"][0], **fields,
                ))
        self.fail("Missing route: POST /acquire/pressure")

    def test_route_reports_the_zero_peak_part(self):
        payload = self._post(zero_pressure_peak_err=ZERO_ERR)
        expected = _calc("ruby", "ruby_shen_2020", zero_err=ZERO_ERR)
        self.assertEqual(payload["pressure_err_gpa"], expected.pressure_err)
        self.assertEqual(payload["pressure_err_zero_peak_gpa"], expected.pressure_err_zero_peak)
        self.assertEqual(payload["zero_pressure_peak_at_current_t_err"], ZERO_ERR)
        AcquirePressureResponse(**payload)

    def test_route_without_the_new_fields_is_unchanged(self):
        payload = self._post()
        self.assertEqual(payload["pressure_err_gpa"], _calc("ruby", "ruby_shen_2020").pressure_err)
        self.assertEqual(payload["pressure_err_zero_peak_gpa"], 0.0)


@unittest.skipIf(AcquirePressureRequest is None, "Pydantic v2 is not installed")
class ApiSchemaTests(unittest.TestCase):
    BASE = {"fit_function": "Pseudo Voigt", "sensor": "ruby",
            "pressure_scale": "ruby_shen_2020", "zero_pressure_peak": 694.3}

    def test_zero_peak_errors_default_to_zero(self):
        req = AcquirePressureRequest(**self.BASE)
        self.assertEqual(req.zero_pressure_peak_err, 0.0)
        correction = TemperatureCorrection(enabled=True, scale="ruby_kobayashi_2026",
                                           current_t=30.0, t0=T0, zero_pressure_peak_at_t0=694.3)
        self.assertEqual(correction.zero_pressure_peak_at_t0_err, 0.0)

    def test_negative_or_non_finite_errors_are_rejected(self):
        for bad in (-0.1, float("nan"), float("inf")):
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    AcquirePressureRequest(**self.BASE, zero_pressure_peak_err=bad)

    def test_response_model_has_the_new_fields(self):
        fields = AcquirePressureResponse.model_fields
        for name in ("pressure_err_zero_peak_gpa", "zero_pressure_peak_at_current_t_err"):
            self.assertIn(name, fields)
            self.assertIsNone(fields[name].default)


@unittest.skipIf(PressureCalculatorWindow is None, "PyQt6 is not installed")
class PressureCalculatorWindowTests(unittest.TestCase):
    FIT_PEAK = {"index": 1, "position": 698.12346, "position_err": 0.00032,
                "width": 0.5, "width_err": 0.01}

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = PressureCalculatorWindow(mode="nm")
        self.win.set_fit_peaks([self.FIT_PEAK])

    def tearDown(self):
        self.win.close()

    def test_capturing_the_current_peak_also_captures_its_fit_error(self):
        win = self.win
        win.apply_current_to_lam0()
        # Four decimals keep a typical ruby fit error instead of rounding it to 0.
        self.assertAlmostEqual(win.spin_lam0.value(), 698.1235, places=9)
        self.assertAlmostEqual(win.spin_lam0_err.value(), 0.0003, places=9)
        expected = PressureCalculator.calculate(
            sensor="ruby", p_scale=win.combo_p_scale.currentData(),
            peak=self.FIT_PEAK["position"], peak_err=self.FIT_PEAK["position_err"],
            zero_peak=win.spin_lam0.value(), zero_peak_at_t0=win.spin_lam0_t0.value(),
            zero_peak_err=win.spin_lam0_err.value(),
            zero_peak_at_t0_err=win.spin_lam0_t0_err.value(),
            current_t=win.spin_t.value(), t0=win.spin_t0.value(),
        )
        self.assertGreater(expected.pressure_err_zero_peak, 0.0)
        self.assertEqual(win.current_pressure_err, expected.pressure_err)

    def test_t0_capture_is_propagated_through_the_temperature_correction(self):
        win = self.win
        win.radio_on.setChecked(True)
        win.combo_t_scale.setCurrentIndex(win.combo_t_scale.findData("ruby_kobayashi_2026"))
        win.spin_t.setValue(30.0)
        win.apply_current_to_lam0_t0()
        self.assertAlmostEqual(win.spin_lam0_t0_err.value(), 0.0003, places=9)
        correction = PressureCalculator.get_corrected_zero_peak_with_err(
            sensor="ruby", t_scale="ruby_kobayashi_2026", current_t=30.0, t0=win.spin_t0.value(),
            zero_peak_at_t0=win.spin_lam0_t0.value(), zero_peak_at_t0_err=0.0003,
        )
        self.assertEqual(win.current_zero_peak_at_current_t_err, correction.err)
        self.assertIn("±", win.lbl_zero_peak_current_t.text())

        info = win.pressure_info_for_save()
        self.assertEqual(info["lam0"], correction.value)
        self.assertEqual(info["lam0_err"], correction.err)

    def test_pressure_info_uses_the_uncorrected_error_without_temperature_correction(self):
        self.win.spin_lam0_err.setValue(0.001)
        info = self.win.pressure_info_for_save()
        self.assertEqual(info["lam0"], self.win.spin_lam0.value())
        self.assertEqual(info["lam0_err"], 0.001)

    def test_error_row_follows_the_zero_peak_row(self):
        win = self.win
        self.assertFalse(win.spin_lam0_err.isHidden())
        win.radio_on.setChecked(True)
        self.assertTrue(win.spin_lam0_err.isHidden())
        win.radio_off.setChecked(True)
        self.assertFalse(win.spin_lam0_err.isHidden())

        win.update_mode("cm-1")
        win.combo_sensor.setCurrentIndex(win.combo_sensor.findData("diamond_raman_edge"))
        self.assertTrue(win.spin_lam0_err.isHidden())
        win.combo_sensor.setCurrentIndex(win.combo_sensor.findData("zircon_b1g"))
        self.assertFalse(win.spin_lam0_err.isHidden())

    def test_changing_sensor_resets_both_errors(self):
        win = self.win
        win.spin_lam0_err.setValue(0.01)
        win.spin_lam0_t0_err.setValue(0.02)
        win.combo_sensor.setCurrentIndex(win.combo_sensor.findData("sm_srb4o7"))
        self.assertEqual(win.spin_lam0_err.value(), 0.0)
        self.assertEqual(win.spin_lam0_t0_err.value(), 0.0)


if __name__ == "__main__":
    unittest.main()
