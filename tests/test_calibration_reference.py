import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.calibration_reference import (
    ReferenceLine,
    find_match_candidates,
    load_reference_standards,
    match_from_seed_axis,
)


def _lines(standard, wavelengths):
    return [
        ReferenceLine(
            line_id=f"{standard}:{wavelength}",
            standard_id=standard,
            species=standard,
            wavelength_nm=float(wavelength),
        )
        for wavelength in wavelengths
    ]


class ReferenceCatalogueTests(unittest.TestCase):
    def test_loads_multiple_standards(self):
        with tempfile.TemporaryDirectory() as directory:
            for standard in ("Ne-I", "Ar-I"):
                Path(directory, f"{standard}.json").write_text(
                    json.dumps({
                        "standard_id": standard,
                        "display_name": standard.replace("-", " "),
                        "lines": [{"wavelength_nm": 700.0}],
                    }),
                    encoding="utf-8",
                )

            standards = load_reference_standards(directory)

        self.assertEqual(set(standards), {"Ne-I", "Ar-I"})
        self.assertEqual(standards["Ne-I"].lines[0].standard_id, "Ne-I")

    def test_calibration_flag_defaults_true_and_does_not_remove_source_line(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Ne-I.json").write_text(
                json.dumps({
                    "standard_id": "Ne-I",
                    "lines": [
                        {"wavelength_nm": 600.0},
                        {
                            "wavelength_nm": 610.0,
                            "enabled_for_calibration": False,
                        },
                    ],
                }),
                encoding="utf-8",
            )

            neon = load_reference_standards(directory)["Ne-I"]

        self.assertEqual(len(neon.lines), 2)
        self.assertTrue(neon.lines[0].enabled_for_calibration)
        self.assertFalse(neon.lines[1].enabled_for_calibration)

    def test_neon_catalogue_contains_all_unfiltered_600_to_800_nm_lines(self):
        catalogue_directory = Path(__file__).parents[1] / "calibrationStandards"
        neon = load_reference_standards(catalogue_directory)["Ne-I"]
        wavelengths = [line.wavelength_nm for line in neon.lines]
        visible_lines = [
            wavelength for wavelength in wavelengths if 600.0 <= wavelength <= 800.0
        ]

        self.assertEqual(len(visible_lines), 85)
        self.assertIn(540.05618, wavelengths)
        self.assertIn(585.24879, wavelengths)
        self.assertEqual(wavelengths, sorted(wavelengths))
        self.assertTrue(all(line.relative_intensity is None for line in neon.lines))
        self.assertEqual(
            {
                line.wavelength_nm
                for line in neon.lines
                if not line.enabled_for_calibration
            },
            {673.80320, 675.95821, 705.12922, 706.4762},
        )


class PatternMatcherTests(unittest.TestCase):
    def test_recovers_mixed_neon_argon_assignments_without_dispersion_prior(self):
        pixels = np.asarray([100.0, 260.0, 450.0, 700.0])
        expected = 680.0 + 0.03 * pixels
        lines = (
            _lines("Ne-I", [expected[0], expected[2], 725.0])
            + _lines("Ar-I", [expected[1], expected[3], 760.0])
        )

        candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=float(680.0 + 0.03 * 400.0),
            detector_midpoint_px=400.0,
        )

        self.assertTrue(candidates)
        best = candidates[0]
        self.assertEqual(best.matched_count, 4)
        self.assertLess(best.rms_nm, 1e-8)
        selected_ids = {line_id for _, line_id in best.assignments}
        self.assertTrue(any(line_id.startswith("Ne-I") for line_id in selected_ids))
        self.assertTrue(any(line_id.startswith("Ar-I") for line_id in selected_ids))

    def test_locked_assignment_is_never_replaced(self):
        pixels = [10.0, 20.0, 30.0]
        lines = _lines("Ne-I", [500.0, 510.0, 520.0, 530.0])
        locked_id = lines[1].line_id

        candidates = find_match_candidates(
            pixels,
            lines,
            locked_assignments={1: locked_id},
        )

        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertIn((1, locked_id), candidate.assignments)

    def test_center_wavelength_is_a_soft_ranking_term(self):
        pixels = [0.0, 10.0, 20.0]
        lines = _lines("Ne-I", [500.0, 510.0, 520.0, 700.0, 710.0, 720.0])

        candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=510.0,
            detector_midpoint_px=10.0,
        )

        self.assertTrue(candidates)
        c0, c1, c2 = candidates[0].coefficients
        self.assertAlmostEqual(c0 + c1 * 10.0 + c2 * 100.0, 510.0, places=6)

    def test_seed_axis_matches_factory_or_model_wavelengths(self):
        axis = np.linspace(690.0, 710.0, 101)
        pixels = [10.0, 35.0, 80.0]
        expected = axis[np.asarray(pixels, dtype=int)]
        lines = _lines("Ne-I", expected)

        candidate = match_from_seed_axis(pixels, lines, axis)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.matched_count, 3)


if __name__ == "__main__":
    unittest.main()
