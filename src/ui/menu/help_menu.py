"""The Help menu shared by the live GUI and Analysis Mode (work/work_updater.md 方針7/9).

About / Check for Updates... / Open Log Folder, plus the start-up update check:
done at most once per 24 hours in a background thread after the window is shown,
silent on failure (a lab PC may be offline), and announced only by an extra item in
this menu - never by a modal dialog that could interrupt the start of an experiment.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox

from src.core.app_paths import logs_dir
from src.core.update_check import (
    UpdateCheckError,
    UpdateInfo,
    check_for_update,
    is_newer,
)
from src.ui.local_cache import load_local_cache, save_local_cache
from src.version import __version__

CHECK_INTERVAL = timedelta(hours=24)
STARTUP_DELAY_MS = 3000

KEY_ON_STARTUP = "update_check_on_startup"
KEY_INCLUDE_PRERELEASE = "update_include_prerelease"
KEY_LAST_CHECKED = "update_last_checked"
KEY_LAST_RESULT = "update_last_result"

_MENU_TITLE = "Help"
_MENU_TITLE_UPDATE = "Help (update available)"


class HelpMenu(QObject):
    """Owns the Help menu of one window and its update checks."""

    # (UpdateInfo | None, error message | None), delivered on the GUI thread.
    _check_finished = pyqtSignal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._running = False
        self._waiting_dialogs = []
        self._latest = None
        self._check_finished.connect(self._on_check_finished)

        menu = window.menuBar().addMenu(_MENU_TITLE)
        self.menu = menu
        self.action_update_available = menu.addAction("Update available")
        self.action_update_available.setVisible(False)
        self.action_update_available.triggered.connect(self._show_latest)
        self.action_check = menu.addAction("Check for Updates…")
        self.action_check.triggered.connect(self.check_now)
        self.action_check_on_startup = menu.addAction("Check for Updates on Startup")
        self.action_check_on_startup.setCheckable(True)
        self.action_check_on_startup.setChecked(
            bool(load_local_cache().get(KEY_ON_STARTUP, True))
        )
        self.action_check_on_startup.toggled.connect(
            lambda checked: save_local_cache(KEY_ON_STARTUP, bool(checked))
        )
        menu.addSeparator()
        self.action_open_logs = menu.addAction("Open Log Folder")
        self.action_open_logs.triggered.connect(self.open_log_folder)
        self.action_about = menu.addAction("About FluoRaPressée")
        self.action_about.triggered.connect(self.show_about)

    # ---- start-up check ---------------------------------------------------

    def schedule_startup_check(self):
        """Call after the window is shown; never delays camera initialisation.

        A child timer rather than QTimer.singleShot(callable): it dies with this
        object, so a window closed within the delay never runs the check.
        """
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._startup_check)
        self._startup_timer.start(STARTUP_DELAY_MS)

    def _startup_check(self):
        cache = load_local_cache()
        if not cache.get(KEY_ON_STARTUP, True):
            return
        last_checked = _parse_time(cache.get(KEY_LAST_CHECKED))
        if last_checked is not None and datetime.now() - last_checked < CHECK_INTERVAL:
            remembered = UpdateInfo.from_dict(cache.get(KEY_LAST_RESULT) or {})
            if is_newer(remembered, __version__):
                self._announce(remembered)
            return
        self._start_check()

    # ---- manual check -------------------------------------------------------

    def check_now(self):
        from src.ui.menu.update_dialog import UpdateDialog

        dialog = UpdateDialog(self._window)
        self._waiting_dialogs.append(dialog)
        self._start_check()
        dialog.exec()
        if dialog in self._waiting_dialogs:
            self._waiting_dialogs.remove(dialog)

    def _show_latest(self):
        from src.ui.menu.update_dialog import UpdateDialog

        dialog = UpdateDialog(self._window)
        dialog.set_result(self._latest)
        dialog.exec()

    # ---- background work ----------------------------------------------------

    def _start_check(self):
        if self._running:
            return
        self._running = True
        include = load_local_cache().get(KEY_INCLUDE_PRERELEASE)
        include = None if include is None else bool(include)
        threading.Thread(
            target=self._worker, args=(include,), daemon=True,
            name="FluoRaPressee-update-check",
        ).start()

    def _worker(self, include_prerelease):
        info, error = None, None
        try:
            info = check_for_update(__version__, include_prerelease)
        except UpdateCheckError as exc:
            error = str(exc)
        except Exception as exc:  # never let a bug here take the app down
            error = f"Unexpected error: {exc}"
        try:
            self._check_finished.emit(info, error)
        except RuntimeError:
            pass  # the window was closed while checking

    def _on_check_finished(self, info, error):
        self._running = False
        if error is None:
            save_local_cache(KEY_LAST_CHECKED, datetime.now().isoformat(timespec="seconds"))
            save_local_cache(KEY_LAST_RESULT, info.to_dict() if info else None)
            if info is not None:
                self._announce(info)
        else:
            print(f"Update check failed: {error}")
        for dialog in self._waiting_dialogs:
            if error is None:
                dialog.set_result(info)
            else:
                dialog.set_error(error)
        self._waiting_dialogs.clear()

    def _announce(self, info):
        self._latest = info
        self.action_update_available.setText(f"Update available: v{info.version}…")
        self.action_update_available.setVisible(True)
        self.menu.setTitle(_MENU_TITLE_UPDATE)

    # ---- other items --------------------------------------------------------

    def open_log_folder(self):
        folder = logs_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self._window, "Log folder", f"Could not create {folder}:\n{exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def show_about(self):
        from src.ui.menu.about_dialog import show_about_dialog

        show_about_dialog(self._window)


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
