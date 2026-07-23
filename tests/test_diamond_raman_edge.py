import unittest

import numpy as np
from scipy.special import erfc

from src.analysis import DataAnalyzer
from src.pressureCalc import PressureCalculator

try:
    from src.api.schemas import AcquirePressureRequest
except ImportError:  # The application API requires Pydantic v2; some test envs still ship v1.
    AcquirePressureRequest = None


class DiamondRamanEdgeTests(unittest.TestCase):
    def test_derivative_fit_recovers_synthetic_edge(self):
        rng = np.random.default_rng(42)
        x = np.linspace(1400.0, 1500.0, 1001)
        expected_edge = 1462.4
        y = (
            100.0
            + 0.02 * (x - 1450.0)
            + 800.0 * 0.5 * erfc((x - expected_edge) / (np.sqrt(2.0) * 1.2))
            + rng.normal(0.0, 2.0, len(x))
        )

        _, _, result = DataAnalyzer().fit_spectrum(
            x, y, "Diamond Raman Edge", 1445.0, 1480.0, peak_count=1
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["analysis_type"], "diamond_raman_edge")
        self.assertAlmostEqual(result["edge_position"], expected_edge, delta=0.1)
        self.assertEqual(result["peaks"][0]["position"], result["edge_position"])
        self.assertGreater(result["R2"], 0.95)

    def test_akahama_2006_pressure_equation(self):
        edge = 1500.0
        x = edge / 1334.0 - 1.0
        expected = 547.0 * x * (1.0 + 0.5 * (3.75 - 1.0) * x)
        result = PressureCalculator.calculate(
            sensor="diamond_raman_edge",
            p_scale="diamond_edge_akahama_kawamura_2006",
            peak=edge,
            zero_peak=0.0,
            peak_err=0.2,
        )
        self.assertAlmostEqual(result.pressure, expected)
        self.assertGreater(result.pressure_err, 0.0)
        self.assertEqual(result.zero_peak_at_current_t, 1334.0)

    def test_cross_validation_rejects_edge_fit_with_non_edge_scale(self):
        with self.assertRaisesRegex(ValueError, "requires a Diamond Raman Edge pressure scale"):
            PressureCalculator.validate_fit_pressure_pair(
                fit_function="Diamond Raman Edge",
                sensor="ruby",
                p_scale="ruby_shen_2020",
            )

    def test_cross_validation_rejects_edge_scale_with_peak_fit(self):
        with self.assertRaisesRegex(ValueError, "requires Diamond Raman Edge fitting"):
            PressureCalculator.validate_fit_pressure_pair(
                fit_function="Pseudo Voigt",
                sensor="diamond_raman_edge",
                p_scale="diamond_edge_hilberer_2026",
            )

    def test_api_schema_applies_cross_validation_before_acquisition(self):
        if AcquirePressureRequest is None:
            self.skipTest("Pydantic v2 is not installed")
        with self.assertRaises(ValueError):
            AcquirePressureRequest(
                fit_function="Diamond Raman Edge",
                fit_peak_count=1,
                sensor="ruby",
                pressure_scale="ruby_shen_2020",
                zero_pressure_peak=694.3,
            )


if __name__ == "__main__":
    unittest.main()
