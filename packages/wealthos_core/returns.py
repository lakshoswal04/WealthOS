"""Return calculations.

All functions take and return pandas objects and never mutate their inputs.
A function returns ``float('nan')`` rather than raising when the input is too
short to define the statistic, so callers can aggregate over many assets
without special-casing every thin series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import TRADING_DAYS_PER_YEAR

__all__ = [
    "simple_returns",
    "log_returns",
    "cumulative_return_series",
    "total_return",
    "annualized_return",
    "annualized_volatility",
    "cagr",
    "wealth_index",
]


def _clean(returns: pd.Series) -> pd.Series:
    """Drop NaNs and infinities from a return series."""
    return pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()


def simple_returns(prices: pd.Series) -> pd.Series:
    """Period-over-period simple return: ``P_t / P_{t-1} - 1``."""
    prices = pd.Series(prices, dtype="float64")
    # Guard against division by zero producing infinities on bad price data.
    return prices.pct_change().replace([np.inf, -np.inf], np.nan)


def log_returns(prices: pd.Series) -> pd.Series:
    """Continuously compounded return: ``ln(P_t / P_{t-1})``."""
    prices = pd.Series(prices, dtype="float64")
    safe = prices.where(prices > 0)
    return np.log(safe / safe.shift(1))


def wealth_index(returns: pd.Series, initial: float = 1.0) -> pd.Series:
    """Growth of ``initial`` invested at the start of the return series."""
    r = pd.Series(returns, dtype="float64").fillna(0.0)
    return initial * (1.0 + r).cumprod()


def cumulative_return_series(returns: pd.Series) -> pd.Series:
    """Running total return from the start of the series: ``prod(1+r) - 1``."""
    return wealth_index(returns) - 1.0


def total_return(returns: pd.Series) -> float:
    """Total compounded return over the whole series."""
    r = _clean(returns)
    if r.empty:
        return float("nan")
    return float((1.0 + r).prod() - 1.0)


def annualized_return(
    returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Geometric annualised return.

    Uses the compounded growth of the full series rather than the arithmetic
    mean, so it reflects what an investor actually earned.
    """
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    growth = float((1.0 + r).prod())
    if growth <= 0:
        # A total wipeout has no finite annualised growth rate.
        return float("nan")

    years = len(r) / periods_per_year
    if years <= 0:
        return float("nan")
    return float(growth ** (1.0 / years) - 1.0)


def annualized_volatility(
    returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Annualised standard deviation of returns (sample std, ddof=1)."""
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))


def cagr(start_value: float, end_value: float, years: float) -> float:
    """Compound annual growth rate between two values."""
    if start_value <= 0 or years <= 0 or end_value <= 0:
        return float("nan")
    return float((end_value / start_value) ** (1.0 / years) - 1.0)
