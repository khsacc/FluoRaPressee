import sys
import types
import unittest

import numpy as np

from src.camera_oceanoptics import CameraThreadOceanOptics, CameraInitError


class _FakeSpectrometer:
    """Minimal stand-in for seabreeze.spectrometers.Spectrometer used by the tests below."""

    def __init__(self, model="USB4000", serial_number="FAKE0001", unsupported=()):
        self.model = model
        self.serial_number = serial_number
        self._unsupported = set(unsupported)  # subset of {"dark", "nonlinearity"}
        self.closed = False
        self.integration_time_calls = []
        self.intensities_calls = []

    def wavelengths(self):
        return np.linspace(350.0, 1050.0, 128)

    def integration_time_micros(self, value):
        self.integration_time_calls.append(value)

    def intensities(self, correct_dark_counts=False, correct_nonlinearity=False):
        self.intensities_calls.append((correct_dark_counts, correct_nonlinearity))
        if correct_dark_counts and "dark" in self._unsupported:
            raise _FakeSeaBreezeError("This device does not support dark count correction.")
        if correct_nonlinearity and "nonlinearity" in self._unsupported:
            raise _FakeSeaBreezeError("This device does not support nonlinearity correction.")
        return np.full(128, 100.0)

    def close(self):
        self.closed = True


class _FakeSeaBreezeError(Exception):
    pass


def _install_fake_seabreeze_module():
    """Inject a minimal fake `seabreeze.spectrometers` into sys.modules so that
    `from seabreeze.spectrometers import SeaBreezeError` succeeds without the real
    (optional) dependency installed - mirrors how src/camera_oceanoptics.py imports it
    lazily inside run()/its helper methods, never at module load time."""
    spectrometers_module = types.ModuleType("seabreeze.spectrometers")
    spectrometers_module.SeaBreezeError = _FakeSeaBreezeError
    seabreeze_module = types.ModuleType("seabreeze")
    seabreeze_module.spectrometers = spectrometers_module
    sys.modules["seabreeze"] = seabreeze_module
    sys.modules["seabreeze.spectrometers"] = spectrometers_module


def _uninstall_fake_seabreeze_module():
    sys.modules.pop("seabreeze", None)
    sys.modules.pop("seabreeze.spectrometers", None)


class WavelengthValidationTests(unittest.TestCase):
    def test_valid_array_passes(self):
        self.assertIsNone(
            CameraThreadOceanOptics._validate_native_wavelengths(np.linspace(350.0, 1050.0, 128))
        )

    def test_empty_array_is_rejected(self):
        reason = CameraThreadOceanOptics._validate_native_wavelengths(np.array([]))
        self.assertIn("empty", reason)

    def test_non_finite_values_are_rejected(self):
        arr = np.linspace(350.0, 1050.0, 128)
        arr[10] = np.nan
        reason = CameraThreadOceanOptics._validate_native_wavelengths(arr)
        self.assertIn("non-finite", reason)

    def test_non_monotonic_array_is_rejected(self):
        arr = np.linspace(350.0, 1050.0, 128)
        arr[5], arr[6] = arr[6], arr[5]
        reason = CameraThreadOceanOptics._validate_native_wavelengths(arr)
        self.assertIn("increasing", reason)


