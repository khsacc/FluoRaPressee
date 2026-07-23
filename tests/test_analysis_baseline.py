import unittest
from unittest.mock import patch

import numpy as np

from src.core.analysis import DataAnalyzer


class AnalysisBaselineTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = DataAnalyzer()
        self.x = np.linspace(690.0, 700.0, 121)
        self.u = 2.0 * (self.x - self.x.min()) / np.ptp(self.x) - 1.0
        self.peak = self.analyzer.gaussian(self.x, 100.0, 695.0, 0.8, 0.0)
        self.noise = np.random.default_rng(3).normal(0.0, 0.25, self.x.size)

    def fit(self, baseline, baseline_model="Constant", x=None):
        fit_x = self.x if x is None else x
        return self.analyzer.fit_spectrum(
            fit_x,
            self.peak + baseline + self.noise,
            "Gauss",
            peak_count=1,
            baseline_model=baseline_model,
        )

    def test_omitted_baseline_is_identical_to_explicit_constant(self):
        y = self.peak + 10.0 + self.noise
        omitted = self.analyzer.fit_spectrum(self.x, y, "Gauss", peak_count=1)
        explicit = self.analyzer.fit_spectrum(
            self.x, y, "Gauss", peak_count=1, baseline_model="Constant"
        )

        np.testing.assert_allclose(omitted[0], explicit[0])
        np.testing.assert_allclose(omitted[1], explicit[1])
        self.assertEqual(explicit[2]["baseline"]["selected"], "Constant")
        self.assertAlmostEqual(
            omitted[2]["peaks"][0]["position"],
            explicit[2]["peaks"][0]["position"],
            places=12,
        )

    def test_explicit_linear_and_quadratic_recover_peak_and_baseline(self):
        cases = [
            ("Linear", 10.0 + 8.0 * self.u, [10.0, 8.0]),
            (
                "Quadratic",
                10.0 + 2.0 * self.u + 8.0 * (2.0 * self.u**2 - 1.0),
                [10.0, 2.0, 8.0],
            ),
        ]
        for model, baseline, expected_coefficients in cases:
            with self.subTest(model=model):
                _, y_fit, result = self.fit(baseline, model)
                self.assertIsNotNone(result)
                self.assertEqual(result["baseline"]["selected"], model)
                self.assertAlmostEqual(result["peaks"][0]["position"], 695.0, delta=0.01)
                np.testing.assert_allclose(
                    result["baseline"]["coefficients"],
                    expected_coefficients,
                    atol=0.15,
                )
                np.testing.assert_allclose(
                    y_fit,
                    result["y_baseline"] + result["y_peak1"],
                )
                np.testing.assert_allclose(result["y_fit1"], y_fit)

    def test_auto_polynomial_is_conservative_and_selects_clear_structure(self):
        cases = [
            ("Constant", 10.0 + 0.0 * self.u),
            ("Constant", 10.0 + 0.1 * self.u),
            ("Linear", 10.0 + 8.0 * self.u),
            (
                "Quadratic",
                10.0 + 2.0 * self.u + 8.0 * (2.0 * self.u**2 - 1.0),
            ),
        ]
        for expected, baseline in cases:
            with self.subTest(expected=expected):
                _, _, result = self.fit(baseline, "Auto Polynomial")
                self.assertEqual(result["baseline"]["selected"], expected)
                self.assertEqual(result["baseline"]["requested"], "Auto Polynomial")
                self.assertEqual(result["baseline"]["selection_threshold"], 6.0)

    def test_auto_polynomial_is_invariant_to_affine_x_axis_scaling(self):
        baseline = 10.0 + 8.0 * self.u
        _, _, wavelength_result = self.fit(baseline, "Auto Polynomial")
        scaled_x = 1000.0 + 250.0 * (self.x - self.x.min())
        _, _, scaled_result = self.fit(baseline, "Auto Polynomial", x=scaled_x)

        self.assertEqual(wavelength_result["baseline"]["selected"], "Linear")
        self.assertEqual(scaled_result["baseline"]["selected"], "Linear")
        np.testing.assert_allclose(
            wavelength_result["baseline"]["coefficients"],
            scaled_result["baseline"]["coefficients"],
            rtol=1e-5,
            atol=1e-5,
        )

    def test_auto_polynomial_uses_remaining_candidates_after_one_fails(self):
        original = self.analyzer._fit_baseline_candidate

        def fail_quadratic(*args, **kwargs):
            if args[2] == 2:
                raise RuntimeError("synthetic candidate failure")
            return original(*args, **kwargs)

        with patch.object(
            self.analyzer, "_fit_baseline_candidate", side_effect=fail_quadratic
        ):
            _, _, result = self.fit(10.0 + 8.0 * self.u, "Auto Polynomial")

        self.assertEqual(result["baseline"]["selected"], "Linear")
        self.assertEqual(result["baseline"]["candidate_failures"], ["Quadratic"])

    def test_linear_baseline_supports_all_peak_functions(self):
        x = np.linspace(0.0, 10.0, 301)
        u = 2.0 * x / 10.0 - 1.0
        peaks = {
            "Gauss": self.analyzer.gaussian(x, 100.0, 5.0, 0.8, 0.0),
            "Lorentz": self.analyzer.lorentzian(x, 100.0, 5.0, 0.8, 0.0),
            "Pseudo Voigt": self.analyzer.pseudo_voigt(x, 100.0, 5.0, 0.8, 0.4, 0.0),
            "Moffat": self.analyzer.moffat(x, 100.0, 5.0, 0.8, 2.0, 0.0),
        }
        for function, peak in peaks.items():
            with self.subTest(function=function):
                _, _, result = self.analyzer.fit_spectrum(
                    x,
                    peak + 5.0 + 2.0 * u,
                    function,
                    peak_count=1,
                    baseline_model="Linear",
                )
                self.assertIsNotNone(result)
                self.assertEqual(result["baseline"]["selected"], "Linear")
                self.assertAlmostEqual(result["peaks"][0]["position"], 5.0, places=5)

    def test_linear_baseline_supports_one_to_five_peaks(self):
        x = np.linspace(0.0, 10.0, 301)
        u = 2.0 * x / 10.0 - 1.0
        for peak_count in range(1, 6):
            positions = np.linspace(2.0, 8.0, peak_count)
            y = 5.0 + 2.0 * u
            for index, position in enumerate(positions):
                y += self.analyzer.gaussian(
                    x, 100.0 - 5.0 * index, position, 0.3, 0.0
                )
            with self.subTest(peak_count=peak_count):
                _, _, result = self.analyzer.fit_spectrum(
                    x,
                    y,
                    "Gauss",
                    peak_count=peak_count,
                    peak_sort_order="x_asc",
                    baseline_model="Linear",
                )
                self.assertIsNotNone(result)
                fitted_positions = [peak["position"] for peak in result["peaks"]]
                np.testing.assert_allclose(fitted_positions, positions, atol=1e-3)


if __name__ == "__main__":
    unittest.main()
