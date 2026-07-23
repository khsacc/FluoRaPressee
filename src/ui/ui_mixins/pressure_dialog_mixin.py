from PyQt6.QtWidgets import QMessageBox

from src.ui.pressureCalc_ui import PressureCalculatorWindow


class PressureDialogMixin:
    def sync_pressure_calculator_mode(self):
        """メイン画面の nm/Raman 切り替えを圧力計算ウィンドウに即時反映させる"""
        if self.pressure_window:
            current_unit = "cm-1" if self.radio_spec_mode_raman.isChecked() else "nm"
            self.pressure_window.update_mode(current_unit)

    def open_pressure_calculator(self):
        """圧力計算ウィンドウを開く (ボタンクリック時)"""
        current_unit = "cm-1" if self.radio_spec_mode_raman.isChecked() else "nm"

        if self.radio_fit_off.isChecked():
            msgBox_fitRequired = QMessageBox(self)
            msgBox_fitRequired.setIcon(QMessageBox.Icon.Warning)
            msgBox_fitRequired.setWindowTitle("Fitting required")
            msgBox_fitRequired.setText("Please activate peak fitting to calculate pressure.")
            msgBox_fitRequired.exec()
        else:

            if self.pressure_window is None:
                self.pressure_window = PressureCalculatorWindow(self, mode=current_unit)
            else:
                self.pressure_window.update_mode(current_unit)

            self.pressure_window.show()
            self.pressure_window.raise_()
            self.pressure_window.activateWindow()
            if getattr(self, "latest_fit_res", None) is not None and self.latest_fit_res.get("peaks"):
                self.pressure_window.set_fit_peaks(self.latest_fit_res["peaks"])
            elif hasattr(self, "combo_fit_peak_count"):
                self.pressure_window.set_fit_peak_count(self.combo_fit_peak_count.currentData())
