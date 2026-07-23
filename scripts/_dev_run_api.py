"""Temporary dev helper for Step 7 verification (work/work_API.md).

Launches FluoRaPressée in --debug mode with the API server started immediately
on a fixed dev key/port, so the HTTP layer can be exercised with curl without
waiting for Step 8's Start/Stop API Server GUI button.

Not part of the production app - safe to delete once Step 8 lands and the
real Start/Stop button supersedes this.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["QT_OPENGL"] = "software"
import gc
gc.enable()
import threading

import uvicorn
from PyQt6.QtWidgets import QApplication

from src.ui import SpectrometerGUI
from src.app_bootstrap import print_software_and_author_info, check_and_create_config
from src.api.gui_bridge import GuiBridge
from src.ui.theme import apply_application_style
from src.api.server import create_app

DEV_API_KEY = "devkey"
DEV_PORT = 8765


def main():
    print_software_and_author_info()
    check_and_create_config()

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    apply_application_style(app)

    bridge = GuiBridge()
    window = SpectrometerGUI(debug=True)
    window.gui_bridge = bridge
    window.show()

    api_app = create_app(window, bridge, api_key=DEV_API_KEY)
    server = uvicorn.Server(uvicorn.Config(api_app, host="127.0.0.1", port=DEV_PORT, log_level="info"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    print(f"[dev] API server at http://127.0.0.1:{DEV_PORT}/docs (X-API-Key: {DEV_API_KEY})")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