class CorrectionCapabilityProbeTests(unittest.TestCase):
    def setUp(self):
        _install_fake_seabreeze_module()
        self.addCleanup(_uninstall_fake_seabreeze_module)

    def test_both_supported(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread.spec = _FakeSpectrometer(unsupported=())

        supports_dark, supports_nonlinearity = thread._probe_correction_capabilities()

        self.assertTrue(supports_dark)
        self.assertTrue(supports_nonlinearity)
        # Both corrections must be probed independently (not a single combined call) so that
        # one unsupported correction can never mask the other's status - see
        # work/work_OceanOptics.md Step 1.
        self.assertIn((True, False), thread.spec.intensities_calls)
        self.assertIn((False, True), thread.spec.intensities_calls)
        self.assertIn((False, False), thread.spec.intensities_calls)

    def test_dark_unsupported_does_not_mask_nonlinearity_support(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread.spec = _FakeSpectrometer(unsupported=("dark",))

        supports_dark, supports_nonlinearity = thread._probe_correction_capabilities()

        self.assertFalse(supports_dark)
        self.assertTrue(supports_nonlinearity)

    def test_nonlinearity_unsupported_does_not_mask_dark_support(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread.spec = _FakeSpectrometer(unsupported=("nonlinearity",))

        supports_dark, supports_nonlinearity = thread._probe_correction_capabilities()

        self.assertTrue(supports_dark)
        self.assertFalse(supports_nonlinearity)

    def test_both_unsupported(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread.spec = _FakeSpectrometer(unsupported=("dark", "nonlinearity"))

        supports_dark, supports_nonlinearity = thread._probe_correction_capabilities()

        self.assertFalse(supports_dark)
        self.assertFalse(supports_nonlinearity)


class EffectiveCorrectionFlagTests(unittest.TestCase):
    def test_requested_and_supported_required_for_true(self):
        thread = CameraThreadOceanOptics(config={"correct_dark_counts": True, "correct_nonlinearity": True}, debug=False)
        thread._supports_dark_correction = False
        thread._supports_nonlinearity_correction = True

        dark, nonlinearity = thread._effective_correction_flags()

        self.assertFalse(dark)  # requested but not supported -> falls back to False
        self.assertTrue(nonlinearity)

    def test_not_requested_stays_false_even_if_supported(self):
        thread = CameraThreadOceanOptics(config={"correct_dark_counts": False, "correct_nonlinearity": False}, debug=False)
        thread._supports_dark_correction = True
        thread._supports_nonlinearity_correction = True

        dark, nonlinearity = thread._effective_correction_flags()

        self.assertFalse(dark)
        self.assertFalse(nonlinearity)


class CachedHardwareMetadataTests(unittest.TestCase):
    def test_native_wavelength_array_is_not_included_only_summary(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread.native_wavelengths = np.linspace(350.0, 1050.0, 2048)
        thread._supports_dark_correction = True
        thread._supports_nonlinearity_correction = False
        thread._requested_dark_counts = True
        thread._requested_nonlinearity = True

        metadata = thread.get_cached_hardware_metadata()

        self.assertNotIn("native_wavelengths", metadata)
        self.assertEqual(metadata["native_wavelength_range"]["count"], 2048)
        self.assertAlmostEqual(metadata["native_wavelength_range"]["min_nm"], 350.0)
        self.assertAlmostEqual(metadata["native_wavelength_range"]["max_nm"], 1050.0)
        self.assertTrue(metadata["hardware_dark_corrected"])
        self.assertFalse(metadata["nonlinearity_corrected"])  # requested but unsupported

    def test_no_native_wavelengths_yet(self):
        thread = CameraThreadOceanOptics(debug=False)

        metadata = thread.get_cached_hardware_metadata()

        self.assertIsNone(metadata["native_wavelength_range"])


class ExposureTokenContractTests(unittest.TestCase):
    def test_wait_resolves_once_seq_is_applied(self):
        thread = CameraThreadOceanOptics(debug=False)
        seq = thread.update_exposure(0.2)

        # No one has "applied" it yet - a short timeout must return False, not hang forever.
        self.assertFalse(thread.wait_for_exposure_applied(seq, timeout=0.05))

        with thread._lock:
            thread._exposure_applied_seq = seq
            thread._lock.notify_all()

        self.assertTrue(thread.wait_for_exposure_applied(seq, timeout=1.0))

    def test_newer_request_supersedes_older_seq(self):
        thread = CameraThreadOceanOptics(debug=False)
        first_seq = thread.update_exposure(0.1)
        second_seq = thread.update_exposure(0.2)
        self.assertGreater(second_seq, first_seq)

        with thread._lock:
            thread._exposure_applied_seq = second_seq
            thread._lock.notify_all()

        # An older token is satisfied by any later applied seq (>=), matching
        # camera_princeton.py's contract.
        self.assertTrue(thread.wait_for_exposure_applied(first_seq, timeout=1.0))


class ExposureValidationRangeTests(unittest.TestCase):
    """Regression test for review round 5, point 1 (P0): a rejected exposure write used to
    still advance _exposure_applied_seq and leave get_exposure_error() nonexistent, so a
    caller like ApiMixin._api_start_acquire() could not tell that current_exposure was left
    unchanged rather than actually reflecting its request."""

    def test_unknown_limits_never_reject(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread._integration_time_limits_us = None
        self.assertIsNone(thread._validate_exposure_range(10_000_000_000))

    def test_within_limits_passes(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread._integration_time_limits_us = (1_000, 10_000_000)
        self.assertIsNone(thread._validate_exposure_range(100_000))

    def test_below_minimum_is_rejected(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread._integration_time_limits_us = (1_000, 10_000_000)
        reason = thread._validate_exposure_range(10)
        self.assertIn("outside", reason)

    def test_above_maximum_is_rejected(self):
        thread = CameraThreadOceanOptics(debug=False)
        thread._integration_time_limits_us = (1_000, 10_000_000)
        reason = thread._validate_exposure_range(20_000_000)
        self.assertIn("outside", reason)


class ExposureErrorReportingTests(unittest.TestCase):
    """get_exposure_error(seq) is how callers distinguish "applied" from "failed but still
    resolved the wait" (see wait_for_exposure_applied()'s contract) - covers the same
    request-handling loop change as ExposureValidationRangeTests, at the seq-tracking level."""

    def test_no_error_reported_by_default(self):
        thread = CameraThreadOceanOptics(debug=False)
        seq = thread.update_exposure(0.2)
        with thread._lock:
            thread._exposure_applied_seq = seq
        self.assertIsNone(thread.get_exposure_error(seq))

    def test_error_recorded_for_the_failed_seq_is_reported(self):
        thread = CameraThreadOceanOptics(debug=False)
        seq = thread.update_exposure(20.0)
        with thread._lock:
            thread._exposure_error_seq = seq
            thread._exposure_error_message = "out of range"
            thread._exposure_applied_seq = seq  # a failure still resolves the wait
        self.assertTrue(thread.wait_for_exposure_applied(seq, timeout=1.0))
        self.assertEqual(thread.get_exposure_error(seq), "out of range")

    def test_error_for_a_different_seq_is_not_reported(self):
        thread = CameraThreadOceanOptics(debug=False)
        first_seq = thread.update_exposure(20.0)
        with thread._lock:
            thread._exposure_error_seq = first_seq
            thread._exposure_error_message = "out of range"
        second_seq = thread.update_exposure(0.2)
        self.assertIsNone(thread.get_exposure_error(second_seq))


class ConnectSpectrometerTests(unittest.TestCase):
    def test_missing_seabreeze_raises_clear_init_error(self):
        # sys.modules[name] = None is what CPython's import machinery treats as "this name
        # is known to be unimportable" and raises ImportError immediately - this forces the
        # "seabreeze is not installed" path deterministically regardless of whether the real
        # (optional) seabreeze package happens to be installed in the environment running
        # this test. Relying on it simply being absent (as a prior version of this test did)
        # made the test fail whenever seabreeze *was* actually installed (e.g. a dev .venv
        # set up for real Ocean Optics testing), since _connect_spectrometer() would then
        # reach a real seabreeze call and raise a different CameraInitError message that
        # doesn't mention "seabreeze" - see work/work_OceanOptics.md review round 5.
        _uninstall_fake_seabreeze_module()
        sys.modules["seabreeze"] = None
        self.addCleanup(sys.modules.pop, "seabreeze", None)
        thread = CameraThreadOceanOptics(debug=False)

        with self.assertRaisesRegex(CameraInitError, "seabreeze"):
            thread._connect_spectrometer()


class DebugModeSmokeTest(unittest.TestCase):
    def test_debug_run_reaches_init_finished_without_hardware(self):
        thread = CameraThreadOceanOptics(debug=True)
        events = []
        thread.init_finished.connect(lambda: events.append("init_finished"))
        thread.identity_ready.connect(lambda model, serial: events.append(("identity", model, serial)))
        thread.thread_active = False  # let the measurement loop exit immediately after init

        thread.run()

        self.assertIn("init_finished", events)
        self.assertEqual(thread.det_height, 1)
        self.assertGreater(thread.det_width, 0)
        self.assertIsNotNone(thread.native_wavelengths)


if __name__ == "__main__":
    unittest.main()
