"""The pressure error is split into its peak-position and scale-parameter parts.

Clients averaging several markers need the two parts separately: the peak part
is independent between spectra, whereas the scale part is shared by every
measurement on the same scale and does not average down.
"""
import math
import unittest

from src.core.pressureCalc import PressureCalculator

try:
    from src.api.schemas import AcquirePressureResponse
except ImportError:  # The application API requires Pydantic v2; some test envs still ship v1.
    AcquirePressureResponse = None

try:
    from src.ui.ui_mixins.api_mixin import ApiMixin
except (ImportError, ModuleNotFoundError):  # pragma: no cover - Qt not installed
    ApiMixin = None


LAMBDA_0 = 694.30
PEAK = 698.00          # roughly 10 GPa on the ruby scales
PEAK_ERR = 0.005


def _ruby(p_scale, *, peak_err=PEAK_ERR, **kwargs):
    return PressureCalculator.calculate(
        sensor="ruby", p_scale=p_scale, peak=PEAK, zero_peak=LAMBDA_0,
        peak_err=peak_err, **kwargs,
    )


class PressureErrorPartsTests(unittest.TestCase):
    def assertQuadratureSum(self, result):
        self.assertIsNotNone(result.pressure_err_peak)
        self.assertIsNotNone(result.pressure_err_scale)
        self.assertGreaterEqual(result.pressure_err_peak, 0.0)
        self.assertGreaterEqual(result.pressure_err_scale, 0.0)
        self.assertAlmostEqual(
            math.hypot(result.pressure_err_peak, result.pressure_err_scale),
            result.pressure_err, places=12,
        )

    def test_shen_2020_parts_match_the_kunc_formula(self):
        result = _ruby("ruby_shen_2020")
        a, b, a_err, b_err = 1870.0, 5.63, 10.0, 0.03
        ratio = (PEAK - LAMBDA_0) / LAMBDA_0
        expected_peak = a * (1.0 + 2.0 * b * ratio) / LAMBDA_0 * PEAK_ERR
        expected_scale = math.hypot(ratio * (1.0 + b * ratio) * a_err, a * ratio**2 * b_err)
        self.assertAlmostEqual(result.pressure_err_peak, expected_peak, places=10)
        self.assertAlmostEqual(result.pressure_err_scale, expected_scale, places=10)
        self.assertQuadratureSum(result)

    def test_scale_without_parameter_errors_has_no_scale_part(self):
        for p_scale in ("ruby_mao_1986", "ruby_kraus_2016", "ruby_sokolova_2013",
                        "ruby_piermarini_1975", "ruby_dorogokupets_oganov_2007"):
            with self.subTest(p_scale=p_scale):
                result = _ruby(p_scale)
                self.assertEqual(result.pressure_err_scale, 0.0)
                self.assertAlmostEqual(result.pressure_err_peak, result.pressure_err, places=12)

    def test_every_ruby_scale_is_a_quadrature_sum(self):
        for p_scale in PressureCalculator.PRESSURE_SCALES["ruby"]:
            with self.subTest(p_scale=p_scale):
                self.assertQuadratureSum(_ruby(p_scale))

    def test_zero_peak_error_leaves_only_the_scale_part(self):
        result = _ruby("ruby_holzapfel_2003", peak_err=0.0)
        self.assertEqual(result.pressure_err_peak, 0.0)
        self.assertGreater(result.pressure_err_scale, 0.0)
        self.assertAlmostEqual(result.pressure_err_scale, result.pressure_err, places=12)

    def test_temperature_corrected_pressure_is_split(self):
        result = _ruby("ruby_shen_2020", temperature_correction_enabled=True,
                       t_scale="ruby_datchi_2007_lt", current_t=80.0, t0=298.15)
        self.assertIsNotNone(result.pressure)
        self.assertQuadratureSum(result)

    def test_raman_and_diamond_edge_scales_are_split(self):
        cases = (
            dict(sensor="cubic_bn_to", p_scale="cubic_bn_kawamoto_2004",
                 peak=1080.0, zero_peak=1054.0, peak_err=0.1),
            dict(sensor="diamond_raman_edge", p_scale="diamond_edge_akahama_kawamura_2006",
                 peak=1500.0, zero_peak=0.0, peak_err=0.2),
            dict(sensor="sm_srb4o7", p_scale="sm_srb4o7_wei_2024",
                 peak=690.0, zero_peak=685.41, peak_err=0.004),
        )
        for case in cases:
            with self.subTest(p_scale=case["p_scale"]):
                result = PressureCalculator.calculate(**case)
                self.assertGreater(result.pressure_err_scale, 0.0)
                self.assertQuadratureSum(result)

    def test_failed_calculation_has_no_parts(self):
        result = PressureCalculator.calculate(
            sensor="ruby", p_scale="no_such_scale", peak=PEAK, zero_peak=LAMBDA_0,
            peak_err=PEAK_ERR,
        )
        self.assertIsNone(result.pressure)
        self.assertIsNone(result.pressure_err_peak)
        self.assertIsNone(result.pressure_err_scale)

    def test_missing_peak_error_has_no_parts(self):
        result = _ruby("ruby_shen_2020", peak_err=None)
        self.assertIsNone(result.pressure_err)
        self.assertIsNone(result.pressure_err_peak)
        self.assertIsNone(result.pressure_err_scale)


@unittest.skipIf(ApiMixin is None, "PyQt6 is not installed")
class ApiPressurePartsTests(unittest.TestCase):
    def test_api_pressure_returns_both_parts(self):
        result = ApiMixin.api_pressure(
            object(), PEAK, PEAK_ERR, "ruby", "ruby_shen_2020", LAMBDA_0,
        )
        expected = _ruby("ruby_shen_2020")
        self.assertEqual(result["pressure_err"], expected.pressure_err)
        self.assertEqual(result["pressure_err_peak"], expected.pressure_err_peak)
        self.assertEqual(result["pressure_err_scale"], expected.pressure_err_scale)


@unittest.skipIf(AcquirePressureResponse is None, "Pydantic v2 is not installed")
class AcquirePressureResponseTests(unittest.TestCase):
    def test_response_model_keeps_both_parts(self):
        fields = AcquirePressureResponse.model_fields
        self.assertIn("pressure_err_peak_gpa", fields)
        self.assertIn("pressure_err_scale_gpa", fields)
        self.assertIsNone(fields["pressure_err_peak_gpa"].default)
        self.assertIsNone(fields["pressure_err_scale_gpa"].default)


if __name__ == "__main__":
    unittest.main()
