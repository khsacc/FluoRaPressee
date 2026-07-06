import numpy as np
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
import pyqtgraph as pg

class ReferenceHelperWindow(QDialog):
    def __init__(self, json_data, is_raman=False, laser_wl=532.0, parent=None):
        super().__init__(parent)
        
        material = json_data.get("material", "Reference")
        approx = json_data.get("approximate_range", "Unknown")
        
        # タイトルの単位も動的に変更
        if is_raman:
            # ラマンシフトへ変換 (簡易計算)
            approx_val = float(approx) if approx.replace('.','',1).isdigit() else 0.0
            approx_raman = (1e7 / laser_wl) - (1e7 / approx_val) if approx_val != 0 else 0.0
            self.setWindowTitle(f"Guide: {material} around {approx_raman:.1f} cm⁻¹")
        else:
            self.setWindowTitle(f"Guide: {material} around {approx} nm")
            
        self.resize(800, 550) # 注意書き用に少し高さを広げる
        
        self.json_data = json_data
        self.is_raman = is_raman
        self.laser_wl = laser_wl
        
        self.init_ui()

    def nm_to_raman(self, wl_nm):
        """Wavelength (nm) to Raman Shift (cm^-1)"""
        if wl_nm == 0: 
            return 0.0
        return (1e7 / self.laser_wl) - (1e7 / wl_nm)

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=False, y=False)
        self.plot_widget.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        
        spectrum = self.json_data.get("spectrum", {})
        x_wl = np.array(spectrum.get("wavelength", []))
        y_int = np.array(spectrum.get("intensity", []))
        
        if len(x_wl) == 0:
            layout.addWidget(self.plot_widget)
            return

        if self.is_raman:
            x_plot = np.array([self.nm_to_raman(val) for val in x_wl])
            self.plot_widget.setLabel('bottom', 'Raman Shift (cm⁻¹)')
        else:
            x_plot = x_wl
            self.plot_widget.setLabel('bottom', 'Wavelength (nm)')
            
        self.plot_widget.setLabel('left', 'Intensity')
        
        # 制限の設定
        x_min, x_max = np.min(x_plot), np.max(x_plot)
        y_min, y_max = np.min(y_int), np.max(y_int)
        x_margin = (x_max - x_min) * 0.05
        y_margin = (y_max - y_min) * 0.1
        self.plot_widget.setLimits(xMin=x_min-x_margin, xMax=x_max+x_margin, yMin=y_min-y_margin, yMax=y_max+y_margin)
        
        # プロット
        self.plot_widget.plot(x_plot, y_int, pen=pg.mkPen('k', width=1.5))
        
        ref_peaks = self.json_data.get("reference_peaks", [])
        max_y = y_max if len(y_int) > 0 else 1.0
        
        for peak in ref_peaks:
            calib_nm = peak.get("calibrated")
            lit_val = peak.get("literature") # JSON内では通常nm
            
            if calib_nm is None or lit_val is None: 
                continue
            
            pos_x = self.nm_to_raman(calib_nm) if self.is_raman else calib_nm
            
            # 縦線（半透明）
            transparent_red_pen = pg.mkPen(color=(255, 0, 0, 100), style=Qt.PenStyle.DashLine)
            line = pg.InfiniteLine(pos=pos_x, angle=90, pen=transparent_red_pen)
            self.plot_widget.addItem(line)
            
            # --- 変更: ラマンモード時は文献値も変換して表示 ---
            if self.is_raman:
                # 変換後の値（小数点2桁程度で表示）
                label_text = f"{self.nm_to_raman(float(lit_val)):.2f}"
            else:
                label_text = str(lit_val)
                
            text_item = pg.TextItem(text=label_text, color='r', angle=-90, anchor=(0, 0.8))
            text_item.setPos(pos_x, max_y * 0.95)
            self.plot_widget.addItem(text_item)
            
        layout.addWidget(self.plot_widget)

        disclaimer_text = (
            "This window displays literature values for the peak positions of standard substances that have been pre-stored in the program; "
            "the spectrum shown is merely an example. " 
            "Therefore, the range on the horizontal axis differs from that of the spectrometer currently in use. "
            "このウィンドウは、較正の助けとなるように、標準物質のピーク位置の文献値を示す目的で、プログラムに事前保存されたデータを表示しており、スペクトルは一例です。横軸の範囲は、現在使用している分光器とは異なります。"
        )
        self.lbl_disclaimer = QLabel(disclaimer_text)
        self.lbl_disclaimer.setWordWrap(True)
        self.lbl_disclaimer.setStyleSheet("color: #555555; font-size: 11px; margin-top: 5px; border-top: 1px solid #DDD; padding-top: 5px;")
        layout.addWidget(self.lbl_disclaimer)