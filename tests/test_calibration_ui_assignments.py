import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
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
        self.window._apply_plot_data_limits(len(self.window.current_spectrum))
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

    def test_disabled_neon_lines_are_kept_in_catalogue_but_hidden_from_gui(self):
        disabled = {
            line.line_id: line.wavelength_nm
            for line in self.window.reference_standards["Ne-I"].lines
            if not line.enabled_for_calibration
        }
        active_ids = {line.line_id for line in self.window.active_reference_lines()}

        self.assertEqual(
            set(disabled.values()),
            {673.80320, 675.95821, 705.12922, 706.4762},
        )
        self.assertTrue(set(disabled).isdisjoint(active_ids))
        self.assertTrue(set(disabled).issubset(self.window.reference_lines_by_id))

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
        self.assertFalse(hasattr(self.window, "peak_select_scatter"))
        self.assertFalse(self.window.peak_lines[0].isVisible())

        neon = self.window.reference_standards["Ne-I"].lines[17]
        self.window.assign_reference_line(0, neon)
        self.assertTrue(self.window.peak_lines[0].isVisible())
        self.assertFalse(self.window.peak_lines[1].isVisible())

        self.window.row_widgets[0]["check"].setChecked(False)
        self.assertFalse(self.window.peak_lines[0].isVisible())

    def test_detected_ticks_have_invisible_click_targets(self):
        points = self.window.detected_select_scatter.points()

        self.assertEqual(len(points), len(self.window.fitted_peaks))
        self.assertEqual(
            self.window.detected_select_scatter.opts["brush"].color().alpha(), 0
        )
        self.assertEqual(
            self.window.detected_select_scatter.opts["pen"].style(),
            Qt.PenStyle.NoPen,
        )
        self.assertIn("Detected peak #1", self.window._detected_peak_tooltip(
            x=0.0, y=0.0, data=0
        ))

    def test_manual_two_click_assignment_and_clear(self):
        neon = self.window.reference_standards["Ne-I"].lines[17]
        point = type("Point", (), {"data": lambda _self: neon.line_id})()

        self.window.select_measured_peak(0)
        self.window.on_reference_line_clicked(None, [point])

        self.assertEqual(self.window.assignments[0]["line_id"], neon.line_id)
        self.assertTrue(self.window.row_widgets[0]["check"].isChecked())
        self.assertIsNone(self.window.selected_peak_row)

        self.window.select_measured_peak(0)
        self.assertTrue(self.window.btn_clear_assignment.isEnabled())
        self.window.btn_clear_assignment.click()
        self.assertNotIn(0, self.window.assignments)
        self.assertFalse(self.window.row_widgets[0]["check"].isChecked())

    def test_overlapping_literature_ticks_offer_a_choice(self):
        lines = self.window.reference_standards["Ne-I"].lines[17:19]
        points = [
            type("Point", (), {"data": lambda _self, line=line: line.line_id})()
            for line in lines
        ]

        self.window.select_measured_peak(0)
        self.window.on_reference_line_clicked(None, points)
        choices = [
            action for action in self.window.reference_candidate_menu.actions()
            if action.isEnabled() and not action.isSeparator()
        ]

        self.assertEqual(len(choices), 2)
        choices[1].trigger()
        self.assertEqual(self.window.assignments[0]["line_id"], lines[1].line_id)
        self.window.reference_candidate_menu.hide()

    def test_fit_plot_click_selects_peak_and_escape_cancels(self):
        second_plot = self.window.row_widgets[1]["plot"]

        second_plot.scene().sigMouseClicked.emit(None)
        self.assertEqual(self.window.selected_peak_row, 1)
        self.assertEqual(
            self.window.peak_tick_items[1].opts["pen"].widthF(), 5.0
        )
        self.assertIn("#FFB300", second_plot.styleSheet())

        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        self.assertIsNone(self.window.selected_peak_row)
        self.assertEqual(
            self.window.peak_tick_items[1].opts["pen"].widthF(), 3.0
        )

    def test_manual_line_combo_supports_contains_search(self):
        self.window.row_widgets[0]["check"].setChecked(True)
        completer = self.window.row_widgets[0]["input"].completer()

        self.assertEqual(completer.filterMode(), Qt.MatchFlag.MatchContains)
        self.assertEqual(
            completer.caseSensitivity(), Qt.CaseSensitivity.CaseInsensitive
        )

    def test_peak_legend_follows_vertical_marker_order(self):
        labels = [label.text for _sample, label in self.window.plot_legend.items]

        self.assertEqual(
            labels,
            ["Detected peak", "Literature line", "Used peak"],
        )

    def test_individual_fit_plots_have_peak_number_titles(self):
        first_plot = self.window.bottom_layout.itemAt(0).widget()
        second_plot = self.window.bottom_layout.itemAt(1).widget()

        self.assertEqual(first_plot.plotItem.titleLabel.text, "Peak #1")
        self.assertEqual(second_plot.plotItem.titleLabel.text, "Peak #2")

    def test_individual_fit_plots_mark_the_fitted_peak_center(self):
        for index, fitted_peak in enumerate(self.window.fitted_peaks):
            small_plot = self.window.bottom_layout.itemAt(index).widget()
            center_lines = [
                item for item in small_plot.plotItem.items
                if isinstance(item, pg.InfiniteLine)
            ]

            self.assertEqual(len(center_lines), 1)
            self.assertAlmostEqual(
                center_lines[0].value(), fitted_peak["center"], places=8
            )
            self.assertEqual(
                center_lines[0].pen.style(), Qt.PenStyle.DashLine
            )

    def test_detected_ticks_are_above_plain_literature_ticks(self):
        neon = self.window.reference_standards["Ne-I"].lines[17]
        argon = self.window.reference_standards["Ar-I"].lines[8]
        self.window.assign_reference_line(0, neon)
        self.window.assign_reference_line(1, argon)

        levels = self.window._tick_levels()
        self.assertGreater(levels["detected"][0], levels["literature"][1])
        self.assertTrue(self.window.reference_overlay_items)
        for marker in self.window.reference_overlay_items:
            x, y = marker.getData()
            self.assertEqual(float(x[0]), float(x[1]))
            self.assertLess(float(np.max(y)), 0.0)
        self.assertEqual(
            self.window.reference_select_scatter.opts["brush"].color().alpha(), 0
        )
        self.assertEqual(
            self.window.reference_select_scatter.opts["pen"].style(),
            Qt.PenStyle.NoPen,
        )

    def test_plot_zoom_is_limited_to_acquired_pixel_domain(self):
        view_box = self.window.plot_widget.getViewBox()

        self.assertEqual(view_box.state["limits"]["xLimits"], [0.0, 1023.0])
        view_box.setXRange(-500.0, 2000.0, padding=0)
        x_range, _y_range = view_box.viewRange()
        self.assertGreaterEqual(x_range[0], 0.0)
        self.assertLessEqual(x_range[1], 1023.0)


if __name__ == "__main__":
    unittest.main()
