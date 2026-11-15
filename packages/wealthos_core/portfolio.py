"""Portfolio valuation, weighting and return construction.

The important subtlety in this module is :func:`time_weighted_returns`. A
portfolio's value rises both because its assets appreciate and because the
investor deposits money. Taking ``pct_change()`` of a portfolio value series
treats every deposit as if it were investment performance, which inflates
return, inflates volatility and makes Sharpe meaningless. Every return series
this platform reports for a contributing investor is time-weighted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import TRADING_DAYS_PER_YEAR

__all__ = [
    "position_values",
    "portfolio_weights",
    "position_value_frame",
    "portfolio_value_series",
    "time_weighted_returns",
    "money_weighted_return",
    "allocation_by",
    "portfolio_returns_from_weights",
]


def position_values(quantities, prices) -> pd.Series:
    """Current market value of each holding: ``quantity x price``."""
    q = pd.Series(quantities, dtype="float64")
    p = pd.Series(prices, dtype="float64")
    return (q * p.reindex(q.index)).dropna()


def portfolio_weights(values) -> pd.Series:
    """Fraction of total portfolio value in each holding."""
    from .concentration import normalize_weights

    return normalize_weights(values)


def position_value_frame(quantities, price_frame: pd.DataFrame) -> pd.DataFrame:
    """Value of each position over time, holding quantities fixed.

    ``price_frame`` is indexed by date with one column per symbol. Symbols with
    no price history are dropped. This is the "what if I had held today's
    positions throughout" view used for risk metrics on the current allocation;
    it is not a transaction-accurate history.
    """
    q = pd.Series(quantities, dtype="float64")
    prices = pd.DataFrame(price_frame).astype("float64")

    shared = [s for s in q.index if s in prices.columns]
    if not shared:
        return pd.DataFrame(index=prices.index)

    return prices[shared].mul(q[shared], axis=1)


def portfolio_value_series(quantities, price_frame: pd.DataFrame) -> pd.Series:
    """Total portfolio value over time for fixed quantities."""
    frame = position_value_frame(quantities, price_frame)
    if frame.empty:
        return pd.Series(dtype="float64")
    # Require every position priced on a date, so a symbol starting late does
    # not read as the portfolio suddenly gaining value.
    return frame.dropna(how="any").sum(axis=1)


def time_weighted_returns(
    values: pd.Series, cashflows: pd.Series | None = None
) -> pd.Series:
    """Return series with the effect of deposits and withdrawals removed.

    For each period::

        r_t = (V_t - CF_t) / V_{t-1} - 1

    where ``CF_t`` is the net external flow *into* the portfolio during period
    t (positive for a deposit, negative for a withdrawal). With no cash flows
    this reduces to an ordinary percentage change.

    The result measures how the investments performed, independent of how much
    money was added, which is the only basis on which volatility, Sharpe and
    drawdown are meaningful for a contributing investor.
    """
    v = pd.Series(values, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    if len(v) < 2:
        return pd.Series(dtype="float64", index=v.index[:0])

    if cashflows is None:
        flows = pd.Series(0.0, index=v.index)
    else:
        flows = pd.Series(cashflows, dtype="float64").reindex(v.index).fillna(0.0)

    previous = v.shift(1)
    returns = (v - flows) / previous - 1.0

    # A zero or negative prior value makes the ratio undefined.
    returns[previous <= 0] = np.nan
    return returns.iloc[1:]


def money_weighted_return(
    cashflows: pd.Series, final_value: float, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Internal rate of return (XIRR) on a dated series of external cash flows.

    Unlike the time-weighted return this *does* reward good contribution
    timing, so it answers "what did I earn on my money", while the
    time-weighted return answers "how did the investments perform".

    ``cashflows`` is indexed by date, negative for money paid in. The terminal
    ``final_value`` is treated as a positive flow on the last date.
    """
    flows = pd.Series(cashflows, dtype="float64").dropna()
    if flows.empty:
        return float("nan")

    try:
        dates = pd.to_datetime(flows.index)
    except (TypeError, ValueError):
        return float("nan")

    amounts = np.append(flows.to_numpy(), float(final_value))
    all_dates = dates.append(pd.DatetimeIndex([dates[-1]]))
    years = np.array([(d - all_dates[0]).days / 365.25 for d in all_dates])

    if amounts.min() >= 0 or amounts.max() <= 0:
        # IRR requires at least one inflow and one outflow to bracket a root.
        return float("nan")

    def net_present_value(rate: float) -> float:
        return float(np.sum(amounts / (1.0 + rate) ** years))

    low, high = -0.9999, 10.0
    f_low, f_high = net_present_value(low), net_present_value(high)
    if np.isnan(f_low) or np.isnan(f_high) or f_low * f_high > 0:
        return float("nan")

    for _ in range(200):  # bisection: robust where Newton diverges
        mid = (low + high) / 2.0
        f_mid = net_present_value(mid)
        if abs(f_mid) < 1e-9:
            return float(mid)
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return float((low + high) / 2.0)


def allocation_by(values, mapping) -> pd.Series:
    """Portfolio weights aggregated by sector, asset class or any grouping."""
    from .concentration import concentration_by_group

    return concentration_by_group(values, mapping)


def portfolio_returns_from_weights(
    weights, asset_returns: pd.DataFrame
) -> pd.Series:
    """Portfolio return series implied by fixed weights, rebalanced each period.

    Useful for comparing candidate allocations (equal-weight, max-Sharpe,
    min-variance) on the same history. Real portfolios drift between
    rebalances, so this is a model of a rebalanced portfolio, not of a
    buy-and-hold one.
    """
    from .concentration import normalize_weights

    w = normalize_weights(weights)
    frame = pd.DataFrame(asset_returns).astype("float64")

    shared = [s for s in w.index if s in frame.columns]
    if not shared:
        return pd.Series(dtype="float64")

    w = normalize_weights(w[shared])
    return frame[shared].mul(w, axis=1).sum(axis=1, min_count=1)
