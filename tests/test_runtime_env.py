"""Run mode, version strings and the two named mutexes (work/work_updater.md Step 0/2)."""
import sys
import unittest
from unittest.mock import patch

from src.core import runtime_env
from src.core.runtime_env import (
    INSTRUMENT_ACQUIRED,
    INSTRUMENT_BUSY,
    INSTRUMENT_BUSY_OTHER_USER,
    INSTRUMENT_UNVERIFIED,
    acquire_instrument_mutex,
    installer_mutex_name,
)
from src.version import __version__


class RunModeTests(unittest.TestCase):
    def test_source_when_not_frozen(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertFalse(runtime_env.is_frozen())
            self.assertEqual(runtime_env.runtime_kind(), "source")

    def test_frozen_when_pyinstaller_sets_the_flag(self):
        with patch.object(sys, "frozen", True, create=True):
            self.assertTrue(runtime_env.is_frozen())
            self.assertEqual(runtime_env.runtime_kind(), "frozen")


class VersionTests(unittest.TestCase):
    def setUp(self):
        runtime_env._git_short_hash.cache_clear()

    def tearDown(self):
        runtime_env._git_short_hash.cache_clear()

    def test_display_version_survives_a_missing_git(self):
        with patch.object(sys, "frozen", False, create=True), \
                patch("src.core.runtime_env.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(runtime_env.display_version(), __version__)

    def test_source_version_carries_the_commit(self):
        class Completed:
            returncode = 0
            stdout = "1a2b3c4d\n"

        with patch.object(sys, "frozen", False, create=True), \
                patch("src.core.runtime_env.subprocess.run", return_value=Completed()):
            self.assertEqual(runtime_env.display_version(), f"{__version__}+dev.g1a2b3c4d")

    def test_frozen_version_is_the_plain_version(self):
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(runtime_env.display_version(), __version__)
            self.assertTrue(runtime_env.version_details().startswith(__version__))


class InstallerMutexNameTests(unittest.TestCase):
    """The same paths are used to check the .iss side in Step 4 (方針6)."""

    def test_default_install_folder(self):
        self.assertEqual(
            installer_mutex_name(r"C:\Users\Lab\AppData\Local\Programs\FluoRaPressee"),
            "Global\\FluoRaPresseeRunning:c:/users/lab/appdata/local/programs/fluorapressee",
        )

    def test_trailing_separator_is_dropped(self):
        self.assertEqual(
            installer_mutex_name("C:\\Apps\\FluoRaPressee\\"),
            installer_mutex_name("C:\\Apps\\FluoRaPressee"),
        )

    def test_only_ascii_letters_are_lowered(self):
        # Inno Setup's Lowercase touches A-Z only, so non-ASCII must stay as it is.
        self.assertEqual(
            installer_mutex_name("C:\\Users\\小林\\Ä\\FRP"),
            "Global\\FluoRaPresseeRunning:c:/users/小林/Ä/frp",
        )

    def test_hold_does_nothing_from_source(self):
        create = unittest.mock.Mock()
        with patch.object(sys, "frozen", False, create=True):
            self.assertFalse(runtime_env.hold_installer_mutex(log=lambda _m: None, create=create))
        create.assert_not_called()

    def test_failure_to_create_is_not_fatal(self):
        with patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "platform", "win32"):
            held = runtime_env.hold_installer_mutex(
                log=lambda _m: None, create=lambda _name: (None, 5)
            )
        self.assertFalse(held)


class InstrumentMutexTests(unittest.TestCase):
    """The four outcomes of CreateMutexW in the 方針13 table."""

    def acquire(self, handle, error):
        closed = []
        result = acquire_instrument_mutex(
            create_mutex=lambda *_args: handle,
            get_last_error=lambda: error,
            close_handle=closed.append,
        )
        return result, closed

    def tearDown(self):
        runtime_env._held_handles.clear()

    def test_first_process_keeps_the_handle(self):
        result, closed = self.acquire(1234, 0)
        self.assertEqual(result, INSTRUMENT_ACQUIRED)
        self.assertEqual(closed, [])
        self.assertIn(1234, runtime_env._held_handles)

    def test_same_user_already_running(self):
        result, closed = self.acquire(1234, 183)
        self.assertEqual(result, INSTRUMENT_BUSY)
        self.assertEqual(closed, [1234])

    def test_other_user_already_running(self):
        result, _closed = self.acquire(None, 5)
        self.assertEqual(result, INSTRUMENT_BUSY_OTHER_USER)

    def test_unknown_failure_lets_start_up_continue(self):
        result, _closed = self.acquire(None, 1450)
        self.assertEqual(result, INSTRUMENT_UNVERIFIED)


class InstrumentStartupRefusalTests(unittest.TestCase):
    def setUp(self):
        from src.app_bootstrap import instrument_startup_refusal

        self.refusal = instrument_startup_refusal

    def test_busy_results_refuse_hardware_mode(self):
        for result in (INSTRUMENT_BUSY, INSTRUMENT_BUSY_OTHER_USER):
            with self.subTest(result=result):
                self.assertIsNotNone(self.refusal(False, acquire=lambda r=result: r))

    def test_other_results_allow_hardware_mode(self):
        for result in (INSTRUMENT_ACQUIRED, INSTRUMENT_UNVERIFIED, "not_applicable"):
            with self.subTest(result=result):
                self.assertIsNone(self.refusal(False, acquire=lambda r=result: r))

    def test_debug_mode_is_never_refused_and_takes_no_mutex(self):
        acquire = unittest.mock.Mock(return_value=INSTRUMENT_BUSY)
        self.assertIsNone(self.refusal(True, acquire=acquire))
        acquire.assert_not_called()


if __name__ == "__main__":
    unittest.main()
