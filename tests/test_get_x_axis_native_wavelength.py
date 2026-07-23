import unittest

import numpy as np

from src.ui_mixins.acquisition_mixin import AcquisitionMixin


class _Checked:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _Value:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Thread:
    def __init__(self, native_wavelengths=None):
        self.native_wavelengths = native_wavelengths


class _Host(AcquisitionMixin):
    """Exercises AcquisitionMixin.get_x_axis() directly - see
    work/work_OceanOptics.md Step 6. Mixins are plain Python classes (no QObject base) that
    only ever call self.xxx, so this only needs the attributes get_x_axis() itself reads."""

    def __init__(self, native_wavelengths=None, calib_coeffs=None, raman=False, exc_wl=532.0):
        self.thread = _Thread(native_wavelengths)
        self.calib_coeffs = calib_coeffs
        self.radio_spec_mode_raman = _Checked(raman)
        self.spin_exc_wl = _Value(exc_wl)


class GetXAxisNativeWavelengthTests(unittest.TestCase):
    def test_returns_native_wavelengths_when_uncalibrated_in_wavelength_mode(self):
        native = np.linspace(350.0, 1050.0, 128)
        host = _Host(native_wavelengths=native, calib_coeffs=None, raman=False)

        x = host.get_x_axis(128)

        np.testing.assert_array_equal(x, native)

    def test_converts_to_raman_shift_when_display_mode_is_raman(self):
        native = np.linspace(600.0, 700.0, 64)
        host = _Host(native_wavelengths=native, calib_coeffs=None, raman=True, exc_wl=532.0)

        x = host.get_x_axis(64)

        expected = 1e7 / 532.0 - 1e7 / native
        np.testing.assert_allclose(x, expected)

    def test_falls_back_to_pixel_index_when_no_native_wavelengths(self):
        host = _Host(native_wavelengths=None, calib_coeffs=None)

        x = host.get_x_axis(10)

        np.testing.assert_array_equal(x, np.arange(10))

    def test_falls_back_to_pixel_index_on_length_mismatch(self):
        native = np.linspace(350.0, 1050.0, 128)
        host = _Host(native_wavelengths=native, calib_coeffs=None)

        x = host.get_x_axis(64)  # length doesn't match native's 128

        np.testing.assert_array_equal(x, np.arange(64))

    def test_calibrated_axis_still_takes_priority_over_native_wavelengths(self):
        native = np.linspace(350.0, 1050.0, 128)
        host = _Host(native_wavelengths=native, calib_coeffs=(690.0, 0.1, 1e-6))

        x = host.get_x_axis(128)

        pixels = np.arange(128)
        expected = 690.0 + 0.1 * pixels + 1e-6 * pixels**2
        np.testing.assert_allclose(x, expected)


if __name__ == "__main__":
    unittest.main()
