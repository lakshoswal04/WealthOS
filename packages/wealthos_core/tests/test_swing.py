"""Tests for the swing-model building blocks.

The most important property of a market model's plumbing is that nothing
peeks at the future. Several tests here perturb prices *after* a date and
check that nothing computed *for* that date moves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wealthos_core import swing_features as sf
from wealthos_core.allocation import PROFILES, hrp_weights, profile_for
from wealthos_core.backtest_xs import cap_weights, rank_portfolio_backtest, select_names
from wealthos_core.conformal import apply_adjustment, coverage, cqr_adjustment
from wealthos_core.costs import DELIVERY, ZERO, CostModel
from wealthos_core.metrics import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from wealthos_core.regime import filtered_probabilities, gaussian_log_likelihoods
from wealthos_core.validation import daily_rank_ic, ic_summary, yearly_folds
from wealthos_core.volatility import HAR, forward_realised_vol, vol_design


def _panel(n_days: int = 700, n_stocks: int = 30, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_days)
    rows = []
    for i in range(n_stocks):
        r = rng.normal(0.0004, 0.018, n_days)
        close = 100 * np.exp(np.cumsum(r))
        open_ = close * np.exp(rng.normal(0, 0.004, n_days))
        high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n_days))
        low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n_days))
        vol = rng.integers(1e5, 1e6, n_days).astype(float) * (1 + i / 10)
        rows.append(pd.DataFrame({"date": dates, "symbol": f"S{i:02d}", "open": open_, "high": high,
                                  "low": low, "close": close, "volume": vol}))
    idx = 10000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n_days)))
    rows.append(pd.DataFrame({"date": dates, "symbol": "NIFTY", "open": idx, "high": idx, "low": idx,
                              "close": idx, "volume": 0.0}))
    vix = 15 + np.abs(rng.normal(0, 3, n_days))
    rows.append(pd.DataFrame({"date": dates, "symbol": "INDIAVIX", "open": vix, "high": vix, "low": vix,
                              "close": vix, "volume": 0.0}))
    return pd.concat(rows, ignore_index=True)


SECTORS = {f"S{i:02d}": "A" if i % 2 else "B" for i in range(30)}


# ---------------------------------------------------------------- features and targets

def test_features_do_not_use_the_future():
    panel = _panel()
    w = sf.to_wide(panel)
    cut = w.dates[500]
    base = sf.build_features(w, SECTORS, liquid_top=20)
    shocked = panel.copy()
    later = shocked["date"] > cut
    shocked.loc[later, ["open", "high", "low", "close"]] *= 3.0
    shocked.loc[later, "volume"] *= 10.0
    w2 = sf.to_wide(shocked)
    moved = sf.build_features(w2, SECTORS, liquid_top=20)
    a = base.loc[base.index.get_level_values("date") <= cut]
    b = moved.loc[moved.index.get_level_values("date") <= cut]
    pd.testing.assert_frame_equal(a, b)


def test_features_are_ranked_within_each_date():
    w = sf.to_wide(_panel())
    f = sf.build_features(w, SECTORS, liquid_top=None)
    stock = f[sf.STOCK_FEATURES]
    assert stock.min().min() > 0 and stock.max().max() <= 1.0
    assert set(f.columns) == set(sf.FEATURES)


def test_target_enters_at_next_open_and_exits_h_sessions_later():
    w = sf.to_wide(_panel())
    y = sf.build_targets(w, horizon=10, liquid_top=None)
    d = w.dates[400]
    sym = "S03"
    expected = w.close.loc[w.dates[410], sym] / w.open.loc[w.dates[401], sym] - 1.0
    assert y.loc[(d, sym), "fwd_ret"] == pytest.approx(expected)
    # Excess is zero-mean within a date; buckets are 0..4.
    day = y.xs(d, level="date")
    assert day["excess"].mean() == pytest.approx(0.0, abs=1e-12)
    assert set(day["bucket"].unique()) <= {0, 1, 2, 3, 4}


def test_liquidity_filter_is_point_in_time():
    w = sf.to_wide(_panel())
    e = sf.eligibility(w, liquid_top=10)
    later = e.loc[w.dates[300:]]
    assert (later.sum(axis=1) <= 10).all()
    # A stock's volume explosion *after* a date cannot make it eligible before.
    panel = _panel()
    panel.loc[(panel["symbol"] == "S00") & (panel["date"] > w.dates[500]), "volume"] *= 1000
    e2 = sf.eligibility(sf.to_wide(panel), liquid_top=10)
    pd.testing.assert_frame_equal(e.loc[: w.dates[500]], e2.loc[: w.dates[500]])


# ---------------------------------------------------------------- validation

def test_yearly_folds_purge_and_embargo():
    dates = pd.bdate_range("2010-01-01", "2016-12-31")
    folds = yearly_folds(dates, first_test_year=2014, horizon=10, embargo=5, min_train_years=3)
    assert [f.test_year for f in folds] == [2014, 2015, 2016]
    for f in folds:
        between = dates[(dates > f.train_end) & (dates < f.test_start)]
        assert len(between) == 15          # horizon + embargo sessions dropped
        # The last training label window (t+1..t+10) ends before the test year.
        last_label_day = dates[dates.get_loc(f.train_end) + 10]
        assert last_label_day < f.test_start


def test_rank_ic_perfect_and_inverse():
    dates = pd.bdate_range("2020-01-01", periods=5)
    idx = pd.MultiIndex.from_product([dates, [f"S{i}" for i in range(10)]], names=["date", "symbol"])
    target = np.tile(np.arange(10, dtype=float), 5)
    frame = pd.DataFrame({"score": target, "excess": target}, index=idx)
    assert daily_rank_ic(frame).mean() == pytest.approx(1.0)
    frame["score"] = -target
    assert daily_rank_ic(frame).mean() == pytest.approx(-1.0)
    s = ic_summary(pd.Series([0.02] * 100 + [0.04] * 100), horizon=10)
    assert s["mean_ic"] == pytest.approx(0.03) and s["t_stat"] > 0


# ---------------------------------------------------------------- costs and backtest

def test_cost_model_arithmetic():
    assert DELIVERY.buy_rate == pytest.approx(0.001 + 0.00015 + (0.0000297 + 0.000001) * 1.18 + 0.0005)
    assert DELIVERY.sell_rate == pytest.approx(0.001 + (0.0000297 + 0.000001) * 1.18 + 0.0005)
    assert ZERO.round_trip == 0.0
    assert CostModel(slippage=0.0).cost(100.0, 0.0) == pytest.approx(100 * CostModel(slippage=0.0).buy_rate)


def test_select_names_keeps_holdings_inside_buffer():
    scores = pd.Series({f"S{i}": float(30 - i) for i in range(30)})
    assert select_names(scores, held=[], top_n=3, buffer=6) == ["S0", "S1", "S2"]
    # S5 is held and still inside the top 6: kept; S20 is outside: dropped.
    assert select_names(scores, held=["S5", "S20"], top_n=3, buffer=6) == ["S5", "S0", "S1"]


def test_cap_weights_respects_cap_and_sums_to_one():
    w = cap_weights(pd.Series([10.0, 1.0, 1.0, 1.0, 1.0]), 0.3)
    assert w.max() <= 0.3 + 1e-9 and w.sum() == pytest.approx(1.0)


def test_backtest_trades_at_next_open_without_lookahead():
    dates = pd.bdate_range("2021-01-01", periods=6)
    close = pd.DataFrame({"A": [100, 100, 100, 100, 100, 100.0], "B": [100, 100, 100, 100, 100, 100.0]}, index=dates)
    open_ = close.copy()
    # B jumps 10% at the open of day 2; a signal on day 0 buys at day 1's open.
    open_.loc[dates[2], "B"] = 110
    close.loc[dates[2]:, "B"] = 110
    scores = pd.DataFrame(np.nan, index=dates, columns=["A", "B"])
    scores.loc[dates[0]] = [0.0, 1.0]          # prefer B
    r = rank_portfolio_backtest(scores, open_, close, top_n=1, rebalance_every=1, buffer=None, costs=ZERO)
    assert r.equity.iloc[-1] == pytest.approx(1.1)
    # The same signal one day too late (day 1, executed day 2 at 110) earns nothing.
    late = pd.DataFrame(np.nan, index=dates, columns=["A", "B"])
    late.loc[dates[1]] = [0.0, 1.0]
    r2 = rank_portfolio_backtest(late, open_, close, top_n=1, rebalance_every=1, buffer=None, costs=ZERO)
    assert r2.equity.iloc[-1] == pytest.approx(1.0)


def test_backtest_charges_costs_and_respects_exposure():
    dates = pd.bdate_range("2021-01-01", periods=4)
    px = pd.DataFrame({"A": [100.0] * 4}, index=dates)
    scores = pd.DataFrame({"A": [1.0, np.nan, np.nan, np.nan]}, index=dates)
    r = rank_portfolio_backtest(scores, px, px, top_n=1, rebalance_every=1, buffer=None,
                                exposure=pd.Series({dates[0]: 0.5}))
    assert r.exposure.iloc[-1] == pytest.approx(0.5, rel=1e-3)
    assert r.equity.iloc[-1] == pytest.approx(1.0 - 0.5 * DELIVERY.buy_rate, rel=1e-6)


# ---------------------------------------------------------------- allocation

def test_hrp_weights_valid_and_favour_low_vol():
    rng = np.random.default_rng(1)
    r = pd.DataFrame({"calm": rng.normal(0, 0.005, 300), "wild": rng.normal(0, 0.03, 300),
                      "mid": rng.normal(0, 0.012, 300)})
    w = hrp_weights(r)
    assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
    assert w["calm"] > w["mid"] > w["wild"]


def test_profiles_map_risk_tolerance():
    assert profile_for("conservative").max_exposure < profile_for("aggressive").max_exposure
    assert profile_for(None) == PROFILES["moderate"]
    assert profile_for("unknown") == PROFILES["moderate"]


# ---------------------------------------------------------------- conformal, Sharpe

def test_conformal_reaches_nominal_coverage():
    rng = np.random.default_rng(2)
    y_cal, y_test = rng.normal(0, 1, 4000), rng.normal(0, 1, 4000)
    lo, hi = np.full(4000, -0.5), np.full(4000, 0.5)          # far too narrow
    q = cqr_adjustment(y_cal, lo, hi, alpha=0.2)
    lo2, hi2 = apply_adjustment(lo, hi, q)
    assert coverage(y_test, lo, hi) < 0.5
    assert coverage(y_test, lo2, hi2) == pytest.approx(0.8, abs=0.03)


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0.0008, 0.01, 2000))
    one = deflated_sharpe_ratio(r, n_trials=1)["dsr"]
    many = deflated_sharpe_ratio(r, n_trials=200)["dsr"]
    assert one > many
    # Probabilistic Sharpe at the benchmark itself is a coin flip.
    assert probabilistic_sharpe_ratio(0.05, 0.05, 1000) == pytest.approx(0.5)


# ---------------------------------------------------------------- regime

def test_filtered_probabilities_match_brute_force_forward():
    rng = np.random.default_rng(4)
    k, d, t = 2, 1, 6
    start = np.array([0.6, 0.4])
    trans = np.array([[0.9, 0.1], [0.2, 0.8]])
    means = np.array([[0.0], [2.0]])
    covars = np.array([[[1.0]], [[0.5]]])
    x = rng.normal(0, 1.5, (t, d))
    got = filtered_probabilities(x, start, trans, means, covars)
    lik = np.exp(gaussian_log_likelihoods(x, means, covars))
    alpha = start * lik[0]
    alpha /= alpha.sum()
    expected = [alpha]
    for i in range(1, t):
        alpha = (alpha @ trans) * lik[i]
        alpha /= alpha.sum()
        expected.append(alpha)
    np.testing.assert_allclose(got, np.array(expected), rtol=1e-8)


def test_filtered_probabilities_ignore_later_observations():
    rng = np.random.default_rng(5)
    args = (np.array([0.5, 0.5]), np.array([[0.95, 0.05], [0.1, 0.9]]),
            np.array([[0.0], [3.0]]), np.array([[[1.0]], [[1.0]]]))
    x = rng.normal(0, 2, (50, 1))
    a = filtered_probabilities(x, *args)
    x2 = x.copy()
    x2[30:] += 10
    b = filtered_probabilities(x2, *args)
    np.testing.assert_allclose(a[:30], b[:30])


# ---------------------------------------------------------------- volatility

def test_har_recovers_volatility_persistence():
    w = sf.to_wide(_panel(n_days=900))
    design = vol_design(w.close, w.high, w.low)
    target = forward_realised_vol(w.close, 10)
    frame = pd.DataFrame({k: v.stack() for k, v in design.items()})
    frame["target"] = target.stack()
    frame = frame.dropna()
    har = HAR().fit(frame, frame["target"])
    pred = har.predict(frame)
    assert np.all(pred > 0)
    # Constant-volatility simulation: forecasts sit near the true 1.8% * sqrt(252).
    assert np.median(pred) == pytest.approx(0.018 * np.sqrt(252), rel=0.15)
