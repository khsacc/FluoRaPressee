"""Regression test for work/work_OceanOptics.md review round 5, point 5:
AcquisitionMixin._sync_fixed_spectrometer_center() updated self.physical_center_wl and the
spec_ctrl's internal reference, but never the spin_centre_wl widget itself - so
FileIOMixin._save_data_to_path()'s legacy "center_wl" header field (which reads
spin_centre_wl.value() directly) stayed at its 0.0 placeholder forever, contradicting the
correct value recorded in hardware_metadata.
"""
import unittest

import numpy as np

from src.ui_mixins.acquisition_mixin import AcquisitionMixin


class _Thread:
    def __init__(self, native_wavelengths=None):
        self.native_wavelengths = native_wavelengths


class _SpecCtrl:
    def __init__(self):
        self.reference_center = None

    def set_reference_center(self, value):
        self.reference_center = value


class _SpinBox:
    """Minimal stand-in for CustomDoubleSpinBox: only the blockSignals/setValue/value
    surface _sync_fixed_spectrometer_center() actually touches."""

    def __init__(self, value=0.0):
        self._value = value
        self.blocked = False

    def blockSignals(self, blocked):
        self.blocked = blocked

    def setValue(self, value):
        self._value = value

    def value(self):
        return self._value


class _Host(AcquisitionMixin):
    def __init__(self, native_wavelengths):
        self.thread = _Thread(native_wavelengths)
        self.spec_ctrl = _SpecCtrl()
        self.spin_centre_wl = _SpinBox(0.0)
        self.physical_center_wl = 0.0


class SyncFixedSpectrometerCenterTests(unittest.TestCase):
    def test_spinbox_physical_center_and_controller_all_sync_to_the_median(self):
        native = np.linspace(350.0, 1050.0, 129)  # odd length -> median is exactly 700.0
        host = _Host(native)

        host._sync_fixed_spectrometer_center()

        self.assertAlmostEqual(host.spin_centre_wl.value(), 700.0)
        self.assertAlmostEqual(host.physical_center_wl, 700.0)
        self.assertAlmostEqual(host.spec_ctrl.reference_center, 700.0)

    def test_spinbox_signals_are_blocked_while_setting(self):
        # AcquisitionMixin.on_roi_spin_changed()/check_spectrometer_changes() etc. are wired to
        # spin_centre_wl.valueChanged - firing them here would be a spurious "user changed
        # the center" event during startup, not an intentional edit.
        captured = []
        host = _Host(np.linspace(350.0, 1050.0, 129))
        original_set_value = host.spin_centre_wl.setValue

        def tracking_set_value(value):
            captured.append(host.spin_centre_wl.blocked)
            original_set_value(value)

        host.spin_centre_wl.setValue = tracking_set_value

        host._sync_fixed_spectrometer_center()

        self.assertEqual(captured, [True])
        self.assertFalse(host.spin_centre_wl.blocked)  # unblocked again afterwards

    def test_no_native_wavelengths_leaves_everything_untouched(self):
        host = _Host(None)
        host.spin_centre_wl.setValue(123.0)
        host.physical_center_wl = 123.0

        host._sync_fixed_spectrometer_center()

        self.assertEqual(host.spin_centre_wl.value(), 123.0)
        self.assertEqual(host.physical_center_wl, 123.0)
        self.assertIsNone(host.spec_ctrl.reference_center)


if __name__ == "__main__":
    unittest.main()
