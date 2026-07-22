import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt5.QtWidgets import QApplication
    from src.analysis_ui import AnalysisWindow
    from src.fitting_config_widget import FittingConfigWidget
except ImportError:
    AnalysisWindow = None
    FittingConfigWidget = None


class SharedAnalysisControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if AnalysisWindow is None:
            return
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        if AnalysisWindow is None:
            self.skipTest("PyQt5 is not importable in this environment")

    def test_fitting_widget_owns_all_exposed_controls_and_defaults(self):
        live_config = FittingConfigWidget(fitting_enabled=False)
        analysis_config = FittingConfigWidget(fitting_enabled=True)

        self.assertFalse(live_config.radio_fit_on.isChecked())
        self.assertTrue(analysis_config.radio_fit_on.isChecked())
        for name in FittingConfigWidget.CONTROL_NAMES:
            self.assertIsNotNone(getattr(live_config, name))
            self.assertIsNotNone(getattr(analysis_config, name))

        self.assertEqual(
            [analysis_config.combo_fit_func.itemText(i)
             for i in range(analysis_config.combo_fit_func.count())],
            ["Pseudo Voigt", "Moffat", "Gauss", "Lorentz", "Diamond Raman Edge"],
        )
        self.assertEqual(analysis_config.combo_fit_peak_count.currentData(), 2)
        self.assertEqual(analysis_config.combo_baseline_model.currentData(), "Constant")
        self.assertEqual(analysis_config.spin_fit_start.value(), 0.0)
        self.assertEqual(analysis_config.spin_fit_end.value(), 4000.0)

    def test_analysis_uses_shared_fitting_widget_and_embedded_pressure_ui(self):
        window = AnalysisWindow()
        window.show()
        self.app.processEvents()

        self.assertIsInstance(window.fitting_config, FittingConfigWidget)
        for name in FittingConfigWidget.CONTROL_NAMES:
            self.assertIs(getattr(window, name), getattr(window.fitting_config, name))

        self.assertTrue(window.pressure_window.embedded)
        self.assertFalse(window.pressure_window.isWindow())
        self.assertTrue(window.pressure_window.isVisible())
        self.assertFalse(window.pressure_window.isEnabled())
        right_panel = window.centralWidget().layout().itemAt(2).widget()
        right_contents = right_panel.widget()
        center_panel = window.centralWidget().layout().itemAt(1).widget()
        self.assertTrue(right_contents.isAncestorOf(window.fitting_text))
        self.assertFalse(center_panel.isAncestorOf(window.fitting_text))
        self.assertGreaterEqual(
            window.fitting_results_group.y(),
            window.fitting_config.y() + window.fitting_config.height(),
        )
        expected_pressure_width = round(window.pressure_group_natural_width * 0.8)
        self.assertEqual(window.pressure_group.maximumWidth(), expected_pressure_width)
        self.assertLess(
            window.pressure_group.maximumWidth(),
            window.pressure_window.unconstrained_width,
        )
        self.assertEqual(right_panel.horizontalScrollBar().maximum(), 0)

        window.resize(window.width(), 500)
        self.app.processEvents()
        self.assertGreater(right_panel.verticalScrollBar().maximum(), 0)
        self.assertEqual(right_panel.horizontalScrollBar().maximum(), 0)

        window.close()


if __name__ == "__main__":
    unittest.main()
