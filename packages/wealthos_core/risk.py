"""Risk measures: drawdown, downside risk, tail risk and benchmark sensitivity."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import DEFAULT_RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from .returns import _clean, annualized_return, wealth_index

__all__ = [
    "drawdown_series",
    "max_drawdown",
    "drawdown_detail",
    "downside_deviation",
    "value_at_risk",
    "conditional_value_at_risk",
    "beta",
    "alpha",
    "correlation_matrix",
    "average_pairwise_correlation",
]


# --------------------------------------------------------------------------
# Drawdown
# --------------------------------------------------------------------------

def drawdown_series(returns: pd.Series) -> pd.Series:
    """Fractional decline from the running peak at each point in time.

    Values are <= 0, where -0.25 means "25% below the previous high".
    """
    wealth = wealth_index(returns)
    peak = wealth.cummax()
    return wealth / peak - 1.0


def max_drawdown(returns: pd.Series) -> float:
    """Worst peak-to-trough decline over the series. Negative, or 0 if never down."""
    r = _clean(returns)
    if r.empty:
        return float("nan")
    return float(drawdown_series(r).min())


def drawdown_detail(returns: pd.Series) -> dict:
    """Max drawdown together with the dates that produced it.

    Returns peak/trough/recovery dates and the length of the drawdown, which is
    what the Risk dashboard page shows alongside the headline number.
    """
    r = _clean(returns)
    if r.empty:
        return {
            "max_drawdown": float("nan"),
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "drawdown_days": None,
            "recovered": False,
        }

    wealth = wealth_index(r)
    peak = wealth.cummax()
    dd = wealth / peak - 1.0

    trough_date = dd.idxmin()
    # The peak is the last point at or above the running max before the trough.
    pre_trough = wealth.loc[:trough_date]
    peak_date = pre_trough.idxmax()
    peak_value = float(pre_trough.max())

    # Recovery is the first date after the trough that regains the prior peak.
    after = wealth.loc[trough_date:]
    regained = after[after >= peak_value]
    recovery_date = regained.index[0] if len(regained) else None

    end = recovery_date if recovery_date is not None else dd.index[-1]
    try:
        span = (pd.Timestamp(end) - pd.Timestamp(peak_date)).days
    except (TypeError, ValueError):
        span = None

    return {
        "max_drawdown": float(dd.min()),
        "peak_date": peak_date,
        "trough_date": trough_date,
        "recovery_date": recovery_date,
        "drawdown_days": span,
        "recovered": recovery_date is not None,
    }


# --------------------------------------------------------------------------
# Downside risk
# --------------------------------------------------------------------------

def downside_deviation(
    returns: pd.Series,
    minimum_acceptable_return: float = 0.0,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised target downside deviation below a minimum acceptable return.

    This is the standard Sortino denominator::

        sqrt( mean( min(r - MAR, 0)^2 ) ) * sqrt(periods_per_year)

    The mean is taken over **all** observations, not only the negative ones.
    Averaging over negative observations alone (as some tutorials do) inflates
    the denominator for portfolios that rarely lose money and makes Sortino
    incomparable across assets, so it is deliberately not used here.

    ``minimum_acceptable_return`` is an annual rate and is de-annualised to the
    frequency of the series before comparison.
    """
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    mar_per_period = (1.0 + minimum_acceptable_return) ** (1.0 / periods_per_year) - 1.0
    shortfall = np.minimum(r - mar_per_period, 0.0)
    return float(np.sqrt((shortfall ** 2).mean()) * np.sqrt(periods_per_year))


# --------------------------------------------------------------------------
# Tail risk
# --------------------------------------------------------------------------

def value_at_risk(
    returns: pd.Series, confidence: float = 0.95, method: str = "historical"
) -> float:
    """Value at Risk as a negative return at the given confidence level.

    -0.03 at 95% means "on the worst 5% of periods, the loss was at least 3%".

    ``method`` is ``"historical"`` (empirical quantile, no distributional
    assumption) or ``"gaussian"`` (mean/sigma, which understates fat tails in
    equity returns and is offered only for comparison).
    """
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")

    if method == "historical":
        return float(np.quantile(r, 1.0 - confidence))
    if method == "gaussian":
        from scipy.stats import norm

        return float(r.mean() + norm.ppf(1.0 - confidence) * r.std(ddof=1))
    raise ValueError(f"unknown VaR method: {method!r}")


def conditional_value_at_risk(returns: pd.Series, confidence: float = 0.95) -> float:
    """Expected shortfall: the mean return among outcomes worse than the VaR."""
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")

    threshold = value_at_risk(r, confidence, method="historical")
    tail = r[r <= threshold]
    if tail.empty:
        return float(threshold)
    return float(tail.mean())


# --------------------------------------------------------------------------
# Benchmark sensitivity
# --------------------------------------------------------------------------

def _align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Inner-join two return series on their index and drop unusable rows."""
    frame = pd.concat(
        [pd.Series(a, dtype="float64"), pd.Series(b, dtype="float64")],
        axis=1,
        join="inner",
    )
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    return frame.iloc[:, 0], frame.iloc[:, 1]


def beta(asset_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Sensitivity to the benchmark: ``Cov(asset, benchmark) / Var(benchmark)``."""
    a, b = _align(asset_returns, benchmark_returns)
    if len(a) < 2:
        return float("nan")

    benchmark_variance = float(b.var(ddof=1))
    if benchmark_variance <= 0:
        return float("nan")
    return float(a.cov(b) / benchmark_variance)


def alpha(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Annualised Jensen's alpha: return earned beyond what beta alone explains.

    ``alpha = R_asset - [ R_f + beta * (R_benchmark - R_f) ]``, with all terms
    annualised.
    """
    a, b = _align(asset_returns, benchmark_returns)
    if len(a) < 2:
        return float("nan")

    asset_annual = annualized_return(a, periods_per_year)
    bench_annual = annualized_return(b, periods_per_year)
    asset_beta = beta(a, b)

    if np.isnan(asset_annual) or np.isnan(bench_annual) or np.isnan(asset_beta):
        return float("nan")

    expected = risk_free_rate + asset_beta * (bench_annual - risk_free_rate)
    return float(asset_annual - expected)


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------

def correlation_matrix(returns_frame: pd.DataFrame) -> pd.DataFrame:
    """Pairwise correlation of asset return columns.

    Correlation is computed on returns, never on price levels: two unrelated
    assets that both trend upward show near-perfect price correlation while
    their returns may be uncorrelated.
    """
    frame = pd.DataFrame(returns_frame).replace([np.inf, -np.inf], np.nan)
    return frame.corr(min_periods=2)


def average_pairwise_correlation(returns_frame: pd.DataFrame) -> float:
    """Mean of the off-diagonal correlations — a single diversification signal.

    Near 1 means the holdings move together and the portfolio is less
    diversified than its holding count suggests.
    """
    corr = correlation_matrix(returns_frame)
    if corr.shape[0] < 2:
        return float("nan")

    mask = ~np.eye(corr.shape[0], dtype=bool)
    values = corr.to_numpy()[mask]
    values = values[~np.isnan(values)]
    if values.size == 0:
        return float("nan")
    return float(values.mean())
