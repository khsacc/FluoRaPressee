import sys
import os

os.environ["QT_OPENGL"] = "software"
import gc
gc.enable()

from PyQt5.QtWidgets import QApplication

# ui.py から必要なクラスや関数をインポート
from src.ui import SpectrometerGUI, print_software_and_author_info, check_and_create_config

def main():

    print_software_and_author_info()
    check_and_create_config()
    

    debug_mode = "--debug" in sys.argv
    print("debug_mode ", debug_mode)
    
    # QApplication の初期化
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        

    window = SpectrometerGUI(debug=debug_mode)
    window.show()
    

    sys.exit(app.exec())

if __name__ == "__main__":
    main()