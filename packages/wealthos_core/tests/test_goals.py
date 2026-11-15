"""Goal projection arithmetic."""

from __future__ import annotations

from datetime import date

import pytest

from wealthos_core.goals import (
    future_value, months_between, project_goal, projection_path,
    required_monthly_contribution,
)


def test_months_between_counts_whole_months():
    assert months_between(date(2026, 1, 1), date(2027, 1, 1)) == 12
    assert months_between(date(2026, 1, 15), date(2026, 7, 15)) == 6
    # The target day has not been reached, so the month is not complete.
    assert months_between(date(2026, 1, 20), date(2026, 7, 15)) == 5
    assert months_between(date(2027, 1, 1), date(2026, 1, 1)) == 0  # never negative


def test_future_value_with_no_growth_is_simple_addition():
    assert future_value(100_000, 10_000, 0.0, 12) == pytest.approx(220_000)


def test_future_value_of_a_lump_sum_compounds():
    # 100,000 at 12% for 12 months of monthly compounding derived from the
    # annual rate geometrically returns exactly 112,000.
    assert future_value(100_000, 0, 0.12, 12) == pytest.approx(112_000, rel=1e-9)


def test_future_value_of_contributions_only():
    # 1,000 a month for 12 months at 12% a year, paid at month end.
    # r = 1.12^(1/12) - 1; FV = 1000 * ((1+r)^12 - 1)/r
    monthly_rate = 1.12 ** (1 / 12) - 1
    expected = 1_000 * ((1 + monthly_rate) ** 12 - 1) / monthly_rate
    assert future_value(0, 1_000, 0.12, 12) == pytest.approx(expected)


def test_future_value_at_zero_months_is_the_present_value():
    assert future_value(500_000, 10_000, 0.10, 0) == pytest.approx(500_000)


def test_required_contribution_reaches_the_target_exactly():
    # The defining property: contributing the required amount must land on
    # the target.
    target, present, rate, months = 5_000_000, 500_000, 0.10, 120

    required = required_monthly_contribution(target, present, rate, months)
    assert future_value(present, required, rate, months) == pytest.approx(target, rel=1e-6)


def test_no_contribution_needed_when_savings_already_grow_past_the_target():
    assert required_monthly_contribution(1_000_000, 900_000, 0.10, 120) == 0.0


def test_required_contribution_with_zero_return_is_the_plain_shortfall():
    assert required_monthly_contribution(1_200_000, 0, 0.0, 12) == pytest.approx(100_000)


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

def test_projection_reports_funding_and_shortfall_consistently():
    projection = project_goal(
        target_amount=10_000_000, current_amount=1_000_000,
        monthly_contribution=30_000, target_date=date(2036, 1, 1),
        expected_annual_return=0.10, return_volatility=0.12,
        as_of=date(2026, 1, 1), name="Retirement",
    )

    assert projection.funding_ratio == pytest.approx(
        projection.projected_value / projection.target_amount
    )
    assert projection.on_track == (projection.projected_value >= projection.target_amount)
    if projection.on_track:
        assert projection.shortfall == 0.0


def test_scenarios_are_ordered_and_always_present():
    projection = project_goal(
        target_amount=10_000_000, current_amount=1_000_000,
        monthly_contribution=30_000, target_date=date(2036, 1, 1),
        expected_annual_return=0.10, return_volatility=0.12, as_of=date(2026, 1, 1),
    )
    scenarios = projection.scenarios

    assert set(scenarios) == {"pessimistic", "expected", "optimistic"}
    assert (
        scenarios["pessimistic"]["projected_value"]
        < scenarios["expected"]["projected_value"]
        < scenarios["optimistic"]["projected_value"]
    )


def test_scenario_band_narrows_as_the_horizon_lengthens():
    # Uncertainty in the AVERAGE annual return scales as sigma/sqrt(years),
    # so a longer horizon has a tighter band around its mean return. Treating
    # a single year's volatility as a permanent shift would instead widen the
    # band without limit and produce absurd projections.
    def band(target_date: date) -> float:
        projection = project_goal(
            target_amount=10_000_000, current_amount=1_000_000,
            monthly_contribution=30_000, target_date=target_date,
            expected_annual_return=0.10, return_volatility=0.15,
            as_of=date(2026, 1, 1),
        )
        return (
            projection.scenarios["optimistic"]["annual_return"]
            - projection.scenarios["pessimistic"]["annual_return"]
        )

    assert band(date(2046, 1, 1)) < band(date(2029, 1, 1))


def test_projection_records_every_assumption():
    projection = project_goal(
        target_amount=1_000_000, current_amount=100_000, monthly_contribution=5_000,
        target_date=date(2031, 1, 1), expected_annual_return=0.09,
        return_volatility=0.11, as_of=date(2026, 1, 1),
    )
    assumptions = projection.assumptions

    assert assumptions["expected_annual_return"] == pytest.approx(0.09)
    assert assumptions["return_volatility"] == pytest.approx(0.11)
    assert "return_standard_error" in assumptions
    assert assumptions["contribution_timing"] == "end of month"
    # The projection must never present itself as a prediction.
    assert "not a prediction" in assumptions["note"]


def test_progress_ratio_distinguishes_ahead_from_behind():
    common = dict(
        target_amount=1_200_000, monthly_contribution=10_000,
        target_date=date(2031, 1, 1), expected_annual_return=0.10,
        as_of=date(2026, 1, 1), started_on=date(2021, 1, 1),
    )
    ahead = project_goal(current_amount=800_000, **common)
    behind = project_goal(current_amount=100_000, **common)

    assert ahead.progress_ratio > behind.progress_ratio
    assert ahead.progress_ratio > 1.0   # past the straight-line expectation
    assert behind.progress_ratio < 1.0


def test_an_already_due_goal_does_not_project_further_growth():
    projection = project_goal(
        target_amount=500_000, current_amount=480_000, monthly_contribution=10_000,
        target_date=date(2026, 1, 1), expected_annual_return=0.10,
        as_of=date(2026, 1, 1),
    )
    assert projection.months_remaining == 0
    assert projection.projected_value == pytest.approx(480_000)


def test_projection_path_length_matches_the_horizon():
    path = projection_path(100_000, 5_000, 0.10, 24)
    assert len(path) == 25            # the starting value plus 24 months
    assert path[0] == pytest.approx(100_000)
    assert path[-1] > path[0]


def test_projection_path_ends_where_future_value_says_it_should():
    path = projection_path(100_000, 5_000, 0.10, 36)
    assert path[-1] == pytest.approx(future_value(100_000, 5_000, 0.10, 36), rel=1e-9)
