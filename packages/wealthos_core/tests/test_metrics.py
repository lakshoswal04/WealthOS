"""Risk-adjusted ratios checked against closed-form values."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from wealthos_core import metrics as M
from wealthos_core.constants import TRADING_DAYS_PER_YEAR


def test_sharpe_is_zero_when_return_equals_the_risk_free_rate():
    # Construct a series whose annualised return is exactly 6%: a constant
    # daily return of 1.06**(1/252) - 1, plus noise to give it dispersion.
    rng = np.random.default_rng(2)
    daily = 1.06 ** (1 / TRADING_DAYS_PER_YEAR) - 1
    noise = rng.normal(0.0, 0.005, 2_520)
    r = pd.Series(daily + noise - noise.mean())

    assert M.sharpe_ratio(r, risk_free_rate=0.06) == pytest.approx(0.0, abs=0.05)


def test_sharpe_matches_a_hand_computed_value():
    # Annualised return and volatility are computed independently here, so the
    # assertion checks the division, not the inputs.
    rng = np.random.default_rng(31)
    r = pd.Series(rng.normal(0.0008, 0.012, 2_520))

    from wealthos_core.returns import annualized_return, annualized_volatility

    expected = (annualized_return(r) - 0.06) / annualized_volatility(r)
    assert M.sharpe_ratio(r, risk_free_rate=0.06) == pytest.approx(expected)


def test_sharpe_is_undefined_for_zero_volatility():
    # A riskless series has no denominator; NaN is correct, infinity is not.
    r = pd.Series([0.0002] * 300)
    assert math.isnan(M.sharpe_ratio(r))


def test_sortino_exceeds_sharpe_for_right_skewed_returns():
    # Large gains inflate total volatility but not downside volatility, so
    # Sortino must rank such a portfolio more favourably than Sharpe does.
    rng = np.random.default_rng(37)
    base = rng.normal(0.0005, 0.004, 2_520)
    base[::50] += 0.08  # occasional large gains, no extra losses
    r = pd.Series(base)

    assert M.sortino_ratio(r, 0.06) > M.sharpe_ratio(r, 0.06)


def test_sortino_is_undefined_when_nothing_falls_below_the_target():
    # Every return beats the MAR, so downside deviation is zero.
    r = pd.Series([0.01] * 300)
    assert math.isnan(M.sortino_ratio(r, risk_free_rate=0.0))


def test_calmar_is_annual_return_over_worst_drawdown():
    rng = np.random.default_rng(41)
    r = pd.Series(rng.normal(0.0006, 0.011, 2_520))

    from wealthos_core.returns import annualized_return
    from wealthos_core.risk import max_drawdown

    expected = annualized_return(r) / abs(max_drawdown(r))
    assert M.calmar_ratio(r) == pytest.approx(expected)


def test_treynor_divides_by_beta_not_volatility():
    rng = np.random.default_rng(43)
    market = pd.Series(rng.normal(0.0005, 0.01, 2_520))
    asset = 2.0 * market  # beta is exactly 2 by construction

    from wealthos_core.returns import annualized_return

    expected = (annualized_return(asset) - 0.06) / 2.0
    assert M.treynor_ratio(asset, market, 0.06) == pytest.approx(expected, rel=1e-6)


def test_performance_summary_reports_every_headline_metric():
    rng = np.random.default_rng(47)
    r = pd.Series(rng.normal(0.0006, 0.011, 1_260))
    market = pd.Series(rng.normal(0.0005, 0.010, 1_260))

    summary = M.performance_summary(r, market)

    required = {
        "observations", "total_return", "annualized_return",
        "annualized_volatility", "downside_deviation", "sharpe_ratio",
        "sortino_ratio", "calmar_ratio", "max_drawdown", "var_95", "cvar_95",
        "beta", "alpha", "treynor_ratio", "risk_free_rate", "periods_per_year",
    }
    assert required <= set(summary)
    assert summary["observations"] == 1_260


def test_performance_summary_without_a_benchmark_leaves_beta_undefined():
    rng = np.random.default_rng(53)
    summary = M.performance_summary(pd.Series(rng.normal(0.0, 0.01, 300)))

    assert math.isnan(summary["beta"])
    assert math.isnan(summary["alpha"])


def test_performance_summary_records_its_assumptions():
    # The risk-free rate and annualisation factor must travel with the numbers
    # they produced, so a reported Sharpe can always be reproduced.
    rng = np.random.default_rng(59)
    summary = M.performance_summary(pd.Series(rng.normal(0.0, 0.01, 300)), risk_free_rate=0.07)

    assert summary["risk_free_rate"] == 0.07
    assert summary["periods_per_year"] == TRADING_DAYS_PER_YEAR


def test_calmar_is_undefined_when_there_is_no_drawdown():
    # A never-declining series has a zero denominator. Floating point makes it
    # a tiny negative number rather than exactly zero, which must still be
    # treated as undefined rather than producing a ratio of order 1e16.
    r = pd.Series([0.001] * 300)
    assert math.isnan(M.calmar_ratio(r))


def test_treynor_is_undefined_for_zero_beta():
    rng = np.random.default_rng(61)
    market = pd.Series(rng.normal(0.0005, 0.01, 500))
    flat = pd.Series([0.0003] * 500)  # no covariance with the market

    assert math.isnan(M.treynor_ratio(flat, market))
