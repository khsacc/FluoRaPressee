def live_window_title(debug, spectrometer_name, camera_name):
    """Return a hardware-specific live-view title when both models are known."""
    if debug or not spectrometer_name or not camera_name:
        return None
    return f"FluoRaPressée: {spectrometer_name} {camera_name}"
