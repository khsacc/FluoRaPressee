import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    import pyqtgraph as pg

    from src.fit_range_context_menu import FitRangeContextMenu
    from src.ui_widgets import CustomDoubleSpinBox
except ImportError:
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6/pyqtgraph is not installed")
class FitRangeContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.plot = pg.PlotWidget()
        self.minimum = CustomDoubleSpinBox()
        self.maximum = CustomDoubleSpinBox()
        self.minimum.setRange(-10000, 20000)
        self.maximum.setRange(-10000, 20000)
        self.minimum.setValue(10)
        self.maximum.setValue(20)
        self.has_data = True
        self.context_menu = FitRangeContextMenu(
            self.plot,
            self.minimum,
            self.maximum,
            lambda: self.has_data,
        )

    def tearDown(self):
        self.plot.close()

    def test_actions_write_the_remembered_x_coordinate(self):
        self.context_menu.clicked_x = 12.345
        self.context_menu._set_minimum()
        self.assertAlmostEqual(self.minimum.value(), 12.35)

        self.context_menu.clicked_x = 18.765
        self.context_menu._set_maximum()
        self.assertAlmostEqual(self.maximum.value(), 18.77)

    def test_actions_prevent_an_inverted_range(self):
        self.context_menu.clicked_x = 21
        self.context_menu._update_action_state()
        self.assertFalse(self.context_menu.set_min_action.isEnabled())
        self.assertTrue(self.context_menu.set_max_action.isEnabled())

        self.context_menu.clicked_x = 9
        self.context_menu._update_action_state()
        self.assertTrue(self.context_menu.set_min_action.isEnabled())
        self.assertFalse(self.context_menu.set_max_action.isEnabled())

    def test_actions_are_disabled_without_loaded_data(self):
        self.has_data = False
        self.context_menu.clicked_x = 15
        self.context_menu._update_action_state()
        self.assertFalse(self.context_menu.set_min_action.isEnabled())
        self.assertFalse(self.context_menu.set_max_action.isEnabled())
