import tempfile
import unittest

from src.configuration_catalog import ConfigurationCatalog

try:
    from src.ui_mixins.file_io_mixin import FileIOMixin
    HAS_QT = True
except ModuleNotFoundError:
    class FileIOMixin:
        pass

    HAS_QT = False


class Checked:
    def __init__(self, checked=False):
        self.checked = checked

    def isChecked(self):
        return self.checked

    def setChecked(self, checked):
        self.checked = checked

    def blockSignals(self, _blocked):
        pass


class Value:
    def __init__(self, value=0):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def blockSignals(self, _blocked):
        pass


class Combo:
    def __init__(self, index=0):
        self.index = index

    def currentIndex(self):
        return self.index

    def setCurrentIndex(self, index):
        self.index = index


class Camera:
    det_width = 1024
    det_height = 127


class Spectrometer:
    def get_cached_hardware_metadata(self):
        return {
            "serial_number": "SPEC-1",
            "grating": {"index": 1, "grooves_per_mm": 600},
            "center_wavelength_nm": 689.9998,
        }


class Window(FileIOMixin):
    def __init__(self, catalog):
        self.configuration_catalog = catalog
        self.spec_ctrl = Spectrometer()
        self.thread = Camera()
        self.config = {
            "hardware_identity": {
                "spectrometer": {"model": "SP-2750", "serial_number": "SPEC-1"},
                "camera": {"model": "DU-401", "serial_number": "CAM-1"},
            },
            "grating": [
                {"index": 1, "grooves": 600},
                {"index": 2, "grooves": 1200},
            ],
        }
        self._camera_identity = {"model": "DU-401", "serial_number": "CAM-1"}
        self.combo_grating = Combo(0)
        self.physical_center_wl = 690.0
        self.radio_2d = Checked(False)
        self.radio_1d_full = Checked(False)
        self.radio_1d_roi = Checked(True)
        self.spin_vstart = Value(45)
        self.spin_vend = Value(65)
        self.radio_spec_mode_raman = Checked(False)
        self.radio_spec_mode_wl = Checked(True)
        self.spin_exc_wl = Value(532.0)
        self.spin_centre_wl = Value(690.0)
        self.lbl_centre = Label()
        self.roi_applied = False
        self.move_started = False

    def apply_roi_settings(self):
        self.roi_applied = True

    def on_apply_spectrometer(self):
        self.move_started = True


class Label:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable in this environment")
class ConfigurationUiFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.window = Window(ConfigurationCatalog(self.tempdir.name))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_register_uses_physical_grating_center_roi_and_not_acquisition(self):
        # A pending, unapplied combo-box selection must not be saved as the
        # physical grating on which calibration was actually performed.
        self.window.combo_grating.setCurrentIndex(1)
        record = self.window.register_current_configuration((1.0, 2.0, 3.0))

        self.assertEqual(record["spectrometer"]["grating_index"], 1)
        self.assertEqual(record["spectrometer"]["grating_grooves_per_mm"], 600)
        self.assertEqual(record["spectrometer"]["target_center_wavelength_nm"], 690.0)
        self.assertEqual(record["spectrometer"]["actual_center_wavelength_nm"], 689.9998)
        self.assertEqual(record["detector"]["roi_start"], 45)
        self.assertNotIn("exposure_time_s", record)

    def test_prepare_loads_complete_configuration_and_defers_calibration_until_move(self):
        record = self.window.register_current_configuration((1.0, 2.0, 3.0))
        self.window.combo_grating.setCurrentIndex(1)
        self.window.spin_vstart.setValue(1)
        self.window.spin_vend.setValue(2)

        self.window._prepare_configuration_for_loading(record)

        self.assertEqual(self.window.combo_grating.currentIndex(), 0)
        self.assertEqual(self.window.spin_vstart.value(), 45)
        self.assertEqual(self.window.spin_vend.value(), 65)
        self.assertTrue(self.window.roi_applied)
        self.assertTrue(self.window.move_started)
        self.assertTrue(self.window._loading_config)
        self.assertEqual(self.window._pending_calib_coeffs, (1.0, 2.0, 3.0))
        self.assertEqual(
            self.window._pending_configuration_id, record["configuration_id"]
        )


if __name__ == "__main__":
    unittest.main()
