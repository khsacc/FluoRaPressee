import unittest

from src.hardware.spectrometer_oceanoptics import SpectrometerControllerOceanOptics, SpectrometerMoveThread


class CapabilitiesTests(unittest.TestCase):
    def test_reports_no_grating_or_movable_center(self):
        ctrl = SpectrometerControllerOceanOptics(debug=False)
        self.assertEqual(
            ctrl.get_capabilities(),
            {"supports_grating": False, "supports_movable_center": False},
        )

    def test_initialize_always_succeeds_without_touching_hardware(self):
        ctrl = SpectrometerControllerOceanOptics(debug=False)
        self.assertTrue(ctrl.initialize())
        self.assertTrue(ctrl.is_initialized)

    def test_get_gratings_matches_the_single_synthetic_slot(self):
        ctrl = SpectrometerControllerOceanOptics(debug=False)
        self.assertEqual(ctrl.get_gratings(), [{"index": 1, "grooves": 0}])


class FixedPositionRejectionTests(unittest.TestCase):
    """Covers work/work_OceanOptics.md Step 2's expanded verification list: this is the
    safety-critical logic that prevents a mismatched Configuration Load from silently
    "succeeding" a move that a fixed spectrometer cannot physically perform."""

    def setUp(self):
        self.ctrl = SpectrometerControllerOceanOptics(debug=False)
        self.ctrl.set_reference_center(700.123)

    def test_matching_center_and_grating_succeed(self):
        self.assertTrue(self.ctrl.set_grating(1))
        self.assertTrue(self.ctrl.set_wavelength(700.123))

    def test_center_within_tolerance_succeeds(self):
        self.assertTrue(self.ctrl.set_wavelength(700.1235))

    def test_mismatched_center_fails(self):
        self.assertFalse(self.ctrl.set_wavelength(650.0))

    def test_mismatched_grating_fails(self):
        self.assertFalse(self.ctrl.set_grating(2))

    def test_move_thread_reports_failure_and_message_on_mismatch(self):
        thread = SpectrometerMoveThread(self.ctrl, grating_index=1, wavelength=650.0)
        thread.run()  # call synchronously; this test only exercises the logic, not real QThread scheduling

        self.assertFalse(thread.success)
        self.assertTrue(thread.error_message)

    def test_move_thread_reports_success_on_matching_request(self):
        thread = SpectrometerMoveThread(self.ctrl, grating_index=1, wavelength=700.123)
        thread.run()

        self.assertTrue(thread.success)
        self.assertEqual(thread.error_message, "")

    def test_move_thread_failure_never_mutates_the_fixed_center(self):
        """A failed (mismatched) move must not leave the controller reporting the requested
        (wrong) value - get_wavelength() must still reflect the real, unchanged position."""
        thread = SpectrometerMoveThread(self.ctrl, grating_index=1, wavelength=650.0)
        thread.run()

        self.assertFalse(thread.success)
        self.assertEqual(self.ctrl.get_wavelength(), 700.123)


if __name__ == "__main__":
    unittest.main()
