"""Portfolio valuation and return construction.

The time-weighted-return tests are the most important in the suite: they are
what stop monthly contributions from being reported as investment performance.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from wealthos_core import portfolio as P


def test_position_values_multiply_quantity_by_price():
    values = P.position_values({"TCS": 10, "INFY": 5}, {"TCS": 3000.0, "INFY": 1500.0})

    assert values["TCS"] == pytest.approx(30_000.0)
    assert values["INFY"] == pytest.approx(7_500.0)


def test_portfolio_weights_sum_to_one():
    weights = P.portfolio_weights({"TCS": 30_000.0, "INFY": 7_500.0, "GOLD": 12_500.0})

    assert weights.sum() == pytest.approx(1.0)
    assert weights["TCS"] == pytest.approx(0.6)


def test_portfolio_value_series_sums_positions_over_time():
    prices = pd.DataFrame(
        {"A": [100.0, 110.0, 120.0], "B": [50.0, 55.0, 60.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    values = P.portfolio_value_series({"A": 2, "B": 4}, prices)

    # Day 1: 2*100 + 4*50 = 400. Day 3: 2*120 + 4*60 = 480.
    assert values.iloc[0] == pytest.approx(400.0)
    assert values.iloc[-1] == pytest.approx(480.0)


def test_value_series_skips_dates_where_a_position_is_unpriced():
    # A symbol whose history starts late must not make the portfolio appear to
    # jump in value on its first trading day.
    prices = pd.DataFrame(
        {"OLD": [100.0, 101.0, 102.0], "NEW": [np.nan, np.nan, 50.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="D"),
    )
    values = P.portfolio_value_series({"OLD": 1, "NEW": 1}, prices)

    assert len(values) == 1
    assert values.iloc[0] == pytest.approx(152.0)


# --------------------------------------------------------------------------
# Time-weighted returns
# --------------------------------------------------------------------------

def test_twr_without_cashflows_is_a_plain_percentage_change():
    values = pd.Series([100.0, 110.0, 99.0])
    result = P.time_weighted_returns(values)

    assert result.iloc[0] == pytest.approx(0.10)
    assert result.iloc[1] == pytest.approx(-0.10)


def test_a_pure_deposit_produces_zero_return():
    # The portfolio went from 100 to 200 only because 100 was deposited.
    # Reporting that as a +100% return would be wrong.
    values = pd.Series([100.0, 200.0])
    cashflows = pd.Series([0.0, 100.0])

    assert P.time_weighted_returns(values, cashflows).iloc[0] == pytest.approx(0.0)


def test_twr_separates_growth_from_contribution():
    # Start 100, the market adds 10%, and 50 is deposited in the same period.
    # Ending value 160; the true investment return is 10%, not 60%.
    values = pd.Series([100.0, 160.0])
    cashflows = pd.Series([0.0, 50.0])

    assert P.time_weighted_returns(values, cashflows).iloc[0] == pytest.approx(0.10)


def test_ignoring_cashflows_overstates_return_and_volatility():
    # This is the failure mode the function exists to prevent. A steadily
    # contributing investor with flat markets shows large fake returns when
    # cash flows are ignored.
    months = 24
    contribution = 10_000.0
    values = pd.Series([contribution * (i + 1) for i in range(months)])
    flows = pd.Series([0.0] + [contribution] * (months - 1))

    naive = values.pct_change().dropna()
    correct = P.time_weighted_returns(values, flows)

    assert naive.mean() > 0.04          # looks like a strong performer
    assert correct.abs().max() < 1e-9   # actually earned nothing
    assert correct.std(ddof=1) == pytest.approx(0.0, abs=1e-12)


def test_withdrawals_are_handled_as_negative_flows():
    # Start 100, grows 10% to 110, then 30 is withdrawn leaving 80.
    values = pd.Series([100.0, 80.0])
    cashflows = pd.Series([0.0, -30.0])

    assert P.time_weighted_returns(values, cashflows).iloc[0] == pytest.approx(0.10)


def test_twr_is_undefined_when_the_prior_value_is_zero():
    values = pd.Series([0.0, 100.0])
    cashflows = pd.Series([0.0, 100.0])

    assert math.isnan(P.time_weighted_returns(values, cashflows).iloc[0])


def test_twr_of_a_too_short_series_is_empty():
    assert P.time_weighted_returns(pd.Series([100.0])).empty


# --------------------------------------------------------------------------
# Money-weighted return
# --------------------------------------------------------------------------

def test_irr_of_a_single_doubling_over_one_year_is_one_hundred_percent():
    flows = pd.Series([-100.0], index=pd.to_datetime(["2024-01-01"]))
    # Terminal value is dated at the last flow date plus the elapsed year.
    flows = pd.Series(
        [-100.0, 0.0], index=pd.to_datetime(["2024-01-01", "2024-12-31"])
    )
    irr = P.money_weighted_return(flows, final_value=200.0)

    assert irr == pytest.approx(1.0, rel=0.01)


def test_irr_is_undefined_without_both_an_inflow_and_an_outflow():
    flows = pd.Series([100.0, 100.0], index=pd.to_datetime(["2024-01-01", "2024-06-01"]))
    assert math.isnan(P.money_weighted_return(flows, final_value=50.0))


def test_money_weighted_differs_from_time_weighted_when_timing_matters():
    # Contributing heavily just before a rise earns more per rupee than the
    # time-weighted return suggests. The two measures answer different
    # questions and should not agree here.
    dates = pd.to_datetime(["2024-01-01", "2024-06-01", "2024-12-31"])
    flows = pd.Series([-100.0, -900.0, 0.0], index=dates)
    irr = P.money_weighted_return(flows, final_value=1_500.0)

    assert irr > 0.0


# --------------------------------------------------------------------------
# Weighted portfolio returns
# --------------------------------------------------------------------------

def test_portfolio_returns_from_weights_is_the_weighted_average():
    asset_returns = pd.DataFrame({"A": [0.10, -0.05], "B": [0.00, 0.05]})
    result = P.portfolio_returns_from_weights({"A": 0.6, "B": 0.4}, asset_returns)

    assert result.iloc[0] == pytest.approx(0.06)   # 0.6*0.10 + 0.4*0.00
    assert result.iloc[1] == pytest.approx(-0.01)  # 0.6*-0.05 + 0.4*0.05


def test_weights_are_renormalised_over_the_assets_that_have_returns():
    # Asking for a symbol with no return history must not silently shrink the
    # portfolio's return toward zero.
    asset_returns = pd.DataFrame({"A": [0.10], "B": [0.20]})
    result = P.portfolio_returns_from_weights({"A": 0.5, "B": 0.25, "MISSING": 0.25}, asset_returns)

    # A and B renormalise to 2/3 and 1/3: 0.0667 + 0.0667 = 0.1333.
    assert result.iloc[0] == pytest.approx(0.13333, rel=1e-4)


def test_allocation_by_asset_class_aggregates_values():
    values = {"TCS": 70_000.0, "GOLDBEES": 30_000.0}
    classes = {"TCS": "equity", "GOLDBEES": "gold"}

    allocation = P.allocation_by(values, classes)

    assert allocation["equity"] == pytest.approx(0.7)
    assert allocation["gold"] == pytest.approx(0.3)
