import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import src.ui.local_cache as local_cache
from src.core.app_paths import ENV_DATA_DIR


def _save_many(data_dir, prefix, count):
    """Runs in a child process (spawned on Windows): save `count` distinct keys."""
    os.environ[ENV_DATA_DIR] = data_dir
    import src.ui.local_cache as cache

    for index in range(count):
        cache.save_local_cache(f"{prefix}{index}", index)


class LocalCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self._env = patch.dict(os.environ, {ENV_DATA_DIR: str(self.data_dir)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmpdir.cleanup()

    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(local_cache.load_local_cache(), {})

    def test_save_then_load_round_trip(self):
        local_cache.save_local_cache("last_analysis_dir", "/some/path")
        self.assertEqual(
            local_cache.load_local_cache(), {"last_analysis_dir": "/some/path"}
        )
        self.assertTrue((self.data_dir / "local_cache.json").is_file())

    def test_save_preserves_other_keys(self):
        local_cache.save_local_cache("a", 1)
        local_cache.save_local_cache("b", 2)
        self.assertEqual(local_cache.load_local_cache(), {"a": 1, "b": 2})

    def test_two_processes_saving_lose_nothing(self):
        """work_updater.md 方針13: read-modify-write is serialised across processes."""
        context = multiprocessing.get_context("spawn")
        workers = [
            context.Process(target=_save_many, args=(str(self.data_dir), prefix, 50))
            for prefix in ("live_", "analysis_")
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=120)
            self.assertEqual(worker.exitcode, 0)

        data = local_cache.load_local_cache()
        for prefix in ("live_", "analysis_"):
            for index in range(50):
                self.assertEqual(data.get(f"{prefix}{index}"), index)

    def test_failed_write_keeps_the_previous_file(self):
        local_cache.save_local_cache("a", 1)
        path = self.data_dir / "local_cache.json"
        original = path.read_text(encoding="utf-8")

        with patch("src.ui.local_cache.os.replace", side_effect=OSError("disk full")):
            local_cache.save_local_cache("b", 2)

        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.data_dir.glob("*.tmp")), [])

    def test_a_held_lock_is_given_up_quickly(self):
        local_cache.save_local_cache("a", 1)
        path = self.data_dir / "local_cache.json"
        with patch.object(local_cache, "LOCK_TIMEOUT_S", 0.2), \
                local_cache._locked(path, timeout=1.0):
            started = time.monotonic()
            local_cache.save_local_cache("b", 2)
            self.assertEqual(local_cache.load_local_cache(), {"a": 1})
            self.assertLess(time.monotonic() - started, 3.0)

        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"a": 1})


if __name__ == "__main__":
    unittest.main()
