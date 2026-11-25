"""Numeric pins on the v1 Health Score methodology.

The existing `test_health.py` is entirely property-based: it asserts that a
sound portfolio outscores a fragile one, that components renormalise when
inputs are missing, and that the total equals the weighted mean of its own
components. Every one of those assertions would still pass if every weight,
ramp endpoint, band boundary and grade cutoff in `health.py` were changed.

This file pins the numbers themselves, so that a methodology change is a
visible, deliberate diff rather than a silent one. Every expected value below
is derived by hand in the comment above it.

When the v2 methodology lands, these tests describe v1 and should be moved to
whatever keeps scoring v1 -- not quietly updated to match v2.
"""

from __future__ import annotations

import math

import pytest

from wealthos_core.health import (
    COMPONENT_WEIGHTS,
    DEFAULT_VOLATILITY_BAND,
    DRAWDOWN_TOLERANCE,
    RISK_TOLERANCE_VOLATILITY_BANDS,
    HealthInputs,
    _band_score,
    _grade,
    _ramp,
    compute_health_score,
)


# --------------------------------------------------------------------------
# The constants
# --------------------------------------------------------------------------

def test_the_six_weights_are_exactly_these_numbers():
    assert COMPONENT_WEIGHTS == {
        "diversification": 20.0,
        "risk": 20.0,
        "concentration": 15.0,
        "liquidity": 10.0,
        "goal_alignment": 20.0,
        "behaviour": 15.0,
    }
    assert sum(COMPONENT_WEIGHTS.values()) == 100.0


def test_volatility_bands_and_drawdown_tolerances_are_pinned():
    assert RISK_TOLERANCE_VOLATILITY_BANDS == {
        "conservative": (0.04, 0.10),
        "moderate": (0.08, 0.17),
        "aggressive": (0.14, 0.28),
    }
    assert DEFAULT_VOLATILITY_BAND == (0.08, 0.17)
    assert DRAWDOWN_TOLERANCE == {
        "conservative": 0.12,
        "moderate": 0.25,
        "aggressive": 0.40,
    }


@pytest.mark.parametrize("total,grade", [
    (100.0, "Excellent"),
    (85.0, "Excellent"),      # the boundary belongs to the better grade
    (84.999, "Good"),
    (70.0, "Good"),
    (69.999, "Fair"),
    (55.0, "Fair"),
    (54.999, "Needs attention"),
    (40.0, "Needs attention"),
    (39.999, "Poor"),
    (0.0, "Poor"),
])
def test_grade_cutoffs_are_85_70_55_40(total, grade):
    assert _grade(total) == grade


# --------------------------------------------------------------------------
# The scoring primitives
# --------------------------------------------------------------------------

def test_ramp_maps_worst_to_zero_and_best_to_one_hundred():
    assert _ramp(1.0, 1.0, 20.0) == 0.0
    assert _ramp(20.0, 1.0, 20.0) == 100.0
    # Midpoint of 1 -> 20 is 10.5: (10.5 - 1) / (20 - 1) = 9.5 / 19 = 0.5
    assert _ramp(10.5, 1.0, 20.0) == pytest.approx(50.0)


def test_ramp_clamps_outside_its_endpoints():
    assert _ramp(0.0, 1.0, 20.0) == 0.0        # below worst
    assert _ramp(50.0, 1.0, 20.0) == 100.0     # beyond best


def test_ramp_runs_backwards_when_lower_is_better():
    # hhi_normalized: worst 0.6, best 0.0. At 0.3,
    # (0.3 - 0.6) / (0.0 - 0.6) = -0.3 / -0.6 = 0.5
    assert _ramp(0.3, 0.6, 0.0) == pytest.approx(50.0)


def test_ramp_propagates_nan_and_handles_a_degenerate_range():
    assert math.isnan(_ramp(float("nan"), 0.0, 1.0))
    assert _ramp(5.0, 2.0, 2.0) == 100.0


def test_band_score_is_full_marks_inside_the_band_including_its_edges():
    low, high = DEFAULT_VOLATILITY_BAND          # (0.08, 0.17)
    assert _band_score(0.12, low, high) == 100.0
    assert _band_score(low, low, high) == 100.0
    assert _band_score(high, low, high) == 100.0


def test_band_score_penalises_overshoot_harder_than_undershoot():
    low, high = 0.08, 0.17                       # width 0.09
    # One full width under: distance 1.0, under_penalty 0.6
    #   100 - 100 * 1.0 * 0.6 = 40
    assert _band_score(low - 0.09, low, high) == pytest.approx(40.0)
    # One full width over: distance 1.0, over_penalty 1.0
    #   100 - 100 * 1.0 * 1.0 = 0
    assert _band_score(high + 0.09, low, high) == pytest.approx(0.0)
    # Half a width each way: 100 - 30 = 70 under, 100 - 50 = 50 over
    assert _band_score(low - 0.045, low, high) == pytest.approx(70.0)
    assert _band_score(high + 0.045, low, high) == pytest.approx(50.0)


