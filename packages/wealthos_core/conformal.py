"""Conformalised quantile regression (Romano, Patterson and Candès, 2019).

Quantile models trained with a pinball loss often produce intervals that are
too narrow out of sample. Conformal calibration widens (or narrows) them by
the amount a held-out calibration year says is needed, so an "80% range" is
an 80% range in the data rather than a label.
"""

from __future__ import annotations

import numpy as np

__all__ = ["cqr_adjustment", "apply_adjustment", "coverage"]


def cqr_adjustment(y: np.ndarray, lo: np.ndarray, hi: np.ndarray, alpha: float = 0.2) -> float:
    """The amount to widen [lo, hi] by for ``1 - alpha`` coverage."""
    y, lo, hi = (np.asarray(a, float) for a in (y, lo, hi))
    ok = ~(np.isnan(y) | np.isnan(lo) | np.isnan(hi))
    y, lo, hi = y[ok], lo[ok], hi[ok]
    n = len(y)
    if n == 0:
        return 0.0
    scores = np.maximum(lo - y, y - hi)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def apply_adjustment(lo: np.ndarray, hi: np.ndarray, q: float) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(lo) - q, np.asarray(hi) + q


def coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    y, lo, hi = (np.asarray(a, float) for a in (y, lo, hi))
    ok = ~(np.isnan(y) | np.isnan(lo) | np.isnan(hi))
    if not ok.any():
        return float("nan")
    return float(np.mean((y[ok] >= lo[ok]) & (y[ok] <= hi[ok])))
