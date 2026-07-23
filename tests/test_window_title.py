import unittest

from src.ui.window_title import live_window_title


class WindowTitleTests(unittest.TestCase):
    def test_hardware_mode_uses_connected_instrument_models(self):
        self.assertEqual(
            live_window_title(False, "Shamrock 303i", "iDus 416"),
            "FluoRaPressée: Shamrock 303i iDus 416",
        )

    def test_debug_mode_keeps_existing_title(self):
        self.assertIsNone(live_window_title(True, "Shamrock 303i", "iDus 416"))

    def test_title_waits_until_both_models_are_available(self):
        self.assertIsNone(live_window_title(False, "Shamrock 303i", None))


if __name__ == "__main__":
    unittest.main()
