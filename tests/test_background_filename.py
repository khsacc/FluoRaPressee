import unittest
from datetime import datetime

from src.ui_mixins.file_io_mixin import _background_default_filename


class BackgroundFilenameTests(unittest.TestCase):
    def setUp(self):
        self.timestamp = datetime(2026, 7, 23, 14, 5, 9)

    def test_custom_roi_filename_contains_acquisition_settings(self):
        filename = _background_default_filename(
            0.125, 7, 45, 65, True, self.timestamp
        )

        self.assertEqual(
            filename,
            "background_20260723_140509_acq_0.125s_accum_7"
            "_ROI_from_45_to_65.txt",
        )

    def test_full_roi_filename_contains_acquisition_settings(self):
        filename = _background_default_filename(
            1, 3, 0, 256, False, self.timestamp
        )

        self.assertEqual(
            filename,
            "background_20260723_140509_acq_1.000s_accum_3_ROI_full.txt",
        )
