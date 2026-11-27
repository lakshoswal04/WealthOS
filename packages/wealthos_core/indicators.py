"""Technical indicators and candlestick patterns.

Every function takes one symbol's daily series, oldest first, and returns
values aligned to it. Definitions follow the conventional ones so a figure
here matches what a charting platform shows for the same data:

* RSI uses Wilder's smoothing (an EMA with alpha = 1/period), not a simple
  average of gains and losses.
* MACD is EMA(12) - EMA(26), signal EMA(9) of that.
* Relative volume compares today with the *previous* 20 sessions, so a
  spike does not dilute its own baseline.

``snapshot`` reduces a frame to the latest value of every field the
screener language can filter on.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = [
    "sma", "ema", "rsi", "macd", "relative_volume", "crossed_above",
    "crossed_below", "doji", "bullish_engulfing", "bearish_engulfing",
    "hammer", "shooting_star", "snapshot", "SNAPSHOT_FIELDS",
]


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)
    # No losses at all is RSI 100, not a division-by-zero NaN.
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def relative_volume(volume: pd.Series, window: int = 20) -> pd.Series:
    baseline = volume.shift(1).rolling(window, min_periods=window).mean()
    return volume / baseline.replace(0, np.nan)


def _both_defined_yesterday(fast: pd.Series, slow: pd.Series) -> pd.Series:
    # Without this, the first bar a 200-day average exists reads as a cross:
    # the bar before it compares against NaN, which is "not above".
    return (fast.shift(1).notna() & slow.shift(1).notna() & fast.notna() & slow.notna())


def crossed_above(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True on the session ``fast`` closes above ``slow`` having been at or below."""
    above = fast > slow
    return above & ~above.shift(1, fill_value=True) & _both_defined_yesterday(fast, slow)


def crossed_below(fast: pd.Series, slow: pd.Series) -> pd.Series:
    below = fast < slow
    return below & ~below.shift(1, fill_value=True) & _both_defined_yesterday(fast, slow)


# --------------------------------------------------------------------------
# Candlestick patterns, on the latest bar(s)
# --------------------------------------------------------------------------

def _body(o: float, c: float) -> float:
    return abs(c - o)


def doji(o: float, h: float, l: float, c: float) -> bool:
    span = h - l
    return span > 0 and _body(o, c) <= 0.1 * span


def hammer(o: float, h: float, l: float, c: float) -> bool:
    span = h - l
    body = _body(o, c)
    lower = min(o, c) - l
    upper = h - max(o, c)
    return span > 0 and body > 0 and lower >= 2 * body and upper <= 0.3 * body + 0.05 * span


def shooting_star(o: float, h: float, l: float, c: float) -> bool:
    span = h - l
    body = _body(o, c)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return span > 0 and body > 0 and upper >= 2 * body and lower <= 0.3 * body + 0.05 * span


def bullish_engulfing(prev: tuple[float, float], cur: tuple[float, float]) -> bool:
    po, pc = prev
    co, cc = cur
    return pc < po and cc > co and co <= pc and cc >= po


def bearish_engulfing(prev: tuple[float, float], cur: tuple[float, float]) -> bool:
    po, pc = prev
    co, cc = cur
    return pc > po and cc < co and co >= pc and cc <= po


# --------------------------------------------------------------------------
# Snapshot for the screener
# --------------------------------------------------------------------------

