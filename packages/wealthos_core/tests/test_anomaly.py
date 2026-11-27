"""The shared anomaly derivations and scoring.

These exist to stop the training and serving paths diverging again. Expected
values are derived by hand in the comment above each assertion.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from wealthos_core.anomaly import (
    AGGREGATIONS,
    ALLOCATION_COLUMNS,
    aggregate_error,
    derive_anomaly_features,
    error_reference,
    months_since_positive,
    threshold_at_budget,
)


def _frame(contributions, n=None, investor="a"):
    """A minimal monthly snapshot frame with the columns the deriver needs."""
    months = len(contributions)
    return pd.DataFrame({
        "investor_id": [investor] * months,
        "date": pd.date_range("2024-01-31", periods=months, freq="ME"),
        "equity_allocation": [0.6] * months,
        "etf_allocation": [0.2] * months,
        "gold_allocation": [0.1] * months,
        "debt_allocation": [0.1] * months,
        "cash_allocation": [0.0] * months,
        "hhi": [0.2] * months,
        "top_holding_weight": [0.3] * months,
        "n_holdings": [10.0] * months,
        "turnover": [100.0] * months,
        "net_contribution": list(contributions),
        "total_value": [10_000.0] * months,
    })


# --------------------------------------------------------------------------
# months_since_positive
# --------------------------------------------------------------------------

def test_months_since_positive_counts_from_the_last_funded_month():
    # Funded, silent, silent, funded -> 0, 1, 2, 0.
    series = pd.Series([500.0, 0.0, 0.0, 500.0])
    assert list(months_since_positive(series)) == [0.0, 1.0, 2.0, 0.0]


def test_months_since_positive_treats_nan_as_unfunded():
    series = pd.Series([500.0, float("nan"), 0.0])
    assert list(months_since_positive(series)) == [0.0, 1.0, 2.0]


def test_months_since_positive_counts_a_leading_silence():
    # No contribution has ever been seen, so the count simply accumulates.
    assert list(months_since_positive(pd.Series([0.0, 0.0, 0.0]))) == [1.0, 2.0, 3.0]


def test_a_negative_contribution_is_not_funding():
    # A withdrawal is not money going in.
    assert list(months_since_positive(pd.Series([500.0, -200.0]))) == [0.0, 1.0]


# --------------------------------------------------------------------------
# recent_funding_rate: the feature that makes a dormancy break visible
# --------------------------------------------------------------------------

def test_recent_funding_rate_excludes_the_current_month():
    """It must describe the past, or it leaks the event it is used to detect.

    A dormancy break *is* a funded month. If this feature included the
    current row, the model would see "funded" on the very row it is being
    asked to flag, which is label leakage dressed up as a feature.
    """
    # Four funded months, then three silent, then the break.
    frame = _frame([500.0] * 4 + [0.0] * 3 + [5000.0])
    out = derive_anomaly_features(frame, group_key="investor_id")

    rates = out["recent_funding_rate"].tolist()
    # Row 0 has no prior month at all.
    assert math.isnan(rates[0])
    # Row 4 looks back at four funded months: 4/4 = 1.0.
    assert rates[4] == pytest.approx(1.0)
    # Row 7 (the break) looks back at months 1-6: four funded, three silent
    # within the six-month window -> months 1,2,3 funded and 4,5,6 silent =
    # 3 of 6 = 0.5.
    assert rates[7] == pytest.approx(0.5)


def test_the_break_row_shows_a_silence_behind_it():
    frame = _frame([500.0] * 4 + [0.0] * 3 + [5000.0])
    out = derive_anomaly_features(frame, group_key="investor_id")

    break_row = out.iloc[7]
    # Funded this month, so the counter resets.
    assert break_row["months_since_contribution"] == 0.0
    # But the contribution ratio jumps: 5000/10000 - 0/10000 = 0.5.
    assert break_row["delta_contribution_ratio"] == pytest.approx(0.5)
    # And the trailing activity is visibly depressed.
    assert break_row["recent_funding_rate"] < 1.0


def test_a_steady_contributor_looks_nothing_like_a_break():
    """The discriminating comparison: same large contribution, no silence."""
    quiet_then_big = derive_anomaly_features(
        _frame([500.0] * 4 + [0.0] * 3 + [5000.0]), group_key="investor_id"
    ).iloc[7]
    always_funded = derive_anomaly_features(
        _frame([500.0] * 7 + [5000.0]), group_key="investor_id"
    ).iloc[7]

    assert quiet_then_big["recent_funding_rate"] < always_funded["recent_funding_rate"]
    assert always_funded["recent_funding_rate"] == pytest.approx(1.0)
    # Both received the same money, so a point-in-time feature cannot tell
    # them apart -- which is precisely why the lag features were needed.
    assert quiet_then_big["contribution_ratio"] == always_funded["contribution_ratio"]


# --------------------------------------------------------------------------
# Training and serving must derive identical columns
# --------------------------------------------------------------------------

def test_grouped_and_ungrouped_derivation_agree_for_a_single_investor():
    """Serving passes one user with group_key=None; training groups by id.

    If these disagree, the model is scored on different features from the
    ones it was fitted on, and nothing in the stack would say so.
    """
    contributions = [500.0, 0.0, 0.0, 800.0, 0.0, 1200.0, 0.0, 0.0, 6000.0]
    grouped = derive_anomaly_features(_frame(contributions), group_key="investor_id")
    single = derive_anomaly_features(_frame(contributions), group_key=None)

    derived = [
        "allocation_shift", "contribution_ratio", "turnover_ratio",
        "months_since_contribution", "delta_contribution_ratio",
        "recent_funding_rate",
    ] + [f"delta_{c}" for c in ALLOCATION_COLUMNS]

    for column in derived:
        pd.testing.assert_series_equal(
            grouped[column].reset_index(drop=True),
            single[column].reset_index(drop=True),
            check_names=False,
            obj=column,
        )


def test_derivation_does_not_mutate_its_input():
    frame = _frame([500.0] * 5)
    before = frame.copy()
    derive_anomaly_features(frame, group_key="investor_id")
    pd.testing.assert_frame_equal(frame, before)


def test_allocation_shift_is_halved_so_it_reads_as_a_share():
    """Moving a tenth of the portfolio should read 0.10, not 0.20."""
    frame = _frame([500.0, 500.0])
    frame.loc[1, "equity_allocation"] = 0.5
    frame.loc[1, "cash_allocation"] = 0.1

    out = derive_anomaly_features(frame, group_key="investor_id")
    # equity -0.10, cash +0.10 -> L1 of 0.20, halved to 0.10.
    assert out.iloc[1]["allocation_shift"] == pytest.approx(0.10)


def test_two_investors_do_not_contaminate_each_others_lags():
    first = _frame([500.0, 500.0, 500.0], investor="a")
    second = _frame([0.0, 0.0, 0.0], investor="b")
    combined = pd.concat([first, second], ignore_index=True)

    out = derive_anomaly_features(combined, group_key="investor_id")
    b_rows = out[out.investor_id == "b"]

    # b's first row must have no delta, not a's last value.
    assert math.isnan(b_rows.iloc[0]["delta_equity_allocation"])
    assert list(b_rows["months_since_contribution"]) == [1.0, 2.0, 3.0]


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def test_mean_aggregation_is_the_plain_row_mean():
    errors = np.array([[1.0, 3.0], [2.0, 8.0]])
    assert list(aggregate_error(errors, "mean")) == [2.0, 5.0]


def test_max_aggregation_takes_the_worst_feature():
    errors = np.array([[1.0, 3.0], [9.0, 2.0]])
    assert list(aggregate_error(errors, "max")) == [3.0, 9.0]


def test_top3_mean_averages_the_three_worst():
    # Row is 1,2,3,4,5 -> the three worst are 3,4,5 -> mean 4.0.
    errors = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    assert aggregate_error(errors, "top3_mean")[0] == pytest.approx(4.0)


def test_zscoring_puts_features_of_different_difficulty_on_one_scale():
    """The defect the z-scored variants exist to fix.

    Feature 0 is intrinsically noisy on normal rows (errors around 100);
    feature 1 is quiet (around 1). A row whose quiet feature is ten times its
    usual error is clearly unusual, but a flat mean buries that behind
    feature 0's ordinary noise.
    """
    normal = np.array([[100.0, 1.0], [110.0, 1.1], [90.0, 0.9]])
    reference = error_reference(normal)

    ordinary = np.array([[100.0, 1.0]])
    odd = np.array([[100.0, 10.0]])

    plain_gap = aggregate_error(odd, "mean")[0] - aggregate_error(ordinary, "mean")[0]
    zscored_gap = (
        aggregate_error(odd, "zscore_mean", reference)[0]
        - aggregate_error(ordinary, "zscore_mean", reference)[0]
    )

    # The mean moves by (10-1)/2 = 4.5 against a feature-0 scale of ~10.
    assert plain_gap == pytest.approx(4.5)
    # Z-scored, the same deviation is many standard deviations of its own
    # feature, so it dominates instead of being averaged away.
    assert zscored_gap > 10 * plain_gap


def test_a_zscored_aggregation_refuses_to_run_without_a_reference():
    with pytest.raises(ValueError, match="requires a per-feature reference"):
        aggregate_error(np.array([[1.0, 2.0]]), "zscore_mean")


def test_a_reference_of_the_wrong_width_is_rejected():
    """The guard that catches an artifact that predates a feature change.

    Silently broadcasting or truncating here would score a user against a
    scale belonging to a different feature set.
    """
    reference = {"mean": np.zeros(5), "std": np.ones(5)}
    with pytest.raises(ValueError, match="does not match the feature table"):
        aggregate_error(np.array([[1.0, 2.0]]), "zscore_mean", reference)


def test_an_unknown_aggregation_is_rejected_by_name():
    with pytest.raises(ValueError, match="unknown aggregation"):
        aggregate_error(np.array([[1.0]]), "median")


def test_a_one_dimensional_array_is_rejected():
    # Passing an already-reduced score would silently produce nonsense.
    with pytest.raises(ValueError, match="2-D"):
        aggregate_error(np.array([1.0, 2.0]), "mean")


@pytest.mark.parametrize("how", AGGREGATIONS)
def test_every_declared_aggregation_actually_works(how):
    normal = np.array([[1.0, 2.0], [1.5, 2.5], [0.5, 1.5]])
    reference = error_reference(normal)
    scores = aggregate_error(normal, how, reference)
    assert scores.shape == (3,)
    assert np.isfinite(scores).all()


def test_error_reference_never_divides_by_zero():
    """A feature reconstructed perfectly on every normal row has zero variance."""
    constant = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
    reference = error_reference(constant)
    assert reference["std"][0] > 0
    assert np.isfinite(aggregate_error(constant, "zscore_mean", reference)).all()


# --------------------------------------------------------------------------
# threshold_at_budget
# --------------------------------------------------------------------------

def test_threshold_at_budget_honours_the_false_alert_rate():
    # 1000 normal rows scored 0..999; a 1% budget should cut at the 99th
    # percentile, flagging about ten of them.
    scores = np.arange(1000, dtype="float64")
    labels = np.zeros(1000, dtype=int)

    cut = threshold_at_budget(scores, labels, 0.01)
    flagged = int((scores >= cut).sum())
    assert 9 <= flagged <= 11, flagged


def test_threshold_at_budget_ignores_the_anomalies():
    """The budget is a rate over normal rows; anomalies must not set it."""
    scores = np.concatenate([np.arange(100.0), np.full(50, 1e6)])
    labels = np.concatenate([np.zeros(100, dtype=int), np.ones(50, dtype=int)])

    cut = threshold_at_budget(scores, labels, 0.05)
    assert cut < 100.0


def test_threshold_at_budget_with_no_normal_rows_flags_nothing():
    cut = threshold_at_budget(np.array([1.0, 2.0]), np.array([1, 1]), 0.01)
    assert math.isinf(cut)
