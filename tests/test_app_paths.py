"""User-data location, migration out of the repository root and path correction.

work/work_updater.md 方針3/4, Step 1. Every test points FLUORAPRESSEE_DATA_DIR (or an
explicit folder) at a temporary directory and never touches real user data.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core import app_paths
from src.core.app_paths import (
    ENV_DATA_DIR,
    migrate_legacy_user_files,
    normalize_hardware_paths,
)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class LocationTests(TempDirTestCase):
    def test_environment_variable_moves_everything(self):
        with patch.dict(os.environ, {ENV_DATA_DIR: str(self.tmp)}):
            self.assertEqual(app_paths.user_data_dir(), self.tmp)
            self.assertEqual(app_paths.spectrometer_config_path(), self.tmp / "spectrometerConfig.json")
            self.assertEqual(app_paths.local_cache_path(), self.tmp / "local_cache.json")
            self.assertEqual(app_paths.configurations_dir(), self.tmp / "configurations")
            self.assertEqual(app_paths.api_clients_path(), self.tmp / "api_clients.json")
            self.assertEqual(app_paths.logs_dir(), self.tmp / "logs")

    def test_empty_environment_variable_is_ignored(self):
        with patch.dict(os.environ, {ENV_DATA_DIR: "  "}):
            self.assertIsNone(app_paths.data_dir_override())

    def test_platform_base_paths(self):
        env = {k: v for k, v in os.environ.items() if k != ENV_DATA_DIR}
        env["LOCALAPPDATA"] = str(self.tmp / "Local")
        env["XDG_DATA_HOME"] = str(self.tmp / "xdg")
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sys, "platform", "win32"):
                self.assertEqual(app_paths.user_data_dir(), self.tmp / "Local" / "FluoraPressee")
            with patch.object(sys, "platform", "linux"):
                self.assertEqual(app_paths.user_data_dir(), self.tmp / "xdg" / "FluoraPressee")
            with patch.object(sys, "platform", "darwin"):
                self.assertEqual(
                    app_paths.user_data_dir(),
                    Path.home() / "Library" / "Application Support" / "FluoraPressee",
                )

    def test_evaluated_on_every_call(self):
        with patch.dict(os.environ, {ENV_DATA_DIR: str(self.tmp / "a")}):
            first = app_paths.local_cache_path()
        with patch.dict(os.environ, {ENV_DATA_DIR: str(self.tmp / "b")}):
            second = app_paths.local_cache_path()
        self.assertNotEqual(first, second)

    def test_migration_rule(self):
        with patch.object(sys, "frozen", False, create=True):
            with patch.dict(os.environ, {ENV_DATA_DIR: str(self.tmp)}):
                self.assertFalse(app_paths.legacy_migration_enabled())
                self.assertIsNone(app_paths.legacy_api_key_path())
            env = {k: v for k, v in os.environ.items() if k != ENV_DATA_DIR}
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(app_paths.legacy_migration_enabled())
        with patch.object(sys, "frozen", True, create=True):
            env = {k: v for k, v in os.environ.items() if k != ENV_DATA_DIR}
            with patch.dict(os.environ, env, clear=True):
                self.assertFalse(app_paths.legacy_migration_enabled())


class MigrationTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.data = self.tmp / "data"
        self.repo.mkdir()
        self.log = Mock()

    def write_repo_files(self, config=None):
        (self.repo / "spectrometerConfig.json").write_text(
            json.dumps(config or {"model": "Andor", "dll_path": ""}), encoding="utf-8"
        )
        (self.repo / "local_cache.json").write_text(
            json.dumps({"last_save_dir": "D:/data"}), encoding="utf-8"
        )

    def test_files_are_copied_and_originals_renamed(self):
        self.write_repo_files()

        results = migrate_legacy_user_files(self.repo, self.data, log=self.log)

        self.assertEqual(results, {"spectrometerConfig.json": "migrated",
                                   "local_cache.json": "migrated"})
        self.assertEqual(json.loads((self.data / "local_cache.json").read_text("utf-8")),
                         {"last_save_dir": "D:/data"})
        self.assertTrue((self.data / "spectrometerConfig.json").is_file())
        self.assertFalse((self.repo / "spectrometerConfig.json").exists())
        self.assertTrue((self.repo / "spectrometerConfig.json.migrated").is_file())
        self.assertTrue((self.repo / "local_cache.json.migrated").is_file())

    def test_existing_new_file_is_not_overwritten(self):
        self.write_repo_files()
        self.data.mkdir()
        (self.data / "local_cache.json").write_text('{"kept": true}', encoding="utf-8")

        results = migrate_legacy_user_files(self.repo, self.data, log=self.log)

        self.assertEqual(results["local_cache.json"], "both")
        self.assertEqual(json.loads((self.data / "local_cache.json").read_text("utf-8")),
                         {"kept": True})
        self.assertTrue((self.repo / "local_cache.json").is_file(), "old file left alone")

    def test_second_call_changes_nothing(self):
        self.write_repo_files()
        migrate_legacy_user_files(self.repo, self.data, log=self.log)
        snapshot = {p.name: p.read_bytes() for p in self.data.iterdir()}

        results = migrate_legacy_user_files(self.repo, self.data, log=self.log)

        self.assertEqual(results, {})
        self.assertEqual({p.name: p.read_bytes() for p in self.data.iterdir()}, snapshot)

    def test_nothing_happens_when_the_environment_variable_is_set(self):
        """方針4: an explicit data folder must not pull in (or rename) real settings."""
        self.write_repo_files()
        before = {p.name: p.read_bytes() for p in self.repo.iterdir()}
        with patch.object(sys, "frozen", False, create=True), \
                patch.dict(os.environ, {ENV_DATA_DIR: str(self.data)}), \
                patch("src.core.app_paths.repo_root", return_value=self.repo):
            app_paths.prepare_user_data(log=self.log)

        self.assertFalse(self.data.exists() and any(self.data.iterdir()))
        self.assertEqual({p.name: p.read_bytes() for p in self.repo.iterdir()}, before)

    def test_config_paths_are_corrected_on_migration(self):
        self.write_repo_files({"model": "PrincetonInstruments", "PIcam_dll_path": "sdk/picam"})

        migrate_legacy_user_files(self.repo, self.data, log=self.log)

        config = json.loads((self.data / "spectrometerConfig.json").read_text("utf-8"))
        self.assertEqual(config["PIcam_dll_path"],
                         os.path.normpath(os.path.join(str(self.repo), "sdk/picam")))


class PathCorrectionTests(TempDirTestCase):
    def test_absolute_paths_are_kept(self):
        absolute = str(self.tmp / "Andor SDK")
        config = normalize_hardware_paths({"dll_path": absolute}, self.tmp)
        self.assertEqual(config["dll_path"], absolute)

    def test_relative_paths_resolve_against_the_original_folder(self):
        # Even with ShamrockCIF.dll right there, an explicit value is never swapped.
        (self.tmp / "ShamrockCIF.dll").write_bytes(b"")
        config = normalize_hardware_paths({"dll_path": "sdk/Shamrock"}, self.tmp)
        self.assertEqual(config["dll_path"],
                         os.path.normpath(os.path.join(str(self.tmp), "sdk/Shamrock")))

    def test_relative_path_kept_even_if_target_is_missing(self):
        config = normalize_hardware_paths({"PIcam_dll_path": "missing"}, self.tmp)
        self.assertEqual(config["PIcam_dll_path"], os.path.join(str(self.tmp), "missing"))

    def test_empty_dll_path_is_filled_only_when_the_dll_is_there(self):
        self.assertEqual(normalize_hardware_paths({"dll_path": ""}, self.tmp)["dll_path"], "")
        self.assertNotIn("dll_path", normalize_hardware_paths({}, self.tmp))

        (self.tmp / "ShamrockCIF.dll").write_bytes(b"")
        self.assertEqual(normalize_hardware_paths({"dll_path": ""}, self.tmp)["dll_path"],
                         os.path.abspath(str(self.tmp)))

    def test_manual_import_uses_the_chosen_files_folder(self):
        from src.ui.config_wizard import load_existing_config

        folder = self.tmp / "old clone"
        folder.mkdir()
        (folder / "ShamrockCIF.dll").write_bytes(b"")
        path = folder / "spectrometerConfig.json"
        path.write_text(json.dumps({"model": "Andor", "dll_path": "", "extra": 1}),
                        encoding="utf-8")

        config = load_existing_config(path)

        self.assertEqual(config["dll_path"], os.path.abspath(str(folder)))
        self.assertEqual(config["extra"], 1)

    def test_manual_import_rejects_non_json(self):
        from src.ui.config_wizard import load_existing_config

        path = self.tmp / "broken.json"
        path.write_text("{ nope", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_existing_config(path)


class UnknownKeyTests(TempDirTestCase):
    """方針14: settings files keep keys this version does not know."""

    def test_spectrometer_config_round_trip_keeps_unknown_keys(self):
        from src.ui.ui_mixins.config_mixin import ConfigMixin

        class Harness(ConfigMixin):
            pass

        with patch.dict(os.environ, {ENV_DATA_DIR: str(self.tmp)}):
            app_paths.write_json_atomic(
                app_paths.spectrometer_config_path(),
                {"model": "Andor", "grating": [], "future_key": {"a": 1}},
            )
            gui = Harness()
            gui.config = gui.load_spectrometer_config()
            gui.config["flip_x"] = True
            gui.save_config_to_file()
            saved = json.loads(app_paths.spectrometer_config_path().read_text("utf-8"))

        self.assertEqual(saved["future_key"], {"a": 1})
        self.assertTrue(saved["flip_x"])


if __name__ == "__main__":
    unittest.main()
