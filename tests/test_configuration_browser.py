import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QRadioButton

from src.ui.configuration_browser import ConfigurationBrowserDialog


class _Catalog:
    def list_selectable(self, _hardware_context, *, active_only, limit):
        return {
            "items": [
                self._summary("cfg-1", "slot-1", "2026-07-23T10:00:00+09:00"),
                self._summary("cfg-2", "slot-2", "2026-07-23T11:00:00+09:00"),
            ],
            "total": 2,
            "catalog_revision": 1,
        }

    @staticmethod
    def _summary(configuration_id, slot_id, created_at):
        return {
            "configuration_id": configuration_id,
            "slot_id": slot_id,
            "active": True,
            "grating": {"grooves_per_mm": 0, "index": 1},
            "center_wavelength_nm": 686.485,
            "roi": {"mode": "1d_full", "start": None, "end": None},
            "calibration": {"unit": "Wavelength"},
            "created_at": created_at,
        }


class ConfigurationBrowserTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.dialog = ConfigurationBrowserDialog(
            _Catalog(), {}, active_configuration_id="cfg-2"
        )

    def _radios(self):
        return [
            self.dialog.table.cellWidget(row, 0).findChild(QRadioButton)
            for row in range(self.dialog.table.rowCount())
        ]

    def test_radio_column_requires_one_explicit_exclusive_selection(self):
        radios = self._radios()
        self.assertEqual(self.dialog.table.columnCount(), 6)
        self.assertFalse(self.dialog.btn_load.isEnabled())

        radios[0].setChecked(True)
        self.assertTrue(self.dialog.btn_load.isEnabled())
        radios[1].setChecked(True)

        self.assertFalse(radios[0].isChecked())
        self.assertTrue(radios[1].isChecked())

    def test_accept_uses_checked_radio_record(self):
        self._radios()[1].setChecked(True)

        self.dialog._accept_selection()

        self.assertEqual(self.dialog.selected_configuration_id, "cfg-2")
        self.assertEqual(self.dialog.selected_slot_id, "slot-2")

    def test_currently_applied_row_has_light_red_background(self):
        normal = self.dialog.table.item(0, 1).background().color()
        applied = self.dialog.table.item(1, 1).background().color()

        self.assertNotEqual(normal, self.dialog.APPLIED_ROW_COLOR)
        self.assertEqual(applied, self.dialog.APPLIED_ROW_COLOR)


if __name__ == "__main__":
    unittest.main()
