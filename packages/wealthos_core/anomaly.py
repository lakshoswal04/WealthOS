"""Anomaly feature derivation and scoring, defined once.

This module exists because the same two things were written twice. The
feature derivations lived in ``ml/pipelines/p07_features.py`` for training and
again in ``backend/app/services/insight_service.py`` for serving, and the
error aggregation was a ``.mean(dim=1)`` hard-coded separately in the
training script and the service. Two copies of a formula is the exact
condition ``wealthos_core`` was created to prevent, and here it was latent:
adding a lag feature to the training table left the serving path building a
column it had never heard of, which ``reindex`` would have filled with zeros
without complaint. The model would have been handed a plausible-looking
feature vector and scored it confidently against a reference it did not match.

Nothing here imports a database, a model or a web framework; it is pandas and
numpy over frames, the same as the rest of the package.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "ALLOCATION_COLUMNS",
    "AGGREGATIONS",
    "derive_anomaly_features",
    "months_since_positive",
    "aggregate_error",
    "error_reference",
    "threshold_at_budget",
]

ALLOCATION_COLUMNS = (
    "equity_allocation", "etf_allocation", "gold_allocation",
    "debt_allocation", "cash_allocation",
)

AGGREGATIONS = ("mean", "max", "top3_mean", "zscore_mean", "zscore_max",
                "zscore_top3_mean")

# Months of trailing activity summarised by `recent_funding_rate`.
FUNDING_WINDOW = 6


def months_since_positive(series: pd.Series) -> pd.Series:
    """Rows since this series was last positive, counting the current row as 0.

    Used for "months since the investor last put money in". The current row
    is included, so a month carrying a contribution reads 0 and the silence
    before it is described by ``recent_funding_rate`` instead. Keeping the
    two separate is deliberate: a single column that reached backwards past
    the current month would encode the label it is meant to help predict.
    """
    out = np.zeros(len(series), dtype="float64")
    counter = 0.0
    for index, value in enumerate(series.to_numpy()):
        if value is not None and not pd.isna(value) and value > 0:
            counter = 0.0
        else:
            counter += 1.0
        out[index] = counter
    return pd.Series(out, index=series.index)


def derive_anomaly_features(
    frame: pd.DataFrame, group_key: str | None = "investor_id"
) -> pd.DataFrame:
    """Add every derived anomaly feature to a monthly snapshot frame.

    ``frame`` must be sorted by time within each group and carry the raw
    monthly columns: the five allocations, ``hhi``, ``top_holding_weight``,
    ``n_holdings``, ``turnover``, ``net_contribution`` and ``total_value``.

    ``group_key`` is the investor identifier during training, where one frame
    holds thousands of investors. At serving time a frame holds one user, so
    ``None`` treats the whole frame as a single series. Returns a copy;
    nothing is mutated in place.
    """
    out = frame.copy()
    columns = list(ALLOCATION_COLUMNS) + ["hhi", "top_holding_weight", "n_holdings"]

    if group_key is not None:
        grouped = out.groupby(group_key)
        for column in columns:
            out[f"delta_{column}"] = grouped[column].diff()
    else:
        for column in columns:
            out[f"delta_{column}"] = out[column].diff()

    # One number for "how much did this portfolio rearrange itself". Halved so
    # that moving a tenth of the portfolio reads as 0.10 rather than 0.20.
    out["allocation_shift"] = (
        out[[f"delta_{c}" for c in ALLOCATION_COLUMNS]].abs().sum(axis=1) / 2.0
    )

    out["contribution_ratio"] = (
        out["net_contribution"] / out["total_value"].replace(0, np.nan)
    )

    if group_key is not None:
        median_turnover = out.groupby(group_key)["turnover"].transform("median")
        out["turnover_ratio"] = out["turnover"] / median_turnover.replace(0, np.nan)
        out["months_since_contribution"] = (
            out.groupby(group_key, group_keys=False)["net_contribution"]
            .apply(months_since_positive)
        )
        out["delta_contribution_ratio"] = (
            out.groupby(group_key)["contribution_ratio"].diff()
        )
        funded = (out["net_contribution"] > 0).astype("float64")
        out["recent_funding_rate"] = (
            funded.groupby(out[group_key], group_keys=False)
            .apply(lambda s: s.shift(1).rolling(FUNDING_WINDOW, min_periods=1).mean())
        )
    else:
        median_turnover = out["turnover"].median()
        out["turnover_ratio"] = (
            out["turnover"] / median_turnover if median_turnover else 0.0
        )
        out["months_since_contribution"] = months_since_positive(out["net_contribution"])
        out["delta_contribution_ratio"] = out["contribution_ratio"].diff()
        funded = (out["net_contribution"] > 0).astype("float64")
        out["recent_funding_rate"] = (
            funded.shift(1).rolling(FUNDING_WINDOW, min_periods=1).mean()
        )

    return out


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def error_reference(per_feature_errors: np.ndarray) -> dict[str, np.ndarray]:
    """Per-feature error scale, to be computed on normal training rows only.

    Deriving this from the rows being scored would let them set their own
    scale, which is how an anomaly comes to look ordinary.
    """
    return {
        "mean": per_feature_errors.mean(axis=0),
        "std": per_feature_errors.std(axis=0) + 1e-12,
    }


def aggregate_error(
    per_feature_errors: np.ndarray,
    how: str,
    reference: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """Reduce per-row, per-feature squared error to one score per row.

    The original score was a flat mean across features, which assumes every
    feature is equally hard to reconstruct. They are not: a feature whose
    ordinary noise is large dominates the mean, so a clean deviation in two
    well-reconstructed features is averaged away against it. The ``zscore_*``
    variants divide each feature's error by its own scale on normal training
    rows first, which puts them on comparable footing.
    """
    errors = np.asarray(per_feature_errors, dtype="float64")
    if errors.ndim != 2:
        raise ValueError(f"expected a 2-D (rows, features) array, got {errors.shape}")

    if how.startswith("zscore_"):
        if reference is None:
            raise ValueError(f"{how} requires a per-feature reference scale")
        mean = np.asarray(reference["mean"], dtype="float64")
        std = np.asarray(reference["std"], dtype="float64")
        if mean.shape[0] != errors.shape[1]:
            raise ValueError(
                f"reference covers {mean.shape[0]} features but the errors "
                f"have {errors.shape[1]}; the artifact does not match the "
                "feature table"
            )
        errors = (errors - mean) / std
        how = how[len("zscore_"):]

    if how == "mean":
        return errors.mean(axis=1)
    if how == "max":
        return errors.max(axis=1)
    if how == "top3_mean":
        return np.sort(errors, axis=1)[:, -3:].mean(axis=1)
    raise ValueError(f"unknown aggregation {how!r}; expected one of {AGGREGATIONS}")


def threshold_at_budget(
    scores: np.ndarray, labels: np.ndarray, budget: float
) -> float:
    """Smallest threshold whose false-positive rate is within ``budget``.

    Used to express an operating point as a false-alert rate -- the cost a
    user actually bears -- rather than as a raw score, which is not
    comparable between periods.
    """
    normal = np.sort(np.asarray(scores)[np.asarray(labels) == 0])
    if normal.size == 0:
        return float("inf")
    index = int(np.ceil((1.0 - budget) * normal.size)) - 1
    return float(normal[int(np.clip(index, 0, normal.size - 1))])
