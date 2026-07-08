from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox,
                             QLabel, QDoubleSpinBox, QAbstractSpinBox, QWidget,
                             QRadioButton, QHBoxLayout, QGroupBox, QPushButton)
from PyQt5.QtCore import Qt
from src.pressureCalc import PressureCalculator

class CustomDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

class PressureCalculatorWindow(QDialog):
    def __init__(self, parent=None, mode="nm"):
        super().__init__(parent)
        self.unit = mode
        self.setWindowTitle("Pressure Calculator")
        self.resize(450, 700)
        self.current_peak_val = 0.0
        self.current_peak_err = 0.0
        self.current_pressure = None       
        self.current_pressure_err = None
        self.init_ui()
        self.setup_connections()
        self.update_mode(self.unit)

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 基本設定 (Sensor / Pressure Scale)
        top_group = QGroupBox("Base Settings")
        form = QFormLayout()

        self.combo_sensor = QComboBox()
        self.combo_p_scale = QComboBox()
        form.addRow("Sensor:", self.combo_sensor)
        form.addRow("Pressure Scale:", self.combo_p_scale)

        self.lbl_cur_peak = QLabel(f"0.000 {self.unit}")
        form.addRow(f"Current peak ({self.unit}):", self.lbl_cur_peak)

        self.lbl_t_mandatory = QLabel("")
        self.lbl_t_mandatory.setStyleSheet("height: 0;")
        form.addRow(self.lbl_t_mandatory)

        # 現在の値を適用するボタン (温度補正ONのときは無効化される)
        self.btn_apply_current = QPushButton("Use the current value as zero-pressure peak position")
        self.btn_apply_current.setAutoDefault(False)  
        self.btn_apply_current.setDefault(False)
        form.addRow(self.btn_apply_current)

        self.spin_lam0 = CustomDoubleSpinBox()
        self.spin_lam0.setRange(-99999, 99999); self.spin_lam0.setDecimals(3)
        self.lbl_lam0_tag = QLabel(f"Zero-pressure peak ({self.unit}):")
        form.addRow(self.lbl_lam0_tag, self.spin_lam0)

        top_group.setLayout(form)
        layout.addWidget(top_group)

        # 2. 温度補正グループ
        self.temp_group = QGroupBox("Temperature Correction")
        temp_v_layout = QVBoxLayout()

        # On/Off ラジオボタン
        self.radio_widget = QWidget()
        radio_h = QHBoxLayout(self.radio_widget)
        self.radio_off = QRadioButton("Off"); self.radio_on = QRadioButton("On")
        self.radio_off.setChecked(True)
        radio_h.addWidget(self.radio_off); radio_h.addWidget(self.radio_on)
        temp_v_layout.addWidget(self.radio_widget)

        # 補正詳細フォーム
        self.t_form_widget = QWidget()
        self.t_form = QFormLayout(self.t_form_widget)

        self.combo_t_scale = QComboBox()
        self.lbl_t_scale_tag = QLabel("Temperature Scale:")
        self.t_form.addRow(self.lbl_t_scale_tag, self.combo_t_scale)

        

        

        self.spin_t = CustomDoubleSpinBox(); self.spin_t.setRange(0, 5000); self.spin_t.setValue(300)
        self.spin_t0 = CustomDoubleSpinBox(); self.spin_t0.setRange(0, 5000); self.spin_t0.setValue(300)

        self.lbl_t_warning = QLabel("")
        self.lbl_t_warning.setStyleSheet("color: red; font-weight: bold;")

        self.t_form.addRow("Current T (K):", self.spin_t)
        self.t_form.addRow("", self.lbl_t_warning)
        self.t_form.addRow("Reference T0 (K):", self.spin_t0)

        self.spin_lam0_t0 = CustomDoubleSpinBox()
        self.spin_lam0_t0.setRange(-99999, 99999); self.spin_lam0_t0.setDecimals(3)
        self.lbl_lam0_t0_tag = QLabel(f"Zero-pressure peak at T0 ({self.unit}):")
        self.t_form.addRow(self.lbl_lam0_t0_tag, self.spin_lam0_t0)

        self.btn_set_lam0_t0 = QPushButton("Use the Current Value as the zero-pressure peak position at T0")
        self.btn_set_lam0_t0.setAutoDefault(False)  # Fix: Enterキーでボタンが押されないようにする
        self.btn_set_lam0_t0.setDefault(False)
        self.t_form.addRow(self.btn_set_lam0_t0)

        temp_v_layout.addWidget(self.t_form_widget)
        self.temp_group.setLayout(temp_v_layout)
        layout.addWidget(self.temp_group)

        # 3. 結果表示
        self.lbl_result = QLabel()
        self.lbl_result.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_result.setStyleSheet("background: #333; color: white; padding: 15px; border-radius: 5px;")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setText(
            "<div style='text-align:center;'>"
            "<span style='font-size:24px; font-weight:bold;'>P = --- GPa</span>"
            "</div>"
        )
        layout.addWidget(self.lbl_result)

    def setup_connections(self):
        self.combo_sensor.currentTextChanged.connect(self.on_sensor_changed)
        self.combo_p_scale.currentTextChanged.connect(self.on_p_scale_changed)
        self.combo_t_scale.currentTextChanged.connect(self.calculate)
        self.spin_lam0.valueChanged.connect(self.calculate)
        self.spin_lam0_t0.valueChanged.connect(self.calculate)
        self.spin_t.valueChanged.connect(self.calculate)
        self.spin_t0.valueChanged.connect(self.calculate)
        self.radio_on.toggled.connect(self.toggle_temp_ui)

        # ボタンの接続
        self.btn_apply_current.clicked.connect(self.apply_current_to_lam0)
        self.btn_set_lam0_t0.clicked.connect(self.apply_current_to_lam0_t0)

    def toggle_temp_ui(self):
        is_on = self.radio_on.isChecked()
        self.t_form_widget.setEnabled(is_on)
        self.spin_lam0.setEnabled(not is_on)
        self.btn_apply_current.setEnabled(not is_on)
        self.calculate()

    def apply_current_to_lam0(self):
        """現在のピーク値を λ0 に適用 (温度補正OFF用)"""
        if self.current_peak_val != 0:
            self.spin_lam0.setValue(self.current_peak_val)

    def apply_current_to_lam0_t0(self):
        """現在のピーク値を λ0 at T0 に適用 (温度補正ON用)"""
        if self.current_peak_val != 0:
            self.spin_lam0_t0.setValue(self.current_peak_val)

    def calculate(self):
        sensor = self.combo_sensor.currentText()
        p_scale = self.combo_p_scale.currentText()
        t_scale = self.combo_t_scale.currentText()
        curr_t = self.spin_t.value()

        is_valid, rng = PressureCalculator.is_temp_in_range(sensor, t_scale, curr_t)
        if self.radio_on.isChecked() and not is_valid and rng[0] is not None:
            self.lbl_t_warning.setText(f"Warning: T out of range ({rng[0]} - {rng[1]} K)")
            self.spin_t.setStyleSheet("background-color: #FFCCCC; color: red;")
        else:
            self.lbl_t_warning.setText("")
            self.spin_t.setStyleSheet("")

        if self.current_peak_val == 0: return

        lam0 = self.spin_lam0.value()
        if self.radio_on.isChecked():
            lam0 = PressureCalculator.get_corrected_lam0(
                sensor, t_scale, curr_t, self.spin_t0.value(), self.spin_lam0_t0.value()
            )

            self.spin_lam0.setValue(lam0)


        p, dp = PressureCalculator.calculate(
            sensor, p_scale, self.current_peak_val, lam0, self.spin_lam0_t0.value(),
            lam_err=self.current_peak_err, current_t=curr_t, t0=self.spin_t0.value()
        )
        if p is not None:
            self.current_pressure = p
            self.current_pressure_err = dp
            self.lbl_result.setText(self._build_result_html(p, dp))
        else:
            self.current_pressure = None
            self.current_pressure_err = None
            self.lbl_result.setText("<span style='font-size:20px;'>Calc Error</span>")

    def update_mode(self, mode):
        self.unit = mode
        self.lbl_lam0_tag.setText(f"Zero-pressure peak ({mode}):")
        self.lbl_lam0_t0_tag.setText(f"Zero-pressure peak at T0 ({mode}):")
        self.combo_sensor.blockSignals(True); self.combo_sensor.clear()
        if mode == "nm":
            self.combo_sensor.addItems(["Ruby", "Sm2+:SrB4O7"])
        else:
            self.combo_sensor.addItems(["13C diamond 1st order", "Cubic BN TO", "Zircon B1g"])
        self.combo_sensor.blockSignals(False)
        self.on_sensor_changed()

    def on_sensor_changed(self):
        sensor = self.combo_sensor.currentText()
        default_val = PressureCalculator.INITIAL_VALUES.get(sensor, 0.0)
        self.spin_lam0.setValue(default_val)
        self.spin_lam0_t0.setValue(default_val)

        self.combo_p_scale.blockSignals(True); self.combo_p_scale.clear()
        self.combo_t_scale.blockSignals(True); self.combo_t_scale.clear()

        if sensor == "Ruby":
            self.combo_p_scale.addItems(["Shen et al. 2020", "Dorogokupets and Oganov 2007", "Holzapfel 2003", "Mao et al. 1986", "Piermarini et al. 1975"])
            self.combo_t_scale.addItems(["Kobayashi et al. unpublished", "Yen and Nicol 1992", "Ragan et al. 1992", "Datchi et al. 1997"])
        elif sensor == "Sm2+:SrB4O7":
            self.combo_p_scale.addItems(["Datchi et al. 1997 (MXB1986)", "Datchi et al. 2007 (DO2007)", "Rashchenko 2015"])
            self.combo_t_scale.addItems(["Datchi et al. 2007"])
        elif sensor == "13C diamond 1st order":
            self.combo_p_scale.addItems(["Schiferl et al. 1997", "Mysen and Yamashita 2010"])
            self.combo_t_scale.addItems(["Schiferl et al. 1997", "Mysen and Yamashita 2010"])
        elif sensor == "Cubic BN TO":
            self.combo_p_scale.addItems(["Kawamoto et al. 2004", "Datchi et al. 2004"])
            self.combo_t_scale.addItems(["Kawamoto et al. 2004"])
        elif sensor == "Zircon B1g":
            self.combo_p_scale.addItems(["Schmidt et al. 2013", "Takahashi et al. 2024"])

        self.combo_p_scale.blockSignals(False); self.combo_t_scale.blockSignals(False)
        self.on_p_scale_changed()
        self.lbl_result.setText(self._build_result_html(self.current_pressure, self.current_pressure_err))

    def on_p_scale_changed(self):
        sensor = self.combo_sensor.currentText()
        scale = self.combo_p_scale.currentText()
        # 指定したスケールを含むかどうか。階層構造が複雑なので、だらだらif文で書く
        is_pt_scale = False
        if sensor == "13C diamond 1st order": 
            if scale in ["Schiferl et al. 1997", "Mysen and Yamashita 2010"]:
                is_pt_scale = True
        elif sensor == "Cubic BN TO":
            if scale in ["Datchi et al. 2004"]:
                is_pt_scale = True

        self.radio_widget.setVisible(not is_pt_scale)
        self.lbl_t_scale_tag.setVisible(not is_pt_scale)
        self.combo_t_scale.setVisible(not is_pt_scale)
        if is_pt_scale:
            self.radio_on.setChecked(True)
            self.lbl_t_mandatory.setText("Temperature input is mandatory for this scale!")
            self.lbl_t_mandatory.setStyleSheet("color: red; font-weight: bold; height: 1em;")
        else:
            self.lbl_t_mandatory.setText("")
            self.lbl_t_mandatory.setStyleSheet("height: 0em;")
        self.toggle_temp_ui()

    def _build_result_html(self, p, dp):
        """結果表示ラベル用のHTMLを生成する"""
        sensor = self.combo_sensor.currentText()
        p_scale = self.combo_p_scale.currentText()

        if p is not None:
            pressure_line = f"P = {p:.3f} &plusmn; {dp:.3f} GPa"
        else:
            pressure_line = "P = --- GPa"

        if self.unit == "nm":
            peak_line = f"&lambda; = {self.current_peak_val:.3f} nm"
        else:
            peak_line = f"&nu; = {self.current_peak_val:.3f} cm<sup>-1</sup>"

        info_line = f"{sensor}, {p_scale}"

        return (
            f"<div style='text-align:center;'>"
            f"<span style='font-size:24px; font-weight:bold;'>{pressure_line}</span><br>"
            f"<span style='font-size:20px; margin-top: 20px'>{peak_line}</span><br>"
            f"<span style='font-size:18px; margin-top: 12px'>{info_line}</span>"
            f"</div>"
        )

    def set_current_peak(self, val, err=0.0):
        self.current_peak_val, self.current_peak_err = val, err
        self.lbl_cur_peak.setText(f"{val:.3f} {self.unit}")
        self.calculate()