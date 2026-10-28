"""Detector saturation warning based on a plateau at the raw-data maximum."""

import numpy as np


def is_saturated(data) -> bool:
    """Return whether three adjacent pixels share the non-zero data maximum.

    For a 2D detector image, adjacency is evaluated within each row; pixels
    at the end of one row and the start of the next are not adjacent.
    """
    values = np.asarray(data)
    if values.ndim not in (1, 2) or values.shape[-1] < 3:
        return False
    finite_values = values[np.isfinite(values)]
    if finite_values.size == 0:
        return False
    maximum = np.max(finite_values)
    if maximum == 0:
        return False
    at_maximum = values == maximum
    return bool(np.any(
        at_maximum[..., :-2] & at_maximum[..., 1:-1] & at_maximum[..., 2:]
    ))
