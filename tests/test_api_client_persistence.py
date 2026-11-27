"""Failure handling around the GUI's named-client persistence layer."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core.app_paths import ENV_DATA_DIR
from src.core.data_versions import UnsupportedDataVersionError

from src.core.api_clients import LastSeenRegistry
from src.ui.ui_mixins.api_mixin import ApiMixin, local_ip_address
from src.ui.ui_mixins.config_mixin import ConfigMixin


class MigrationHarness(ConfigMixin):
    def save_api_clients(self, _clients):
        raise OSError("disk full")


class ClientEditHarness(ApiMixin):
    def __init__(self):
        self._api_clients = ({"name": "old", "key": "old-key"},)

    def save_api_clients(self, _clients):
        raise OSError("read only")


class RecordingBridge:
    def __init__(self):
        self.posted = []

    def post(self, fn):
        self.posted.append(fn)


class StatusLabel:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


class FrozenWidget:
    """Records setEnabled() calls so a test can assert they never happen."""

    def __init__(self, current_data=None):
        self.enable_calls = []
        self._current_data = current_data

    def setEnabled(self, enabled):
        self.enable_calls.append(enabled)

    def currentData(self):
        return self._current_data


class LastRequestHarness(ApiMixin):
    def __init__(self, running=True, stopping=False):
        self.gui_bridge = RecordingBridge()
        self._api_last_seen = LastSeenRegistry()
        self._api_server = object() if running else None
        self._api_stopping = stopping
        self._api_last_port = 8765
        self._api_mode = "standby"
        self.lbl_api_status = StatusLabel()
        # If _refresh_last_request_label() ever touches setEnabled() on any of these
        # (the widgets _on_api_state_changed() freezes while the server runs), the
        # recorded call list below will be non-empty.
        self.spin_api_port = FrozenWidget()
        self.combo_api_bind = FrozenWidget(current_data="0.0.0.0")
        self.chk_api_expose_docs = FrozenWidget()
        self.combo_api_mode = FrozenWidget()
        self.state_refreshes = 0

    def _on_api_state_changed(self):
        self.state_refreshes += 1


class ApiClientPersistenceTests(unittest.TestCase):
    def test_failed_migration_save_preserves_the_legacy_file(self):
        client = {"name": "default", "key": "legacy-key", "allowed_ips": []}
        gui = MigrationHarness()

        with (
            patch(
                "src.ui.ui_mixins.config_mixin.load_clients",
                return_value=((client,), True, True),
            ),
            patch("src.ui.ui_mixins.config_mixin.remove_legacy_key_file") as remove,
        ):
            loaded = gui.load_api_clients()

        self.assertEqual(loaded, (client,))
        remove.assert_not_called()

    def test_failed_client_edit_does_not_replace_the_live_snapshot(self):
        gui = ClientEditHarness()

        with patch("src.ui.ui_mixins.api_mixin.QMessageBox.critical") as critical:
            applied = gui.set_api_clients(({"name": "new", "key": "new-key"},))

        self.assertFalse(applied)
        self.assertEqual(gui._api_clients[0]["key"], "old-key")
        critical.assert_called_once()

    def test_last_request_queues_a_lightweight_gui_refresh(self):
        gui = LastRequestHarness()

        gui.note_api_request("press", "192.0.2.10")

        self.assertEqual(len(gui.gui_bridge.posted), 1)
        gui.gui_bridge.posted[0]()
        self.assertEqual(gui._api_last_request["client"], "press")
        self.assertIn("press", gui.lbl_api_status.text)

    def test_last_request_refresh_does_not_touch_the_frozen_widgets(self):
        """Regression: note_api_request() used to post the full
        _on_api_state_changed(), which re-touches setEnabled() on 4 widgets (plus
        rebuilding the whole status label) on every single API request even though
        none of that state can have changed just because a request came in.
        """
        gui = LastRequestHarness()

        gui.note_api_request("press", "192.0.2.10")
        gui.gui_bridge.posted[0]()

        self.assertEqual(gui.state_refreshes, 0)
        for widget in (
            gui.spin_api_port, gui.combo_api_bind,
            gui.chk_api_expose_docs, gui.combo_api_mode,
        ):
            self.assertEqual(widget.enable_calls, [])

    def test_last_request_refresh_is_skipped_while_stopping(self):
        gui = LastRequestHarness(stopping=True)

        gui.note_api_request("press", "192.0.2.10")
        gui.gui_bridge.posted[0]()

        self.assertIsNone(gui.lbl_api_status.text)

    def test_last_request_refresh_is_skipped_when_not_running(self):
        gui = LastRequestHarness(running=False)

        gui.note_api_request("press", "192.0.2.10")
        gui.gui_bridge.posted[0]()

        self.assertIsNone(gui.lbl_api_status.text)


class LocalIpAddressCachingTests(unittest.TestCase):
    def setUp(self):
        local_ip_address.cache_clear()
        self.addCleanup(local_ip_address.cache_clear)

    def test_the_resolving_syscalls_run_only_once(self):
        """Regression: this used to run socket.gethostbyname(socket.gethostname()) -
        a real, occasionally slow DNS/NSS syscall - on the GUI thread on every single
        API request. The value is documented as best-effort/display-only and a
        machine's LAN address essentially never changes mid-session, so it is safe
        (and now required) to resolve it only once per process.
        """
        with (
            patch("socket.gethostname", return_value="rig-host") as hostname,
            patch("socket.gethostbyname", return_value="192.0.2.5") as byname,
        ):
            first = local_ip_address()
            second = local_ip_address()

        self.assertEqual(first, "192.0.2.5")
        self.assertEqual(second, "192.0.2.5")
        hostname.assert_called_once()
        byname.assert_called_once()


class PlainConfigHarness(ConfigMixin):
    """Uses the real load/save path, only redirected to temporary folders."""


class StartupHarness(ApiMixin, ConfigMixin):
    """The real load path as the window's constructor calls it."""


