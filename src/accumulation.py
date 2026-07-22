"""AccumulationCombiner: combines raw detector frames from one accumulation
cycle into a single summed frame, with optional cosmic-ray spike rejection.

Pure NumPy, no Qt dependency - usable standalone and trivially testable,
mirroring the style of DataAnalyzer (analysis.py) and CalibrationCore
(calibration.py).
"""

import numpy as np


class AccumulationCombiner:
    """Cosmic-ray hits show up as a large, single-frame excursion at one pixel
    while every other frame agrees at that pixel. Comparing each frame to the
    per-pixel median (scaled by the Median Absolute Deviation) flags such
    spikes without needing any assumption about the real spectral shape."""

    # A per-pixel MAD estimated from only 3-4 frames is itself extremely noisy,
    # which (empirically verified) causes many false positives on ordinary shot/
    # read noise at low N even with a large threshold_k - 5 is the practical floor
    # where the sampling noise of the MAD estimate itself becomes small enough for
    # a fixed threshold_k to behave consistently.
    MIN_FRAMES_FOR_REJECTION = 5
    MAD_TO_SIGMA = 1.4826          # scales MAD to be comparable to a Gaussian std-dev
    SIGMA_FLOOR_COUNTS = 1.0       # guards perfectly-flat regions (MAD==0) from false positives

    @classmethod
    def combine(cls, frames, reject_spikes: bool, threshold_k: float):
        """Combine a single accumulation cycle's raw frames.

        Args:
            frames: list of np.ndarray (same shape), one per raw accumulation.
            reject_spikes: whether to run spike detection/replacement.
            threshold_k: sigma multiplier above which a value is flagged as a spike.

        Returns:
            (combined_sum, n_spikes_rejected). combined_sum has the same scale
            as a plain sum over all frames (preserves the "total counts over N
            accumulations" semantics the rest of the app assumes). n_spikes_rejected
            counts flagged (pixel, frame) values, not affected frames.
        """
        stack = np.stack([f.astype(np.float64) for f in frames], axis=0)

        if not reject_spikes or len(frames) < cls.MIN_FRAMES_FOR_REJECTION:
            return stack.sum(axis=0), 0

        median = np.median(stack, axis=0)
        mad = np.median(np.abs(stack - median), axis=0)
        sigma = np.maximum(mad * cls.MAD_TO_SIGMA, cls.SIGMA_FLOOR_COUNTS)

        spike_mask = (stack - median) > (threshold_k * sigma)  # one-sided: spikes are always positive excursions
        n_spikes = int(np.count_nonzero(spike_mask))
        if n_spikes == 0:
            return stack.sum(axis=0), 0

        corrected = np.where(spike_mask, median[np.newaxis, :], stack)
        return corrected.sum(axis=0), n_spikes
