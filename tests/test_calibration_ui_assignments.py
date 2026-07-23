import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.calibration_ui import CalibrationWindow


_APP = QApplication.instance() or QApplication([])


class CalibrationUiAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.window = CalibrationWindow()
        x = np.arange(1024.0)
        self.window.current_spectrum = (
            100.0
            + 800.0 * np.exp(-0.5 * ((x - 150.0) / 3.0) ** 2)
            + 700.0 * np.exp(-0.5 * ((x - 420.0) / 3.0) ** 2)
            + 600.0 * np.exp(-0.5 * ((x - 750.0) / 3.0) ** 2)
        )
        self.window.find_peaks()
        self.assertEqual(len(self.window.row_widgets), 3)

    def tearDown(self):
        self.window.close()

    def _set_standard(self, standard_id, checked):
        for index in range(self.window.list_standards.count()):
            item = self.window.list_standards.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == standard_id:
                item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
                return
        self.fail(f"Missing standard {standard_id}")

    def test_switching_standard_keeps_locked_assignment(self):
        neon = self.window.reference_standards["Ne-I"].lines[17]
        self.window.assign_reference_line(0, neon)

        self._set_standard("Ar-I", True)
        self._set_standard("Ne-I", False)

        assignment = self.window.assignments[0]
        self.assertEqual(assignment["line_id"], neon.line_id)
        self.assertEqual(assignment["species"], "Ne I")
        combo = self.window.row_widgets[0]["input"]
        self.assertGreaterEqual(combo.findData(neon.line_id), 0)

    def test_mixed_species_can_form_one_calibration(self):
        neon = self.window.reference_standards["Ne-I"].lines[17]
        argon = self.window.reference_standards["Ar-I"].lines[8]
        self.window.assign_reference_line(0, neon)
        self.window.assign_reference_line(1, argon)

        self.assertIsNotNone(self.window.calib_coeffs)
        self.assertEqual(
            {assignment["species"] for assignment in self.window.assignments.values()},
            {"Ne I", "Ar I"},
        )
        self.assertTrue(self.window.btn_save_apply.isEnabled())

    def test_same_literature_line_cannot_be_assigned_twice(self):
        neon = self.window.reference_standards["Ne-I"].lines[17]

        self.window.assign_reference_line(0, neon)
        self.window.assign_reference_line(1, neon)

        self.assertIn(0, self.window.assignments)
        self.assertNotIn(1, self.window.assignments)

    def test_only_used_peak_has_full_height_dashed_marker(self):
        self.assertFalse(self.window.peak_lines[0].isVisible())

        neon = self.window.reference_standards["Ne-I"].lines[17]
        self.window.assign_reference_line(0, neon)
        self.assertTrue(self.window.peak_lines[0].isVisible())
        self.assertFalse(self.window.peak_lines[1].isVisible())

        self.window.row_widgets[0]["check"].setChecked(False)
        self.assertFalse(self.window.peak_lines[0].isVisible())

    def test_individual_fit_plots_have_peak_number_titles(self):
        first_plot = self.window.bottom_layout.itemAt(0).widget()
        second_plot = self.window.bottom_layout.itemAt(1).widget()

        self.assertEqual(first_plot.plotItem.titleLabel.text, "Peak #1")
        self.assertEqual(second_plot.plotItem.titleLabel.text, "Peak #2")

    def test_literature_markers_are_short_bars_below_zero(self):
        neon = self.window.reference_standards["Ne-I"].lines[17]
        argon = self.window.reference_standards["Ar-I"].lines[8]
        self.window.assign_reference_line(0, neon)
        self.window.assign_reference_line(1, argon)

        self.assertTrue(self.window.reference_overlay_items)
        for marker in self.window.reference_overlay_items:
            _x, y = marker.getData()
            self.assertLess(float(np.max(y)), 0.0)


if __name__ == "__main__":
    unittest.main()
