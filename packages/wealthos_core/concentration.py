"""Concentration and diversification measures.

A portfolio is not diversified merely because it holds many securities. These
functions quantify how much of the money actually sits in how few places, at
the asset, sector and asset-class level.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "normalize_weights",
    "herfindahl_index",
    "normalized_herfindahl_index",
    "effective_number_of_holdings",
    "top_k_weight",
    "concentration_by_group",
    "concentration_report",
]


def normalize_weights(weights) -> pd.Series:
    """Coerce values to non-negative weights summing to 1.

    Accepts a Series, dict or array, and tolerates percentages (``40``) as well
    as fractions (``0.40``). Negative entries (short positions, which the MVP
    does not model) are dropped rather than silently distorting the sum.
    """
    series = pd.Series(weights, dtype="float64")
    series = series.replace([np.inf, -np.inf], np.nan).dropna()
    series = series[series > 0]

    total = float(series.sum())
    if series.empty or total <= 0:
        return pd.Series(dtype="float64")
    return series / total


def herfindahl_index(weights) -> float:
    """HHI: the sum of squared portfolio weights.

    Ranges from ``1/n`` (perfectly equal-weighted across n holdings) to ``1``
    (everything in one holding). Higher means more concentrated.
    """
    w = normalize_weights(weights)
    if w.empty:
        return float("nan")
    return float((w ** 2).sum())


def normalized_herfindahl_index(weights) -> float:
    """HHI rescaled to ``[0, 1]`` so portfolios of different sizes compare.

    ``(HHI - 1/n) / (1 - 1/n)``. 0 is perfectly equal-weighted, 1 is a single
    holding. Raw HHI cannot be compared across portfolios with different
    holding counts, because its floor moves with n; this one can.
    """
    w = normalize_weights(weights)
    n = len(w)
    if n == 0:
        return float("nan")
    if n == 1:
        return 1.0

    hhi = float((w ** 2).sum())
    floor = 1.0 / n
    return float((hhi - floor) / (1.0 - floor))


def effective_number_of_holdings(weights) -> float:
    """``1 / HHI`` — how many equally-weighted positions the portfolio behaves like.

    A 20-stock portfolio with 80% in one name has an effective count near 1.5,
    which communicates concentration far better than "20 holdings".
    """
    hhi = herfindahl_index(weights)
    if np.isnan(hhi) or hhi <= 0:
        return float("nan")
    return float(1.0 / hhi)


def top_k_weight(weights, k: int = 5) -> float:
    """Combined weight of the k largest positions."""
    w = normalize_weights(weights)
    if w.empty:
        return float("nan")
    return float(w.nlargest(min(k, len(w))).sum())


def concentration_by_group(weights, groups) -> pd.Series:
    """Aggregate weights up to a grouping (sector, asset class, ...).

    ``groups`` maps each weight's label to its group. Holdings with no mapping
    are grouped under ``"Unknown"`` rather than dropped, so the weights still
    sum to 1 and the gap is visible.
    """
    w = normalize_weights(weights)
    if w.empty:
        return pd.Series(dtype="float64")

    mapping = pd.Series(groups, dtype="object")
    labels = w.index.map(lambda key: mapping.get(key, "Unknown"))
    return w.groupby(labels).sum().sort_values(ascending=False)


def concentration_report(weights, sectors=None, asset_classes=None) -> dict:
    """Full concentration picture for one portfolio, as the API returns it."""
    w = normalize_weights(weights)

    report = {
        "n_holdings": int(len(w)),
        "hhi": herfindahl_index(w),
        "hhi_normalized": normalized_herfindahl_index(w),
        "effective_holdings": effective_number_of_holdings(w),
        "top_1_weight": top_k_weight(w, 1),
        "top_3_weight": top_k_weight(w, 3),
        "top_5_weight": top_k_weight(w, 5),
        "largest_holding": str(w.idxmax()) if not w.empty else None,
        "weights": {str(k): float(v) for k, v in w.sort_values(ascending=False).items()},
    }

    if sectors is not None:
        by_sector = concentration_by_group(w, sectors)
        report["sector_weights"] = {str(k): float(v) for k, v in by_sector.items()}
        report["sector_hhi"] = herfindahl_index(by_sector)
        report["n_sectors"] = int(len(by_sector))
        report["max_sector_weight"] = float(by_sector.max()) if len(by_sector) else float("nan")
        report["largest_sector"] = str(by_sector.idxmax()) if len(by_sector) else None

    if asset_classes is not None:
        by_class = concentration_by_group(w, asset_classes)
        report["asset_class_weights"] = {str(k): float(v) for k, v in by_class.items()}
        report["asset_class_hhi"] = herfindahl_index(by_class)
        report["n_asset_classes"] = int(len(by_class))

    return report
