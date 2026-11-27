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
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
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


# --------------------------------------------------------------------------
# Selection-bias-aware Sharpe (Bailey and López de Prado, 2012 and 2014)
# --------------------------------------------------------------------------

_EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe_ratio(
    sharpe: float, benchmark_sharpe: float, n_obs: int, skew: float = 0.0, kurtosis: float = 3.0
) -> float:
    """Probability that the true (per-period) Sharpe exceeds ``benchmark_sharpe``.

    Both Sharpe ratios are per period (not annualised). ``kurtosis`` is the
    ordinary kurtosis (3 for a normal distribution), not excess kurtosis.
    """
    from scipy.stats import norm

    if n_obs < 2 or np.isnan(sharpe):
        return float("nan")
    denom = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2
    if denom <= 0:
        return float("nan")
    z = (sharpe - benchmark_sharpe) * np.sqrt(n_obs - 1) / np.sqrt(denom)
    return float(norm.cdf(z))


def deflated_sharpe_ratio(
    returns: pd.Series, n_trials: int, trial_sharpe_std: float | None = None
) -> dict:
    """Probability the strategy's Sharpe is real after trying ``n_trials`` variants.

    Testing many configurations and keeping the best inflates the winner's
    Sharpe. The deflated Sharpe ratio raises the bar to the Sharpe expected
    from the best of ``n_trials`` skill-less strategies, then asks how likely
    the observed one beats it. ``trial_sharpe_std`` is the spread of
    per-period Sharpe ratios across the trials; without it, the sampling
    standard error of a single Sharpe estimate is used.
    """
    from scipy.stats import kurtosis as _kurt
    from scipy.stats import norm
    from scipy.stats import skew as _skew

    r = _clean(returns)
    n = len(r)
    if n < 10 or r.std(ddof=1) == 0:
        return {"dsr": float("nan"), "sharpe_per_period": float("nan"), "benchmark_sharpe_per_period": float("nan"),
                "n_trials": int(n_trials), "n_obs": int(n)}
    sr = float(r.mean() / r.std(ddof=1))
    sk = float(_skew(r))
    ku = float(_kurt(r, fisher=False))
    sd = trial_sharpe_std if trial_sharpe_std is not None else float(np.sqrt(1.0 / (n - 1)))
    n_trials = max(int(n_trials), 1)
    if n_trials == 1:
        sr0 = 0.0
    else:
        sr0 = sd * ((1.0 - _EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n_trials)
                    + _EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * np.e)))
    return {
        "dsr": probabilistic_sharpe_ratio(sr, sr0, n, sk, ku),
        "sharpe_per_period": sr,
        "benchmark_sharpe_per_period": float(sr0),
        "skew": sk,
        "kurtosis": ku,
        "n_trials": n_trials,
        "n_obs": int(n),
    }
