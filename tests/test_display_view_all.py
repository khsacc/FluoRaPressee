import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    import pyqtgraph as pg

    from src.ui.ui_mixins.display_mixin import DisplayMixin
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6/pyqtgraph is not installed")
class DisplayViewAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.display = DisplayMixin()
        self.display.plot_widget = pg.PlotWidget()

    def tearDown(self):
        self.display.plot_widget.close()

    def test_view_all_restores_complete_spectrum_x_and_y_ranges(self):
        plot = self.display.plot_widget
        view_box = plot.getViewBox()
        self.display._configure_spectrum_plot_range(0, 99)
        plot.plot(range(100), [value**2 for value in range(100)])
        view_box.setRange(xRange=(40, 60), yRange=(1000, 4000), padding=0)
        QApplication.processEvents()

        view_box.getMenu(None).viewAll.trigger()
        QApplication.processEvents()

        x_range, y_range = view_box.viewRange()
        self.assertAlmostEqual(x_range[0], 0)
        self.assertAlmostEqual(x_range[1], 99)
        self.assertLessEqual(y_range[0], 0)
        self.assertGreaterEqual(y_range[1], 99**2)
