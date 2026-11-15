"""Risk-adjusted performance ratios.

Each ratio divides an excess return by a different notion of risk, so they
disagree by design: Sharpe penalises all variability, Sortino only harmful
variability, Calmar only the worst historical loss, and Treynor only
market-related risk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import DEFAULT_RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from .returns import _clean, annualized_return, annualized_volatility
from .risk import beta, downside_deviation, max_drawdown

# Denominators below this are treated as zero. Floating-point arithmetic gives
# a constant return series a standard deviation around 1e-18 rather than
# exactly 0, and dividing by that yields a nonsense ratio of order 1e16
# instead of the "undefined" the situation actually calls for.
_ZERO_TOLERANCE = 1e-12


def _is_effectively_zero(value: float) -> bool:
    return bool(np.isnan(value)) or abs(value) < _ZERO_TOLERANCE


__all__ = [
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "treynor_ratio",
    "performance_summary",
]


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Excess return per unit of total volatility.

    ``(annualised return - risk-free rate) / annualised volatility``
    """
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    annual_return = annualized_return(r, periods_per_year)
    annual_vol = annualized_volatility(r, periods_per_year)

    if np.isnan(annual_return) or _is_effectively_zero(annual_vol):
        return float("nan")
    return float((annual_return - risk_free_rate) / annual_vol)


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    minimum_acceptable_return: float | None = None,
) -> float:
    """Excess return per unit of *downside* volatility.

    Upside swings are not penalised. ``minimum_acceptable_return`` defaults to
    the risk-free rate, which is the common convention.
    """
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    mar = risk_free_rate if minimum_acceptable_return is None else minimum_acceptable_return

    annual_return = annualized_return(r, periods_per_year)
    downside = downside_deviation(r, mar, periods_per_year)

    if np.isnan(annual_return) or _is_effectively_zero(downside):
        # Zero downside deviation means the portfolio never fell below the MAR
        # over this sample. The ratio is undefined rather than infinite.
        return float("nan")
    return float((annual_return - mar) / downside)


def calmar_ratio(
    returns: pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float:
    """Annualised return divided by the absolute worst drawdown."""
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    annual_return = annualized_return(r, periods_per_year)
    worst = max_drawdown(r)

    if np.isnan(annual_return) or _is_effectively_zero(worst):
        return float("nan")
    return float(annual_return / abs(worst))


def treynor_ratio(
    returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Excess return per unit of market risk (beta) rather than total risk."""
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    annual_return = annualized_return(r, periods_per_year)
    asset_beta = beta(r, benchmark_returns)

    if np.isnan(annual_return) or _is_effectively_zero(asset_beta):
        return float("nan")
    return float((annual_return - risk_free_rate) / asset_beta)


def performance_summary(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> dict:
    """Every headline performance and risk figure for one return series.

    This is the single function the API and the ML feature builders both call,
    so a portfolio's Sharpe is computed identically at training and serving
    time.
    """
    from .returns import total_return
    from .risk import conditional_value_at_risk, value_at_risk

    r = _clean(returns)

    summary = {
        "observations": int(len(r)),
        "total_return": total_return(r),
        "annualized_return": annualized_return(r, periods_per_year),
        "annualized_volatility": annualized_volatility(r, periods_per_year),
        "downside_deviation": downside_deviation(r, risk_free_rate, periods_per_year),
        "sharpe_ratio": sharpe_ratio(r, risk_free_rate, periods_per_year),
        "sortino_ratio": sortino_ratio(r, risk_free_rate, periods_per_year),
        "calmar_ratio": calmar_ratio(r, periods_per_year),
        "max_drawdown": max_drawdown(r),
        "var_95": value_at_risk(r, 0.95),
        "cvar_95": conditional_value_at_risk(r, 0.95),
        "risk_free_rate": risk_free_rate,
        "periods_per_year": periods_per_year,
    }

    if benchmark_returns is not None:
        from .risk import alpha

        summary["beta"] = beta(r, benchmark_returns)
        summary["alpha"] = alpha(r, benchmark_returns, risk_free_rate, periods_per_year)
        summary["treynor_ratio"] = treynor_ratio(
            r, benchmark_returns, risk_free_rate, periods_per_year
        )
    else:
        summary["beta"] = float("nan")
        summary["alpha"] = float("nan")
        summary["treynor_ratio"] = float("nan")

    return summary
