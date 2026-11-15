"""Return calculations checked against values computed by hand.

Every expected number in this file is derived analytically in the comment
above it, so a failure points at the formula rather than at a stored fixture.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from wealthos_core import returns as R
from wealthos_core.constants import TRADING_DAYS_PER_YEAR


def test_simple_returns_known_prices():
    # 100 -> 110 is +10%; 110 -> 99 is -10%.
    prices = pd.Series([100.0, 110.0, 99.0])
    result = R.simple_returns(prices)

    assert math.isnan(result.iloc[0])  # no prior price for the first row
    assert result.iloc[1] == pytest.approx(0.10)
    assert result.iloc[2] == pytest.approx(-0.10)


def test_log_returns_sum_to_total_log_growth():
    # Log returns are additive: their sum equals ln(P_last / P_first).
    prices = pd.Series([100.0, 120.0, 90.0, 150.0])
    log_r = R.log_returns(prices).dropna()

    assert log_r.sum() == pytest.approx(math.log(150.0 / 100.0))


def test_total_return_compounds_not_adds():
    # +10% then -10% leaves 0.99, a 1% loss -- not the 0% a naive sum gives.
    r = pd.Series([0.10, -0.10])
    assert R.total_return(r) == pytest.approx(-0.01)


def test_annualized_return_is_geometric():
    # 252 daily returns of exactly 0.1% compound to 1.001**252 - 1.
    r = pd.Series([0.001] * TRADING_DAYS_PER_YEAR)
    expected = 1.001 ** TRADING_DAYS_PER_YEAR - 1

    assert R.annualized_return(r) == pytest.approx(expected, rel=1e-9)


def test_annualized_return_over_two_years_halves_the_exponent():
    # The same daily return over two years annualises to the same figure.
    one_year = pd.Series([0.001] * TRADING_DAYS_PER_YEAR)
    two_years = pd.Series([0.001] * (2 * TRADING_DAYS_PER_YEAR))

    assert R.annualized_return(two_years) == pytest.approx(
        R.annualized_return(one_year), rel=1e-9
    )


def test_constant_returns_have_zero_volatility():
    # A series that never varies has no dispersion, whatever its level.
    r = pd.Series([0.01] * 100)
    assert R.annualized_volatility(r) == pytest.approx(0.0, abs=1e-12)


def test_annualized_volatility_scales_by_sqrt_time():
    # Daily sigma of 0.01 annualises to 0.01 * sqrt(252).
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0, 0.01, 50_000))

    assert R.annualized_volatility(r) == pytest.approx(
        0.01 * math.sqrt(TRADING_DAYS_PER_YEAR), rel=0.02
    )


def test_volatility_uses_sample_standard_deviation():
    # ddof=1 on [0.0, 0.02]: mean 0.01, sum sq dev 0.0002, var 0.0002, sd 0.01414...
    r = pd.Series([0.0, 0.02])
    expected = 0.01414213562373095 * math.sqrt(TRADING_DAYS_PER_YEAR)

    assert R.annualized_volatility(r) == pytest.approx(expected, rel=1e-9)


def test_wealth_index_tracks_compounded_growth():
    # 1 -> 1.10 -> 1.21 for two consecutive +10% periods.
    r = pd.Series([0.10, 0.10])
    wealth = R.wealth_index(r)

    assert wealth.iloc[0] == pytest.approx(1.10)
    assert wealth.iloc[1] == pytest.approx(1.21)


def test_cumulative_return_series_is_wealth_minus_one():
    r = pd.Series([0.05, -0.02, 0.03])
    assert R.cumulative_return_series(r).iloc[-1] == pytest.approx(
        R.total_return(r)
    )


def test_cagr_doubling_over_two_years():
    # Doubling in 2 years is sqrt(2) - 1 per year, about 41.42%.
    assert R.cagr(100.0, 200.0, 2.0) == pytest.approx(math.sqrt(2) - 1)


@pytest.mark.parametrize(
    "func", [R.annualized_return, R.annualized_volatility, R.total_return]
)
def test_empty_input_returns_nan_rather_than_raising(func):
    # Thin series must not blow up aggregation across many assets.
    assert math.isnan(func(pd.Series([], dtype="float64")))


def test_infinite_values_are_excluded():
    # A zero price produces an infinite return; it must be dropped, leaving
    # 1.01 * 1.02 - 1 = 0.0302.
    r = pd.Series([0.01, np.inf, 0.02, -np.inf])
    assert R.total_return(r) == pytest.approx(0.0302)


def test_total_return_ignores_non_finite_entries():
    clean = pd.Series([0.01, 0.02])
    dirty = pd.Series([0.01, np.inf, 0.02, np.nan])

    assert R.total_return(dirty) == pytest.approx(R.total_return(clean))
