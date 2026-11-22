"""Per-process log files for windowed builds (work/work_updater.md 方針9, Step 2)."""
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.core import app_logging


class SetupStdioTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self._tmp.name) / "logs"
        self._saved = (sys.stdout, sys.stderr, sys.excepthook, app_logging._current_log_path)
        self._opened = []

    def tearDown(self):
        for stream in {sys.stdout, sys.stderr} - {self._saved[0], self._saved[1]}:
            try:
                stream.close()
            except Exception:
                pass
        sys.stdout, sys.stderr, sys.excepthook, app_logging._current_log_path = self._saved
        self._tmp.cleanup()

    def _windowed(self):
        sys.stdout = None
        sys.stderr = None

    def test_console_streams_are_left_in_place(self):
        stdout, stderr = sys.stdout, sys.stderr
        self.assertIsNone(app_logging.setup_stdio("live", logs_dir=self.logs))
        self.assertIs(sys.stdout, stdout)
        self.assertIs(sys.stderr, stderr)

    def test_windowed_output_goes_to_this_process_file(self):
        self._windowed()
        path = app_logging.setup_stdio(
            "live", logs_dir=self.logs, now=datetime(2026, 11, 21, 9, 30, 15), pid=12345
        )
        print("hello from the log")
        sys.stdout.flush()

        self.assertEqual(path.name, "app-live-20261121-093015-12345.log")
        self.assertIn("hello from the log", path.read_text(encoding="utf-8"))
        self.assertEqual(app_logging.current_log_path(), path)

    def test_two_processes_get_separate_files(self):
        # live and Analysis Mode running together must not share (or rename) a file.
        self._windowed()
        first = app_logging.setup_stdio("live", logs_dir=self.logs, pid=111)
        sys.stdout.close()
        self._windowed()
        second = app_logging.setup_stdio("analysis", logs_dir=self.logs, pid=222)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists() and second.exists())

    def test_unwritable_log_folder_does_not_stop_start_up(self):
        self.logs.parent.mkdir(parents=True, exist_ok=True)
        self.logs.write_text("a file where the folder should be", encoding="utf-8")
        self._windowed()

        path = app_logging.setup_stdio("live", logs_dir=self.logs)

        self.assertIsNone(path)
        print("still fine")
        sys.stdout.write("also fine\n")
        sys.stdout.flush()

    def test_uncaught_exceptions_are_logged(self):
        self._windowed()
        path = app_logging.setup_stdio("live", logs_dir=self.logs)
        try:
            raise ValueError("boom for the log")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        sys.stderr.flush()
        self.assertIn("boom for the log", path.read_text(encoding="utf-8"))


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, name, age_days):
        path = self.dir / name
        path.write_text("x", encoding="utf-8")
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_old_and_excess_files_are_removed_but_not_our_own(self):
        own = self.make("app-live-own.log", 40)  # old, but in use by this process
        old = self.make("app-live-old.log", 31)
        recent = [self.make(f"app-analysis-{i:03d}.log", i * 0.01) for i in range(5)]
        other = self.make("instrument_state.log", 400)

        app_logging.cleanup_old_logs(self.dir, keep=own, max_files=3)

        self.assertTrue(own.exists())
        self.assertFalse(old.exists())
        self.assertEqual([p.exists() for p in recent], [True, True, True, False, False])
        self.assertTrue(other.exists(), "only app-*.log is managed here")

    def test_a_file_that_cannot_be_deleted_is_skipped(self):
        self.make("app-live-locked.log", 60)
        self.make("app-live-free.log", 60)
        real_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "app-live-locked.log":
                raise PermissionError("in use by another process")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", unlink):
            app_logging.cleanup_old_logs(self.dir)

        self.assertTrue((self.dir / "app-live-locked.log").exists())
        self.assertFalse((self.dir / "app-live-free.log").exists())


if __name__ == "__main__":
    unittest.main()