class LegacyKeyIsolationTests(unittest.TestCase):
    """work_updater.md 方針4: FLUORAPRESSEE_DATA_DIR must keep the real key untouched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.data = Path(self._tmp.name) / "data"
        self.repo.mkdir()
        self.legacy = self.repo / "fluora_pressee_api_key.json"
        self.legacy.write_text(json.dumps({"api_key": "real-secret"}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_environment_variable_leaves_the_legacy_file_alone(self):
        before = self.legacy.read_bytes()
        with patch.object(sys, "frozen", False, create=True), \
                patch.dict(os.environ, {ENV_DATA_DIR: str(self.data)}), \
                patch("src.core.app_paths.repo_root", return_value=self.repo):
            clients = PlainConfigHarness().load_api_clients()

        self.assertEqual(self.legacy.read_bytes(), before)
        self.assertNotEqual(clients[0]["key"], "real-secret")
        saved = json.loads((self.data / "api_clients.json").read_text(encoding="utf-8"))
        self.assertNotEqual(saved["clients"][0]["key"], "real-secret")

    def test_migration_still_happens_without_the_environment_variable(self):
        # Patch the rule and the folder instead of clearing the variable: without it
        # the real user-data folder would be used.
        with patch("src.ui.ui_mixins.config_mixin.legacy_api_key_path", return_value=self.legacy), \
                patch("src.core.api_clients.default_api_clients_path",
                      return_value=self.data / "api_clients.json"):
            clients = PlainConfigHarness().load_api_clients()

        self.assertEqual(clients[0]["key"], "real-secret")
        self.assertFalse(self.legacy.exists())

    def test_newer_file_is_neither_saved_nor_regenerated(self):
        self.data.mkdir()
        path = self.data / "api_clients.json"
        path.write_text(json.dumps({"version": 99, "clients": []}), encoding="utf-8")
        before = path.read_bytes()
        with patch.dict(os.environ, {ENV_DATA_DIR: str(self.data)}):
            with self.assertRaises(UnsupportedDataVersionError):
                PlainConfigHarness().load_api_clients()
        self.assertEqual(path.read_bytes(), before)

    def test_newer_file_does_not_stop_the_window_from_starting(self):
        # SpectrometerGUI.__init__ loads the clients even with the API off.
        self.data.mkdir()
        path = self.data / "api_clients.json"
        path.write_text(json.dumps({"version": 99, "clients": []}), encoding="utf-8")
        before = path.read_bytes()
        gui = StartupHarness()
        with patch.dict(os.environ, {ENV_DATA_DIR: str(self.data)}):
            clients = gui.load_api_client_list_at_startup()
        self.assertEqual(clients, ())
        self.assertEqual(gui._api_clients, ())
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