SNAPSHOT_FIELDS: dict[str, str] = {
    "close": "Last close (₹)",
    "change_1d_pct": "1-day change (%)",
    "change_5d_pct": "5-day change (%)",
    "change_1m_pct": "1-month change (%)",
    "sma_20": "20-day average",
    "sma_50": "50-day average",
    "sma_200": "200-day average",
    "above_sma_50": "Above 50-day average",
    "above_sma_200": "Above 200-day average",
    "pct_from_52w_high": "Distance from 52-week high (%)",
    "pct_from_52w_low": "Distance above 52-week low (%)",
    "new_52w_high": "New 52-week high today",
    "new_52w_low": "New 52-week low today",
    "rsi_14": "RSI (14)",
    "macd_bullish_cross_3d": "MACD crossed above signal, last 3 sessions",
    "macd_bearish_cross_3d": "MACD crossed below signal, last 3 sessions",
    "golden_cross_10d": "50-day crossed above 200-day, last 10 sessions",
    "death_cross_10d": "50-day crossed below 200-day, last 10 sessions",
    "crossed_above_sma_50_5d": "Price crossed above 50-day, last 5 sessions",
    "crossed_below_sma_200_5d": "Price crossed below 200-day, last 5 sessions",
    "rel_volume": "Volume vs 20-session average (×)",
    "avg_value_cr": "Average daily traded value (₹ Cr, 20 sessions)",
    "volatility_20d_pct": "20-day annualised volatility (%)",
    "doji": "Doji",
    "hammer": "Hammer",
    "shooting_star": "Shooting star",
    "bullish_engulfing": "Bullish engulfing",
    "bearish_engulfing": "Bearish engulfing",
}


def _last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    value = series.iloc[-1]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _pct(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return (a / b - 1.0) * 100.0


def snapshot(frame: pd.DataFrame) -> dict[str, float | bool | None]:
    """Latest value of every screener field for one symbol.

    ``frame`` has columns open, high, low, close, volume, oldest first. A
    field that needs more history than exists is None, never a guess.
    """
    close, volume = frame["close"], frame["volume"]
    o, h, l, c = (float(frame[col].iloc[-1]) for col in ("open", "high", "low", "close"))
    n = len(frame)

    s20, s50, s200 = sma(close, 20), sma(close, 50), sma(close, 200)
    window = close.iloc[-252:]
    hi52, lo52 = float(window.max()), float(window.min())
    m = macd(close)
    rets = close.pct_change()

    def recent(flags: pd.Series, k: int) -> bool:
        return bool(flags.iloc[-k:].any()) if len(flags) else False

    out: dict[str, float | bool | None] = {
        "close": c,
        "change_1d_pct": _pct(c, float(close.iloc[-2])) if n >= 2 else None,
        "change_5d_pct": _pct(c, float(close.iloc[-6])) if n >= 6 else None,
        "change_1m_pct": _pct(c, float(close.iloc[-22])) if n >= 22 else None,
        "sma_20": _last(s20),
        "sma_50": _last(s50),
        "sma_200": _last(s200),
        "above_sma_50": (c > _last(s50)) if _last(s50) is not None else None,
        "above_sma_200": (c > _last(s200)) if _last(s200) is not None else None,
        "pct_from_52w_high": _pct(c, hi52) if n >= 200 else None,
        "pct_from_52w_low": _pct(c, lo52) if n >= 200 else None,
        "new_52w_high": bool(n >= 200 and c >= hi52),
        "new_52w_low": bool(n >= 200 and c <= lo52),
        "rsi_14": _last(rsi(close)),
        "macd_bullish_cross_3d": recent(crossed_above(m["macd"], m["signal"]), 3),
        "macd_bearish_cross_3d": recent(crossed_below(m["macd"], m["signal"]), 3),
        "golden_cross_10d": recent(crossed_above(s50, s200), 10),
        "death_cross_10d": recent(crossed_below(s50, s200), 10),
        "crossed_above_sma_50_5d": recent(crossed_above(close, s50), 5),
        "crossed_below_sma_200_5d": recent(crossed_below(close, s200), 5),
        "rel_volume": _last(relative_volume(volume)),
        "avg_value_cr": _last((close * volume).rolling(20, min_periods=20).mean() / 1e7),
        "volatility_20d_pct": _last(rets.rolling(20, min_periods=20).std() * math.sqrt(252) * 100),
        "doji": doji(o, h, l, c),
        "hammer": hammer(o, h, l, c),
        "shooting_star": shooting_star(o, h, l, c),
        "bullish_engulfing": False,
        "bearish_engulfing": False,
    }
    if n >= 2:
        prev = (float(frame["open"].iloc[-2]), float(frame["close"].iloc[-2]))
        out["bullish_engulfing"] = bullish_engulfing(prev, (o, c))
        out["bearish_engulfing"] = bearish_engulfing(prev, (o, c))
    return out
