import os
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from src.ui.ui_mixins.acquisition_mixin import AcquisitionMixin
    from src.ui.ui_mixins.display_mixin import DisplayMixin
except ImportError:
    AcquisitionMixin = None
    DisplayMixin = None


class _Value:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Checked:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _Label:
    def setText(self, text):
        self.text = text

    def setVisible(self, visible):
        self.visible = visible

    def hide(self):
        self.visible = False


class _Curve:
    def __init__(self):
        self.data = None

    def setData(self, *data):
        self.data = data

    def clear(self):
        self.data = None


class _ViewBox:
    def setLimits(self, **_kwargs):
        pass

    def setDefaultPadding(self, _padding):
        pass

    def enableAutoRange(self, **_kwargs):
        pass

    def disableAutoRange(self, **_kwargs):
        pass


class _PlotWidget:
    def __init__(self):
        self.view_box = _ViewBox()

    def getViewBox(self):
        return self.view_box

    def setClipToView(self, _enabled):
        pass


class _Stack:
    def setCurrentIndex(self, index):
        self.index = index


class _Text:
    def setHtml(self, html):
        self.html = html


class _Thread:
    is_measuring = True


class _PreviewWindow(AcquisitionMixin if AcquisitionMixin is not None else object):
    def __init__(self, *, cosmic_ray_removal=False):
        self.thread = _Thread()
        self.is_single_shot = False
        self._ignore_next_frames = False
        self._active_target_accum = None
        self.spin_accumulate = _Value(3 if not cosmic_ray_removal else 5)
        self.chk_cosmic_ray_removal = _Checked(cosmic_ray_removal)
        self.current_accum_count = 0
        self.accumulated_data = None
        self.accum_frames = None
        self.lbl_accum_status = _Label()
        self.preview_calls = []
        self.completed_calls = []
        self.raw_1d_data = np.array([99.0, 99.0])
        self._latest_hardware_capture = None
        self._hardware_capture_by_mode = {}

    def update_display(self, **kwargs):
        copied = dict(kwargs)
        if "display_data" in copied:
            copied["display_data"] = copied["display_data"].copy()
        self.preview_calls.append(copied)

    def _process_completed_data(self, mode, data):
        self.completed_calls.append((mode, data.copy()))


@unittest.skipIf(AcquisitionMixin is None, "PyQt6 is not installed")
class AccumulationLivePreviewTests(unittest.TestCase):
    def test_each_incomplete_frame_displays_the_running_sum_only(self):
        window = _PreviewWindow()

        window.on_data_ready("1d", np.array([1.0, 2.0]))
        window.on_data_ready("1d", np.array([3.0, 4.0]))

        self.assertEqual(len(window.preview_calls), 2)
        np.testing.assert_array_equal(
            window.preview_calls[0]["display_data"], [1.0, 2.0]
        )
        np.testing.assert_array_equal(
            window.preview_calls[1]["display_data"], [4.0, 6.0]
        )
        self.assertTrue(all(
            call["is_new_data"] is False and call["update_analysis"] is False
            for call in window.preview_calls
        ))
        np.testing.assert_array_equal(window.raw_1d_data, [99.0, 99.0])

    def test_cosmic_ray_mode_keeps_a_separate_running_preview_sum(self):
        window = _PreviewWindow(cosmic_ray_removal=True)

        window.on_data_ready("1d", np.array([10.0, 20.0]))
        window.on_data_ready("1d", np.array([1.0, 2.0]))

        np.testing.assert_array_equal(
            window.preview_calls[-1]["display_data"], [11.0, 22.0]
        )
        self.assertEqual(len(window.accum_frames), 2)

    def test_only_the_target_frame_count_is_committed_as_completed_data(self):
        window = _PreviewWindow()
        window.spin_accumulate = _Value(2)

        with patch(
            "src.ui.ui_mixins.acquisition_mixin.capture_hardware_state",
            return_value={"complete": True},
        ):
            window.on_data_ready("1d", np.array([1.0, 2.0]))
            window.on_data_ready("1d", np.array([3.0, 4.0]))

        self.assertEqual(len(window.preview_calls), 1)
        self.assertEqual(len(window.completed_calls), 1)
        self.assertEqual(window.completed_calls[0][0], "1d")
        np.testing.assert_array_equal(window.completed_calls[0][1], [4.0, 6.0])


@unittest.skipIf(DisplayMixin is None, "PyQt6 is not installed")
class PartialBackgroundDisplayTests(unittest.TestCase):
    def test_partial_preview_subtracts_the_complete_background(self):
        display = DisplayMixin()
        display.radio_bg_on = _Checked(True)
        display.chk_flip_x = _Checked(False)
        display.loaded_bg_data = np.array([10.0, 20.0])

        result = display._prepare_1d_display_data(np.array([3.0, 5.0]))

        np.testing.assert_array_equal(result, [-7.0, -15.0])

    def test_partial_display_does_not_replace_completed_saveable_data(self):
        display = DisplayMixin()
        display.update_plot_labels = lambda: None
        display.get_x_axis = lambda length: np.arange(length, dtype=float)
        display.radio_bg_on = _Checked(True)
        display.chk_flip_x = _Checked(False)
        display.radio_plot_scatter = _Checked(False)
        display.chk_rescale_x = _Checked(True)
        display.chk_rescale_y = _Checked(True)
        display.radio_fit_on = _Checked(True)
        display.loaded_bg_data = np.array([10.0, 20.0])
        display.raw_1d_data = np.array([100.0, 200.0])
        display.latest_1d_data = np.array([90.0, 180.0])
        display.plot_widget = _PlotWidget()
        display.plot_line = _Curve()
        display.plot_scatter = _Curve()
        display.fit_curve = _Curve()
        display.fit_baseline_curve = _Curve()
        display.fit_curve_sub1 = _Curve()
        display.fit_curve_sub2 = _Curve()
        display.edge_marker = _Label()
        display.fitting_text = _Text()
        display.stacked_widget = _Stack()

        display.update_display(
            mode="1d",
            display_data=np.array([3.0, 5.0]),
            update_analysis=False,
        )

        np.testing.assert_array_equal(display.latest_1d_data, [90.0, 180.0])
        np.testing.assert_array_equal(display._displayed_1d_data, [-7.0, -15.0])
        np.testing.assert_array_equal(display.plot_line.data[1], [-7.0, -15.0])
        self.assertIn("paused", display.fitting_text.html)


if __name__ == "__main__":
    unittest.main()
