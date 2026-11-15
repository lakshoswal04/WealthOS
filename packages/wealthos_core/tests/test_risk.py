"""Risk measures checked against hand-computed values and known price paths."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from wealthos_core import risk as K
from wealthos_core.constants import TRADING_DAYS_PER_YEAR


# --------------------------------------------------------------------------
# Drawdown
# --------------------------------------------------------------------------

def test_max_drawdown_on_a_known_path():
    # Wealth path 1.00 -> 1.50 -> 0.75 -> 1.20.
    # Peak 1.50, trough 0.75, so the worst decline is -50%.
    r = pd.Series([0.50, -0.50, 0.60])
    assert K.max_drawdown(r) == pytest.approx(-0.50)


def test_monotonically_rising_series_never_draws_down():
    r = pd.Series([0.01] * 50)
    assert K.max_drawdown(r) == pytest.approx(0.0, abs=1e-12)


def test_drawdown_series_is_never_positive():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.normal(0.0005, 0.012, 1_000))
    assert K.drawdown_series(r).max() <= 1e-12


def test_drawdown_detail_identifies_peak_and_trough():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    # 1.00 -> 1.50 (peak) -> 0.75 (trough) -> 1.65 (recovered past the peak)
    r = pd.Series([0.50, -0.50, 1.20], index=dates[1:])

    detail = K.drawdown_detail(r)

    assert detail["max_drawdown"] == pytest.approx(-0.50)
    assert detail["trough_date"] == dates[2]
    assert detail["recovered"] is True


def test_drawdown_detail_reports_unrecovered_drawdown():
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    r = pd.Series([0.50, -0.50], index=dates[1:])  # ends below the peak

    detail = K.drawdown_detail(r)

    assert detail["recovered"] is False
    assert detail["recovery_date"] is None


# --------------------------------------------------------------------------
# Downside deviation
# --------------------------------------------------------------------------

def test_downside_deviation_ignores_upside():
    # With MAR = 0 the only shortfall is the -0.02 observation.
    # mean(min(r,0)^2) over 4 points = 0.0004/4 = 0.0001, sqrt = 0.01.
    r = pd.Series([0.03, 0.05, -0.02, 0.01])
    expected = 0.01 * math.sqrt(TRADING_DAYS_PER_YEAR)

    assert K.downside_deviation(r, 0.0) == pytest.approx(expected, rel=1e-9)


def test_all_positive_returns_have_zero_downside_deviation():
    r = pd.Series([0.01, 0.02, 0.03])
    assert K.downside_deviation(r, 0.0) == pytest.approx(0.0, abs=1e-12)


def test_downside_deviation_averages_over_all_observations():
    # The denominator counts every observation, not only the losing ones.
    # Adding profitable periods must therefore LOWER downside deviation.
    losses_only = pd.Series([-0.02, -0.02])
    with_gains = pd.Series([-0.02, -0.02, 0.05, 0.05])

    assert K.downside_deviation(with_gains, 0.0) < K.downside_deviation(losses_only, 0.0)


# --------------------------------------------------------------------------
# Tail risk
# --------------------------------------------------------------------------

def test_historical_var_is_the_empirical_quantile():
    # 100 returns from -0.050 to +0.049 in 0.001 steps; the 5th percentile
    # of that uniform grid is about -0.005.
    r = pd.Series(np.arange(-50, 50) / 1000.0)
    assert K.value_at_risk(r, 0.95) == pytest.approx(np.quantile(r, 0.05))


def test_cvar_is_at_least_as_severe_as_var():
    # Expected shortfall averages the tail beyond VaR, so it cannot be milder.
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0.0, 0.02, 5_000))

    assert K.conditional_value_at_risk(r, 0.95) <= K.value_at_risk(r, 0.95)


def test_var_rejects_invalid_confidence():
    r = pd.Series([0.01, -0.01, 0.02])
    with pytest.raises(ValueError):
        K.value_at_risk(r, 1.5)


def test_gaussian_var_matches_closed_form_for_normal_data():
    # For N(0, 0.02), the 95% VaR is 0 + z(0.05) * 0.02 = -1.6449 * 0.02.
    rng = np.random.default_rng(11)
    r = pd.Series(rng.normal(0.0, 0.02, 200_000))

    assert K.value_at_risk(r, 0.95, method="gaussian") == pytest.approx(
        -1.6448536 * 0.02, rel=0.02
    )


# --------------------------------------------------------------------------
# Beta and alpha
# --------------------------------------------------------------------------

def test_beta_of_an_asset_against_itself_is_one():
    rng = np.random.default_rng(5)
    r = pd.Series(rng.normal(0.0, 0.01, 500))

    assert K.beta(r, r) == pytest.approx(1.0)


def test_beta_of_double_leverage_is_two():
    rng = np.random.default_rng(5)
    market = pd.Series(rng.normal(0.0, 0.01, 500))

    assert K.beta(2.0 * market, market) == pytest.approx(2.0)


def test_beta_is_zero_for_an_uncorrelated_asset():
    rng = np.random.default_rng(13)
    market = pd.Series(rng.normal(0.0, 0.01, 100_000))
    independent = pd.Series(rng.normal(0.0, 0.01, 100_000))

    assert K.beta(independent, market) == pytest.approx(0.0, abs=0.02)


def test_alpha_is_zero_when_the_asset_tracks_the_benchmark():
    # An asset identical to the benchmark earns exactly its CAPM-expected
    # return, so Jensen's alpha is zero regardless of the risk-free rate.
    rng = np.random.default_rng(17)
    market = pd.Series(rng.normal(0.0004, 0.01, 2_000))

    assert K.alpha(market, market, risk_free_rate=0.06) == pytest.approx(0.0, abs=1e-9)


def test_beta_aligns_series_on_index_before_computing():
    # Overlapping dates only; the unmatched tail must be ignored, not treated
    # as zero return.
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    market = pd.Series(np.linspace(0.01, 0.02, 10), index=idx)
    asset = pd.Series(np.linspace(0.02, 0.04, 6), index=idx[:6])

    assert not math.isnan(K.beta(asset, market))


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------

def test_average_pairwise_correlation_excludes_the_diagonal():
    # Two perfectly correlated columns average to 1.0, not to 1.0 inflated by
    # the self-correlations on the diagonal.
    rng = np.random.default_rng(23)
    base = rng.normal(0.0, 0.01, 300)
    frame = pd.DataFrame({"a": base, "b": base})

    assert K.average_pairwise_correlation(frame) == pytest.approx(1.0)


def test_average_pairwise_correlation_of_independent_assets_is_near_zero():
    rng = np.random.default_rng(29)
    frame = pd.DataFrame(rng.normal(0.0, 0.01, (20_000, 4)), columns=list("abcd"))

    assert K.average_pairwise_correlation(frame) == pytest.approx(0.0, abs=0.03)


def test_single_asset_has_undefined_average_correlation():
    frame = pd.DataFrame({"a": [0.01, 0.02, -0.01]})
    assert math.isnan(K.average_pairwise_correlation(frame))
