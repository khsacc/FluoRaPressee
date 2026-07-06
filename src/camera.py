def CameraThread(config=None, debug=False):
    # configからモデルを判定（デフォルトはAndor）
    model = config.get("model", "Andor") if config else "Andor"
    
    if model == "PrincetonInstruments":
        from src.camera_princeton import CameraThreadPI
        return CameraThreadPI(config=config, debug=debug)
    else:
        from src.camera_andor import CameraThreadAndor
        return CameraThreadAndor(debug=debug)