def test_band_score_floors_at_zero_rather_than_going_negative():
    assert _band_score(5.0, 0.08, 0.17) == 0.0


# --------------------------------------------------------------------------
# The components, on one fully specified portfolio
# --------------------------------------------------------------------------

def _reference() -> HealthInputs:
    """A deliberately well-built portfolio, every input specified.

    Nothing is NaN, so no component renormalises away and each sub-score
    below can be derived by hand.
    """
    return HealthInputs(
        n_holdings=20, n_sectors=9, n_asset_classes=4,
        hhi_normalized=0.02, average_pairwise_correlation=0.20,
        annualized_volatility=0.12, max_drawdown=-0.15, risk_tolerance="moderate",
        top_1_weight=0.10, top_5_weight=0.45, max_sector_weight=0.22,
        asset_class_weights={"equity": 0.5, "debt": 0.25, "gold": 0.15, "cash": 0.10},
        has_goals=True, goal_progress_ratio=1.15, goal_funding_ratio=1.05,
        annual_turnover=0.15, contribution_consistency=1.0, allocation_drift=0.05,
    )


def _component(score, name):
    return next(c for c in score.components if c.name == name)


def test_diversification_component_on_the_reference_portfolio():
    # holdings      _ramp(20,  1.0, 20.0) -> 100
    # sectors       _ramp(9,   1.0,  8.0) -> clipped to 100
    # classes       _ramp(4,   1.0,  4.0) -> 100
    # evenness      _ramp(0.02, 0.6, 0.0) -> (0.02-0.6)/(0-0.6) = 0.96667 -> 96.667
    # correlation   _ramp(0.20, 0.9, 0.2) -> 100
    # mean = (100 + 100 + 100 + 96.667 + 100) / 5 = 99.333
    got = _component(compute_health_score(_reference()), "diversification")
    assert got.score == pytest.approx(99.333, abs=0.01)
    assert got.weight == 20.0


def test_risk_component_on_the_reference_portfolio():
    # volatility 0.12 sits inside the moderate band (0.08, 0.17)  -> 100
    # drawdown   abs(-0.15), tolerance 0.25, ramp worst = 0.25 * 2 = 0.50
    #            (0.15 - 0.50) / (0.0 - 0.50) = 0.70                -> 70
    # mean = (100 + 70) / 2 = 85
    got = _component(compute_health_score(_reference()), "risk")
    assert got.score == pytest.approx(85.0, abs=0.01)


def test_concentration_component_on_the_reference_portfolio():
    # top_1      _ramp(0.10, 0.50, 0.10) -> 100
    # top_5      _ramp(0.45, 1.00, 0.50) -> clipped to 100
    # max_sector _ramp(0.22, 0.70, 0.25) -> clipped to 100
    got = _component(compute_health_score(_reference()), "concentration")
    assert got.score == pytest.approx(100.0, abs=0.01)


def test_liquidity_component_is_the_raw_weighted_rating():
    # 0.5*0.70 (equity) + 0.25*0.75 (debt) + 0.15*0.80 (gold) + 0.10*1.00 (cash)
    #   = 0.35 + 0.1875 + 0.12 + 0.10 = 0.7575 -> 75.75
    got = _component(compute_health_score(_reference()), "liquidity")
    assert got.score == pytest.approx(75.75, abs=0.01)


def test_liquidity_cannot_fall_below_seventy_for_any_real_portfolio():
    """The component has almost no discriminating power, by construction.

    An all-equity portfolio -- the least liquid blend the universe allows --
    still scores 70. With a weight of 10, the component can only ever vary by
    about 3 points out of 100. Pinned because v2 is expected to change it.
    """
    worst = compute_health_score(
        HealthInputs(asset_class_weights={"equity": 1.0}, n_holdings=1)
    )
    assert _component(worst, "liquidity").score == pytest.approx(70.0)


def test_goal_alignment_component_on_the_reference_portfolio():
    # progress _ramp(1.15, 0.4, 1.2) -> 0.75/0.80  = 0.9375  -> 93.75
    # funding  _ramp(1.05, 0.4, 1.1) -> 0.65/0.70  = 0.92857 -> 92.857
    # mean = 93.304
    got = _component(compute_health_score(_reference()), "goal_alignment")
    assert got.score == pytest.approx(93.304, abs=0.01)


def test_behaviour_component_on_the_reference_portfolio():
    # turnover    _ramp(0.15, 2.0, 0.15) -> 100
    # consistency _ramp(1.00, 0.0, 1.00) -> 100
    # drift       _ramp(0.05, 0.60, 0.05) -> 100
    got = _component(compute_health_score(_reference()), "behaviour")
    assert got.score == pytest.approx(100.0, abs=0.01)


def test_total_on_the_reference_portfolio():
    # (99.333*20 + 85*20 + 100*15 + 75.75*10 + 93.304*20 + 100*15) / 100
    # = (1986.67 + 1700 + 1500 + 757.5 + 1866.07 + 1500) / 100 = 93.10
    score = compute_health_score(_reference())
    assert score.total == pytest.approx(93.10, abs=0.05)
    assert score.grade == "Excellent"
