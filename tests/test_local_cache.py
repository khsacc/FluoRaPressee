import os
import tempfile
import unittest

import src.local_cache as local_cache


class LocalCacheTests(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(self._tmpdir.name)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    def test_load_missing_file_returns_empty_dict(self):
        self.assertEqual(local_cache.load_local_cache(), {})

    def test_save_then_load_round_trip(self):
        local_cache.save_local_cache("last_analysis_dir", "/some/path")
        self.assertEqual(
            local_cache.load_local_cache(), {"last_analysis_dir": "/some/path"}
        )

    def test_save_preserves_other_keys(self):
        local_cache.save_local_cache("a", 1)
        local_cache.save_local_cache("b", 2)
        self.assertEqual(local_cache.load_local_cache(), {"a": 1, "b": 2})


if __name__ == "__main__":
    unittest.main()
