import time
import serial
import re
from PyQt5.QtCore import QThread, pyqtSignal

class SpectrometerControllerPI:
    """Acton SP2750 Spectrometer Controller (Serial Communication)"""

    def __init__(self, config=None, debug=False):
        self.debug = debug
        self.config = config

        self.is_initialized = False
        self.spec = None

        self.com_port = self.config["com_port"]

    def initialize(self):
        if self.debug:
            print("[DEBUG MODE] Spectrometer dummy mode forced.")
            self.is_initialized = False
            return False

        print("Spectrometer initialization...")
        try:

            self.spec = serial.Serial(self.com_port, 9600, timeout=1)
            
            # 接続テスト
            self.spec.write(b'? NM\r\n')
            response = self.spec.readline().decode('ascii').strip()
            
            if response:
                print(f"Connected to SP2750 on {self.com_port}. (Response: {response})")
                self.is_initialized = True
                return True
            else:
                print("Failed to get response from SP2750.")
                return False
                
        except serial.SerialException as e:
            print(f"[Warning] Failed to open {self.com_port}. Running in dummy mode. Error: {e}")
            self.is_initialized = False
            return False
        except Exception as e:
            print(f"An error occurred during initialization: {e}")
            self.is_initialized = False
            return False

    def _send_command(self, cmd):
        """SP2750へASCIIコマンドを送信し、応答を取得するヘルパー関数"""
        if not self.is_initialized or not self.spec:
            return ""
        try:
            self.spec.write((cmd + '\r').encode('ascii'))
            return self.spec.readline().decode('ascii').strip()
        except Exception as e:
            print(f"Serial communication error: {e}")
            return ""

    def get_wavelength(self):
        if not self.is_initialized:
            return 694.0 # ダミー値
            
        res = self._send_command('? NM')
        try:
            # 応答から数値部分だけを抽出 (例: "500.00 nm" -> 500.00)
            match = re.search(r"[-+]?\d*\.\d+|\d+", res)
            if match:
                return float(match.group())
        except Exception:
            pass
        return 694.0

    def get_grating(self):
        if not self.is_initialized:
            return 1 # ダミー値
            
        res = self._send_command('? TURRET')
        try:
            match = re.search(r"\d+", res)
            if match:
                return int(match.group())
        except Exception:
            pass
        return 1

    def set_wavelength(self, wavelength_nm):
        if not self.is_initialized:
            print(f"(Dummy) Setting spectrometer wavelength to {wavelength_nm} nm...")
            time.sleep(1.5) 
            return False
            
        print(f"Setting spectrometer wavelength to {wavelength_nm} nm...")
        # Actonコマンド: 波長移動
        self._send_command(f'{wavelength_nm:.3f} GOTO')
        
        # モーターの移動を待つための簡易スリープ（機種によっては '? DONE' コマンドでポーリング可能です）
        time.sleep(2.0)
        return True

    def set_grating(self, grating_index):
        if not self.is_initialized:
            print(f"(Dummy) Changing grating to index {grating_index}...")
            time.sleep(2.0) 
            return False
            
        print(f"Changing grating to index {grating_index}...")
        # Actonコマンド: ターレットの切り替え (通常 1, 2, 3 のいずれか)
        self._send_command(f'{grating_index} TURRET')
        time.sleep(3.0) # ターレットの回転は時間がかかるため長めに待機
        return True

    def close(self):
        if self.is_initialized and self.spec:
            try:
                self.spec.close()
            except Exception:
                pass
            finally:
                self.is_initialized = False


class SpectrometerMoveThread(QThread):
    finished_signal = pyqtSignal()

    def __init__(self, spec_ctrl, grating_index, wavelength):
        super().__init__()
        self.spec_ctrl = spec_ctrl
        self.grating_index = grating_index
        self.wavelength = wavelength

    def run(self):
        self.spec_ctrl.set_grating(self.grating_index)
        self.spec_ctrl.set_wavelength(self.wavelength)
        self.finished_signal.emit()