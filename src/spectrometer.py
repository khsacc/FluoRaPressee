import json
import os
from pathlib import Path

def _get_config_path(config_path=None):
    """設定ファイルのパスを取得する。
    
    Args:
        config_path: 明示的に指定する設定ファイルパス
        
    Returns:
        config_path が与えられればそれ、なければプロジェクトルートのspectrometerConfig.json
    """
    if config_path:
        return config_path
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "spectrometerConfig.json")

def SpectrometerController(config=None, debug=False):
    """スペクトロメータコントローラを初期化する。
    
    Args:
        config: 設定辞書
        debug: デバッグモードフラグ
        
    Returns:
        SpectrometerController インスタンス
    """
    model = config.get("model", "Andor") if config else "Andor"
    
    if model == "PrincetonInstruments":
        from src.spectrometer_princeton import SpectrometerControllerPI
        return SpectrometerControllerPI(config=config, debug=debug)
    else:
        from src.spectrometer_andor import SpectrometerControllerAndor
        return SpectrometerControllerAndor(debug=debug)

def _load_spectrometer_model(config_path=None):
    """設定ファイルからスペクトロメータモデルを読み込む。"""
    try:
        path = _get_config_path(config_path)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f).get("model", "Andor")
    except Exception as e:
        print(f"Warning: Failed to load spectrometer config: {e}")
    return "Andor"

_model = _load_spectrometer_model()

if _model == "PrincetonInstruments":
    from src.spectrometer_princeton import SpectrometerMoveThread
else:
    from src.spectrometer_andor import SpectrometerMoveThread