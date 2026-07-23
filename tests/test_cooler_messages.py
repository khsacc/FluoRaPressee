import unittest

from src.ui import SpectrometerGUI


class _CapabilityState:
    pass


class CoolerMessageTests(unittest.TestCase):
    def test_close_message_does_not_mention_cooler_when_unavailable(self):
        state = _CapabilityState()
        state._temp_capability_known = True
        state._temp_control_available = False

        message = SpectrometerGUI._close_confirmation_message(state)

        self.assertEqual(message, "Are you sure you want to close FluoraPressée?")

    def test_close_message_mentions_cooler_when_available(self):
        state = _CapabilityState()
        state._temp_capability_known = True
        state._temp_control_available = True

        message = SpectrometerGUI._close_confirmation_message(state)

        self.assertIn("terminate the cooler", message)

    def test_unknown_capability_uses_generic_close_message(self):
        message = SpectrometerGUI._close_confirmation_message(_CapabilityState())

        self.assertNotIn("cooler", message)


if __name__ == "__main__":
    unittest.main()
