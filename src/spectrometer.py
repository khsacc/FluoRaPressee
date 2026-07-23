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
    elif model == "OceanOptics":
        from src.spectrometer_oceanoptics import SpectrometerControllerOceanOptics
        return SpectrometerControllerOceanOptics(config=config, debug=debug)
    else:
        from src.spectrometer_andor import SpectrometerControllerAndor
        return SpectrometerControllerAndor(config=config, debug=debug)

def SpectrometerMoveThread(controller, *args, **kwargs):
    """Create the move thread that matches the connected controller.

    This must be selected at call time: on the first application launch this
    module is imported before the setup wizard creates spectrometerConfig.json.
    """
    if controller.__class__.__module__.endswith("spectrometer_princeton"):
        from src.spectrometer_princeton import SpectrometerMoveThread as ThreadClass
    elif controller.__class__.__module__.endswith("spectrometer_oceanoptics"):
        from src.spectrometer_oceanoptics import SpectrometerMoveThread as ThreadClass
    else:
        from src.spectrometer_andor import SpectrometerMoveThread as ThreadClass
    return ThreadClass(controller, *args, **kwargs)
