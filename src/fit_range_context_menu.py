"""Context-menu controls for setting a fitting range from a pyqtgraph plot."""

import numpy as np
from PyQt6.QtCore import Qt


class FitRangeContextMenu:
    """Add fitting-range actions to a PlotWidget's existing ViewBox menu."""

    def __init__(self, plot_widget, spin_min, spin_max, has_data):
        self.plot_widget = plot_widget
        self.spin_min = spin_min
        self.spin_max = spin_max
        self.has_data = has_data
        self.clicked_x = None

        view_box = plot_widget.getViewBox()
        menu = view_box.getMenu(None)
        menu.addSeparator()
        self.set_min_action = menu.addAction("Set as fitting range MIN")
        self.set_max_action = menu.addAction("Set as fitting range MAX")
        self.set_min_action.triggered.connect(self._set_minimum)
        self.set_max_action.triggered.connect(self._set_maximum)
        menu.aboutToShow.connect(self._update_action_state)
        plot_widget.scene().sigMouseClicked.connect(self._remember_right_click)

        self._update_action_state()

    def _remember_right_click(self, event):
        if event.button() != Qt.MouseButton.RightButton:
            return

        scene_pos = event.scenePos()
        view_box = self.plot_widget.getViewBox()
        if not view_box.sceneBoundingRect().contains(scene_pos):
            self.clicked_x = None
        else:
            x_value = float(view_box.mapSceneToView(scene_pos).x())
            self.clicked_x = x_value if np.isfinite(x_value) else None
        self._update_action_state()

    def _update_action_state(self):
        usable = self.clicked_x is not None and bool(self.has_data())
        self.set_min_action.setEnabled(
            usable and self.clicked_x <= self.spin_max.value()
        )
        self.set_max_action.setEnabled(
            usable and self.clicked_x >= self.spin_min.value()
        )

    def _set_minimum(self):
        if self.clicked_x is not None:
            self.spin_min.setValue(self.clicked_x)

    def _set_maximum(self):
        if self.clicked_x is not None:
            self.spin_max.setValue(self.clicked_x)
