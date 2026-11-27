"""Technical indicators, against hand-computed values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wealthos_core.indicators import (
    SNAPSHOT_FIELDS, bearish_engulfing, bullish_engulfing, crossed_above, doji, hammer,
    macd, relative_volume, rsi, shooting_star, sma, snapshot,
)


def test_sma_by_hand():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert sma(s, 3).isna().sum() == 2


def test_rsi_matches_a_wilder_loop():
    rng = np.random.default_rng(7)
    close = pd.Series(100 + rng.normal(0, 1, 80).cumsum())
    # Reference: Wilder's recursion, seeded with the exponential form pandas
    # uses (adjust=False starts from the first value).
    delta = close.diff().iloc[1:].to_numpy()
    gains, losses = np.clip(delta, 0, None), np.clip(-delta, 0, None)
    ag, al = gains[0], losses[0]
    for g, l in zip(gains[1:], losses[1:]):
        ag = ag + (g - ag) / 14
        al = al + (l - al) / 14
    expected = 100 - 100 / (1 + ag / al)
    assert rsi(close).iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_rsi_is_100_when_nothing_ever_falls():
    close = pd.Series(np.arange(1.0, 40.0))
    assert rsi(close).iloc[-1] == 100.0


def test_macd_is_the_difference_of_two_emas():
    close = pd.Series(np.linspace(100, 130, 60))
    m = macd(close)
    assert m["hist"].iloc[-1] == pytest.approx(m["macd"].iloc[-1] - m["signal"].iloc[-1])
    assert m["macd"].iloc[-1] > 0  # a steady rise puts the fast EMA above the slow


def test_relative_volume_excludes_the_day_itself():
    vol = pd.Series([100.0] * 20 + [300.0])
    assert relative_volume(vol).iloc[-1] == pytest.approx(3.0)


def test_a_series_that_only_becomes_defined_is_not_a_cross():
    fast = pd.Series([10.0, 10, 10, 10])
    slow = pd.Series([np.nan, np.nan, 5.0, 5.0])
    # Fast was "above" a NaN slow, then above a real slow: no cross occurred.
    assert not crossed_above(fast, slow).any()


def test_a_real_cross_is_detected_once():
    fast = pd.Series([1.0, 2, 3, 4, 5])
    slow = pd.Series([3.0, 3, 3, 3, 3])
    assert crossed_above(fast, slow).tolist() == [False, False, False, True, False]


def test_candlestick_patterns_by_hand():
    assert doji(100, 105, 95, 100.5)
    assert not doji(100, 105, 95, 104)
    assert hammer(100, 101, 90, 101)          # long lower shadow, close at the high
    assert shooting_star(100, 110, 99.5, 99)  # long upper shadow
    assert bullish_engulfing((105, 100), (99, 106))
    assert bearish_engulfing((100, 105), (106, 99))
    assert not bullish_engulfing((100, 105), (99, 106))  # previous candle rose


def test_snapshot_reports_missing_history_as_none():
    n = 60
    close = pd.Series(np.linspace(100, 120, n))
    frame = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                          "close": close, "volume": 1_000.0})
    snap = snapshot(frame)
    assert set(SNAPSHOT_FIELDS) <= set(snap)
    assert snap["sma_200"] is None and snap["above_sma_200"] is None
    assert snap["pct_from_52w_high"] is None
    assert snap["sma_50"] == pytest.approx(float(close.iloc[-50:].mean()))
    assert snap["change_1d_pct"] == pytest.approx((close.iloc[-1] / close.iloc[-2] - 1) * 100)
