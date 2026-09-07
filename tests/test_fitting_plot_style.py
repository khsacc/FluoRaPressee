import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication, QButtonGroup, QCheckBox, QRadioButton, QWidget

    from src.ui.ui_mixins.display_mixin import DisplayMixin
except ImportError:
    QApplication = None


class _Clearable:
    def clear(self):
        pass


class _Marker:
    def hide(self):
        pass


class _Camera:
    is_measuring = False


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
class FittingPlotStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_turning_fitting_off_redraws_existing_spectrum_as_line(self):
        display = DisplayMixin()
        owner = QWidget()

        display.radio_fit_on = QRadioButton(owner)
        display.radio_fit_off = QRadioButton(owner)
        fit_group = QButtonGroup(owner)
        fit_group.addButton(display.radio_fit_on)
        fit_group.addButton(display.radio_fit_off)
        display.radio_fit_off.setChecked(True)

        display.radio_plot_line = QRadioButton(owner)
        display.radio_plot_scatter = QRadioButton(owner)
        plot_group = QButtonGroup(owner)
        plot_group.addButton(display.radio_plot_line)
        plot_group.addButton(display.radio_plot_scatter)
        display.radio_plot_scatter.setChecked(True)

        display.fitting_panel = QWidget(owner)
        display.chk_save_fitting = QCheckBox(owner)
        display.chk_save_fitting.setChecked(True)
        display.fit_curve = _Clearable()
        display.fit_baseline_curve = _Clearable()
        display.fit_curve_sub1 = _Clearable()
        display.fit_curve_sub2 = _Clearable()
        display.edge_marker = _Marker()
        display.pressure_window = None
        display.raw_1d_data = np.array([1.0, 2.0])
        display.thread = _Camera()

        redraws = []
        display.update_display = lambda is_new_data=False: redraws.append(is_new_data)

        display.toggle_fitting_panel()

        self.assertTrue(display.radio_plot_line.isChecked())
        self.assertFalse(display.radio_plot_scatter.isChecked())
        self.assertEqual(redraws, [False])

        owner.close()
