import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.core.calibration import CalibrationCore
from src.core.calibration_reference import (
    ReferenceLine,
    find_match_candidates,
    load_reference_standards,
    match_from_seed_axis,
    resolve_standard_for_laser,
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

    def test_neon_catalogue_includes_nist_strong_lines_down_to_570_nm(self):
        standards_dir = Path(__file__).parents[1] / "calibrationStandards"
        neon = load_reference_standards(standards_dir)["Ne-I"]
        wavelengths = {line.wavelength_nm for line in neon.lines}

        self.assertTrue({
            571.92248, 574.82985, 576.44188, 580.44496, 582.01558,
            585.24879, 587.28275, 588.18952, 590.24623, 590.64294,
            594.48342, 596.54710, 597.46273, 597.55340, 598.79074,
        }.issubset(wavelengths))


class RamanShiftStandardTests(unittest.TestCase):
    """Raman-shift-native standards (e.g. ASTM materials, polystyrene RMs)."""

    def test_loads_raman_shift_quantity_catalogue_with_wavelength_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Cyclohexane.json").write_text(
                json.dumps({
                    "standard_id": "ASTM-Cyclohexane",
                    "quantity": "raman_shift_cm1",
                    "lines": [
                        {"raman_shift_cm1": 801.3, "uncertainty_cm1": 0.96},
                        {"raman_shift_cm1": 384.1},
                    ],
                }),
                encoding="utf-8",
            )

            standard = load_reference_standards(directory)["ASTM-Cyclohexane"]

        self.assertEqual(standard.quantity, "raman_shift_cm1")
        # Sorted by raman_shift_cm1 even though wavelength_nm isn't known yet.
        self.assertEqual(
            [line.raman_shift_cm1 for line in standard.lines], [384.1, 801.3]
        )
        self.assertTrue(all(line.wavelength_nm is None for line in standard.lines))
        self.assertEqual(standard.lines[1].uncertainty_cm1, 0.96)

    def test_resolve_standard_for_laser_computes_matching_wavelength(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Cyclohexane.json").write_text(
                json.dumps({
                    "standard_id": "ASTM-Cyclohexane",
                    "quantity": "raman_shift_cm1",
                    "lines": [{"raman_shift_cm1": 801.3}],
                }),
                encoding="utf-8",
            )
            standard = load_reference_standards(directory)["ASTM-Cyclohexane"]

        resolved = resolve_standard_for_laser(standard, 532.0)

        line = resolved.lines[0]
        self.assertIsNotNone(line.wavelength_nm)
        self.assertAlmostEqual(
            CalibrationCore.nm_to_raman(line.wavelength_nm, 532.0),
            801.3,
            places=6,
        )

    def test_resolve_standard_for_laser_is_a_no_op_for_wavelength_standards(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Ne-I.json").write_text(
                json.dumps({
                    "standard_id": "Ne-I",
                    "lines": [{"wavelength_nm": 700.0}],
                }),
                encoding="utf-8",
            )
            standard = load_reference_standards(directory)["Ne-I"]

        self.assertIs(resolve_standard_for_laser(standard, 532.0), standard)

    def test_bundled_astm_and_polystyrene_catalogues_load(self):
        catalogue_directory = Path(__file__).parents[1] / "calibrationStandards"
        standards = load_reference_standards(catalogue_directory)

        expected_counts = {
            "ASTM-Cyclohexane": 11,
            "ASTM-Naphthalene": 8,
            "ASTM-4-Acetamidophenol": 24,
            "ASTM-Toluene-Acetonitrile": 12,
            "Polystyrene-NMIJ": 11,
        }
        for standard_id, expected_count in expected_counts.items():
            standard = standards[standard_id]
            self.assertEqual(standard.quantity, "raman_shift_cm1")
            self.assertEqual(len(standard.lines), expected_count)
            self.assertEqual(
                [line.raman_shift_cm1 for line in standard.lines],
                sorted(line.raman_shift_cm1 for line in standard.lines),
            )

        mixture = standards["ASTM-Toluene-Acetonitrile"]
        self.assertEqual(
            {line.species for line in mixture.lines}, {"Toluene", "Acetonitrile"}
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

    def test_two_peak_candidates_search_outwards_from_center(self):
        pixels = [100.0, 900.0]
        lines = _lines(
            "Ne-I", [450.0, 500.0, 506.0, 514.0, 520.0, 700.0]
        )

        candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=510.0,
            detector_midpoint_px=500.0,
            expected_slope_sign=1,
        )

        self.assertGreaterEqual(len(candidates), 2)
        wavelengths_by_id = {line.line_id: line.wavelength_nm for line in lines}
        assigned_wavelengths = [
            wavelengths_by_id[line_id]
            for _, line_id in candidates[0].assignments
        ]
        self.assertEqual(assigned_wavelengths, [506.0, 514.0])
        search_radii = [
            max(
                abs(wavelengths_by_id[line_id] - 510.0)
                for _, line_id in candidate.assignments
            )
            for candidate in candidates
        ]
        self.assertEqual(search_radii, sorted(search_radii))

    def test_two_peak_center_order_preserves_a_locked_assignment(self):
        pixels = [100.0, 900.0]
        lines = _lines("Ne-I", [500.0, 506.0, 514.0, 520.0, 700.0])

        candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=510.0,
            detector_midpoint_px=500.0,
            locked_assignments={0: lines[0].line_id},
            expected_slope_sign=1,
        )

        self.assertTrue(candidates)
        self.assertEqual(
            candidates[0].assignments,
            ((0, lines[0].line_id), (1, lines[2].line_id)),
        )

    def test_two_peak_hypothesis_cap_still_starts_near_center(self):
        pixels = [100.0, 900.0]
        lines = _lines("Ne-I", np.arange(400.0, 530.0))

        candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=500.0,
            detector_midpoint_px=500.0,
            expected_slope_sign=1,
        )

        self.assertTrue(candidates)
        wavelengths_by_id = {line.line_id: line.wavelength_nm for line in lines}
        first_radius = max(
            abs(wavelengths_by_id[line_id] - 500.0)
            for _, line_id in candidates[0].assignments
        )
        self.assertEqual(first_radius, 1.0)

    def test_three_peak_pattern_ranking_is_not_replaced_by_center_outwards_order(self):
        pixels = [0.0, 10.0, 20.0]
        lines = _lines("Ne-I", [500.0, 509.0, 510.0, 511.0, 520.0])

        candidates = find_match_candidates(
            pixels,
            lines,
            center_wavelength_nm=510.0,
            detector_midpoint_px=10.0,
            expected_slope_sign=1,
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0].matched_count, 3)
        self.assertEqual(
            candidates[0].assignments,
            (
                (0, lines[0].line_id),
                (1, lines[2].line_id),
                (2, lines[4].line_id),
            ),
        )

    def test_expected_slope_sign_follows_flip_x_direction(self):
        pixels = [0.0, 10.0, 20.0]
        lines = _lines("Ne-I", [500.0, 510.0, 520.0])

        normal = find_match_candidates(
            pixels, lines, expected_slope_sign=1
        )
        flipped = find_match_candidates(
            pixels, lines, expected_slope_sign=-1
        )

        self.assertTrue(normal)
        self.assertTrue(flipped)
        self.assertGreater(normal[0].coefficients[1], 0)
        self.assertLess(flipped[0].coefficients[1], 0)

    def test_seed_axis_matches_factory_or_model_wavelengths(self):
        axis = np.linspace(690.0, 710.0, 101)
        pixels = [10.0, 35.0, 80.0]
        expected = axis[np.asarray(pixels, dtype=int)]
        lines = _lines("Ne-I", expected)

        candidate = match_from_seed_axis(pixels, lines, axis)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.matched_count, 3)

    def test_seed_candidate_must_follow_expected_flip_direction(self):
        pixels = [10.0, 35.0, 80.0]
        normal_axis = np.linspace(690.0, 710.0, 101)
        flipped_axis = normal_axis[::-1]
        normal_lines = _lines(
            "Ne-I", normal_axis[np.asarray(pixels, dtype=int)]
        )
        flipped_lines = _lines(
            "Ne-I", flipped_axis[np.asarray(pixels, dtype=int)]
        )

        self.assertIsNone(match_from_seed_axis(
            pixels,
            normal_lines,
            normal_axis,
            expected_slope_sign=-1,
        ))
        candidate = match_from_seed_axis(
            pixels,
            flipped_lines,
            flipped_axis,
            expected_slope_sign=-1,
        )

        self.assertIsNotNone(candidate)
        self.assertLess(candidate.coefficients[1], 0)

    def test_seed_axis_recovers_a_shared_factory_axis_offset(self):
        true_axis = np.linspace(600.0, 610.0, 101)
        seed_axis = true_axis - 1.4
        pixels = [0.0, 20.0, 50.0, 80.0, 100.0]
        lines = _lines("Ne-I", true_axis[np.asarray(pixels, dtype=int)])

        candidate = match_from_seed_axis(pixels, lines, seed_axis)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.matched_count, 5)
        self.assertEqual(
            candidate.assignments,
            tuple((index, line.line_id) for index, line in enumerate(lines)),
        )

    def test_seed_axis_honours_locked_assignments_while_searching_offset(self):
        axis = np.linspace(500.0, 510.0, 101)
        pixels = [0.0, 50.0, 100.0]
        lines = _lines("Ne-I", [500.0, 505.0, 510.0, 515.0])

        candidate = match_from_seed_axis(
            pixels,
            lines,
            axis,
            locked_assignments={1: lines[1].line_id},
        )

        self.assertIsNotNone(candidate)
        self.assertIn((1, lines[1].line_id), candidate.assignments)

    def test_coarse_grating_neon_pattern_rejects_incidental_extra_matches(self):
        # Strongest 20 detections from data_20260909_134501_699.txt.  Three are
        # not coherent catalogue peaks and must not displace the 17-line fit.
        pixels = [
            80.73, 101.63, 146.31, 238.13, 253.61, 286.88, 301.50,
            374.49, 422.72, 457.22, 470.85, 544.90, 563.67, 610.59,
            666.90, 694.46, 845.41, 918.58, 1069.87, 1253.92,
        ]
        standards_dir = Path(__file__).parents[1] / "calibrationStandards"
        lines = [
            line
            for line in load_reference_standards(standards_dir)["Ne-I"].lines
            if line.enabled_for_calibration
        ]
        seed_axis = np.linspace(572.7687665, 797.0042691, 1600)

        candidate = match_from_seed_axis(pixels, lines, seed_axis)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.matched_count, 19)
        self.assertLess(candidate.rms_nm, 0.004)
        line_by_id = {line.line_id: line.wavelength_nm for line in lines}
        self.assertEqual(
            [line_by_id[line_id] for _, line_id in candidate.assignments],
            [
                585.24879, 588.18952, 594.48342, 607.43376, 609.61630,
                614.30627, 616.35937, 626.64952, 633.44276, 638.29914,
                640.22480, 650.65277, 653.28824, 659.89528, 667.82766,
                671.70430, 692.94672, 703.24128, 724.51665,
            ],
        )


if __name__ == "__main__":
    unittest.main()
