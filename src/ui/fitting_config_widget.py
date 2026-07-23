"""Reusable fitting-configuration controls shared by live and analysis UIs."""

from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QRadioButton,
)

from src.ui.ui_widgets import CustomComboBox, CustomDoubleSpinBox


class FittingConfigWidget(QGroupBox):
    """The complete fitting-settings panel used throughout FluoraPressee.

    Signal handling intentionally remains with the containing window because the
    live view and Analysis Mode refresh their data differently.  The controls,
    choices, ranges, labels, and defaults are defined only here.
    """

    CONTROL_NAMES = (
        "radio_fit_on",
        "radio_fit_off",
        "combo_fit_func",
        "combo_fit_peak_count",
        "combo_peak_sort",
        "combo_baseline_model",
        "spin_fit_start",
        "spin_fit_end",
    )

    def __init__(self, fitting_enabled=False, parent=None):
        super().__init__("Fitting Configurations", parent)

        layout = QGridLayout(self)

        self.radio_fit_on = QRadioButton("ON")
        self.radio_fit_off = QRadioButton("OFF")
        if fitting_enabled:
            self.radio_fit_on.setChecked(True)
        else:
            self.radio_fit_off.setChecked(True)

        fit_radio_layout = QHBoxLayout()
        fit_radio_layout.addWidget(self.radio_fit_on)
        fit_radio_layout.addWidget(self.radio_fit_off)

        self.combo_fit_func = CustomComboBox()
        self.combo_fit_func.addItems([
            "Pseudo Voigt", "Moffat", "Gauss", "Lorentz", "Diamond Raman Edge"
        ])
        self.combo_fit_func.setCurrentText("Pseudo Voigt")

        self.combo_fit_peak_count = CustomComboBox()
        for count in range(1, 6):
            self.combo_fit_peak_count.addItem(str(count), count)
        self.combo_fit_peak_count.setCurrentIndex(self.combo_fit_peak_count.findData(2))

        self.combo_peak_sort = CustomComboBox()
        self.combo_peak_sort.addItem("x descending", "x_desc")
        self.combo_peak_sort.addItem("x ascending", "x_asc")
        self.combo_peak_sort.addItem("intensity descending", "intensity_desc")
        self.combo_peak_sort.addItem("intensity ascending", "intensity_asc")

        self.combo_baseline_model = CustomComboBox()
        self.combo_baseline_model.addItem("Constant", "Constant")
        self.combo_baseline_model.addItem("Linear", "Linear")
        self.combo_baseline_model.addItem("Quadratic", "Quadratic")
        self.combo_baseline_model.addItem("Auto Polynomial", "Auto Polynomial")
        self.combo_baseline_model.setCurrentIndex(
            self.combo_baseline_model.findData("Constant")
        )

        self.spin_fit_start = CustomDoubleSpinBox()
        self.spin_fit_start.setRange(-10000, 20000)
        self.spin_fit_start.setValue(0.0)
        self.spin_fit_start.setDecimals(2)

        self.spin_fit_end = CustomDoubleSpinBox()
        self.spin_fit_end.setRange(-10000, 20000)
        self.spin_fit_end.setValue(4000.0)
        self.spin_fit_end.setDecimals(2)

        layout.addWidget(QLabel("Fitting:"), 0, 0)
        layout.addLayout(fit_radio_layout, 0, 1)
        layout.addWidget(QLabel("Function:"), 1, 0)
        layout.addWidget(self.combo_fit_func, 1, 1)
        layout.addWidget(QLabel("Fit Peaks:"), 2, 0)
        layout.addWidget(self.combo_fit_peak_count, 2, 1)
        layout.addWidget(QLabel("Sort peaks:"), 3, 0)
        layout.addWidget(self.combo_peak_sort, 3, 1)
        layout.addWidget(QLabel("Baseline:"), 4, 0)
        layout.addWidget(self.combo_baseline_model, 4, 1)
        layout.addWidget(QLabel("Range Start:"), 5, 0)
        layout.addWidget(self.spin_fit_start, 5, 1)
        layout.addWidget(QLabel("Range End:"), 6, 0)
        layout.addWidget(self.spin_fit_end, 6, 1)

        self.combo_fit_func.currentTextChanged.connect(self._update_function_controls)
        self._update_function_controls(self.combo_fit_func.currentText())

    def _update_function_controls(self, function_name):
        is_edge = function_name == "Diamond Raman Edge"
        if is_edge:
            self.combo_fit_peak_count.setCurrentIndex(
                self.combo_fit_peak_count.findData(1)
            )
        self.combo_fit_peak_count.setEnabled(not is_edge)
        self.combo_peak_sort.setEnabled(not is_edge)
        self.combo_baseline_model.setEnabled(not is_edge)

    def expose_controls_on(self, owner):
        """Keep existing mixin/controller attribute names without duplicating UI."""
        for name in self.CONTROL_NAMES:
            setattr(owner, name, getattr(self, name))
