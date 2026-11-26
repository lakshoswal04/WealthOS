"""wealthos_core — the shared financial analytics library.

This package is the single implementation of every financial formula in
WealthOS. Both the FastAPI service layer and the offline ML training
pipelines import from here, so a metric such as Sharpe is computed one way at
training time and the identical way at serving time. Nothing in this package
imports a database, a web framework or a model artifact; it is pure
computation over pandas objects and is therefore directly unit-testable.
"""

from __future__ import annotations

from .constants import (
    ASSET_CLASS_LIQUIDITY,
    ASSET_CLASSES,
    BENCHMARK_NAME,
    BENCHMARK_SYMBOL,
    CASH_ANNUAL_RETURN,
    DEFAULT_RISK_FREE_RATE,
    MIN_OBSERVATIONS_FOR_RISK,
    MIN_SYMBOL_COVERAGE,
    MONTHS_PER_YEAR,
    PERIODS_PER_YEAR,
    RELIABLE_OBSERVATIONS_FOR_RISK,
    TRADING_DAYS_PER_YEAR,
)
from .health import (
    COMPONENT_WEIGHTS,
    HealthInputs,
    HealthScore,
    compute_health_score,
    sensitivity_analysis,
)
from .health_v2 import COMPONENT_WEIGHTS_V2, compute_health_score_v2
from .jsonsafe import json_safe, round_or_none
from .concentration import (
    concentration_by_group,
    concentration_report,
    effective_number_of_holdings,
    herfindahl_index,
    normalize_weights,
    normalized_herfindahl_index,
    top_k_weight,
)
from .metrics import (
    calmar_ratio,
    performance_summary,
    sharpe_ratio,
    sortino_ratio,
    treynor_ratio,
)
from .portfolio import (
    allocation_by,
    money_weighted_return,
    portfolio_returns_from_weights,
    portfolio_value_series,
    portfolio_weights,
    position_value_frame,
    position_values,
    time_weighted_returns,
)
from .returns import (
    annualized_return,
    annualized_volatility,
    cagr,
    cumulative_return_series,
    log_returns,
    simple_returns,
    total_return,
    wealth_index,
)
from .risk import (
    alpha,
    average_pairwise_correlation,
    beta,
    conditional_value_at_risk,
    correlation_matrix,
    downside_deviation,
    drawdown_detail,
    drawdown_series,
    max_drawdown,
    value_at_risk,
)

__version__ = "0.1.0"

__all__ = [
    # constants
    "TRADING_DAYS_PER_YEAR", "MONTHS_PER_YEAR", "PERIODS_PER_YEAR",
    "DEFAULT_RISK_FREE_RATE", "CASH_ANNUAL_RETURN",
    "BENCHMARK_SYMBOL", "BENCHMARK_NAME",
    "MIN_OBSERVATIONS_FOR_RISK", "RELIABLE_OBSERVATIONS_FOR_RISK",
    "MIN_SYMBOL_COVERAGE",
    "ASSET_CLASSES", "ASSET_CLASS_LIQUIDITY",
    # json safety
    "json_safe", "round_or_none",
    # health score
    "HealthInputs", "HealthScore", "compute_health_score",
    "compute_health_score_v2", "sensitivity_analysis",
    "COMPONENT_WEIGHTS", "COMPONENT_WEIGHTS_V2",
    # returns
    "simple_returns", "log_returns", "cumulative_return_series", "total_return",
    "annualized_return", "annualized_volatility", "cagr", "wealth_index",
    # risk
    "drawdown_series", "max_drawdown", "drawdown_detail", "downside_deviation",
    "value_at_risk", "conditional_value_at_risk", "beta", "alpha",
    "correlation_matrix", "average_pairwise_correlation",
    # ratios
    "sharpe_ratio", "sortino_ratio", "calmar_ratio", "treynor_ratio",
    "performance_summary",
    # concentration
    "normalize_weights", "herfindahl_index", "normalized_herfindahl_index",
    "effective_number_of_holdings", "top_k_weight", "concentration_by_group",
    "concentration_report",
    # portfolio
    "position_values", "portfolio_weights", "position_value_frame",
    "portfolio_value_series", "time_weighted_returns", "money_weighted_return",
    "allocation_by", "portfolio_returns_from_weights",
]
