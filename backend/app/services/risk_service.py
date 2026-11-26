"""Portfolio risk, performance and concentration analysis.

Every number here comes from ``wealthos_core``. The service's job is to turn
a user's holdings into the return series those functions expect, and to
attach the assumptions behind each figure so the UI and the Copilot can
state them.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from wealthos_core import (
    BENCHMARK_NAME,
    BENCHMARK_SYMBOL,
    DEFAULT_RISK_FREE_RATE,
    MIN_OBSERVATIONS_FOR_RISK,
    MIN_SYMBOL_COVERAGE,
    RELIABLE_OBSERVATIONS_FOR_RISK,
    TRADING_DAYS_PER_YEAR,
    annualized_return,
    annualized_volatility,
    average_pairwise_correlation,
    concentration_report,
    correlation_matrix,
    cumulative_return_series,
    drawdown_detail,
    drawdown_series,
    performance_summary,
    portfolio_returns_from_weights,
)
from app.models import User
from app.services import portfolio_service
from app.services.market_service import market_cache

# BENCHMARK_SYMBOL, MIN_OBSERVATIONS_FOR_RISK, RELIABLE_OBSERVATIONS_FOR_RISK
# and MIN_SYMBOL_COVERAGE are imported from wealthos_core above rather than
# defined here. This module used to redefine the first two, and both copies
# disagreed with the shared one: the symbol differed by a space, and the
# comment claimed a one-year minimum above a constant of 60 days.

LOOKBACK_WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252, "3y": 756, "5y": 1260}


class InsufficientHistory(Exception):
    """Raised when a portfolio has too little price history to analyse."""


def portfolio_return_series(
    db: Session, user: User, start: date | None = None, end: date | None = None
) -> tuple[pd.Series, pd.Series, dict]:
    """Build the portfolio and benchmark return series for the current holdings.

    Returns are computed on today's weights held fixed across history. This
    answers "how risky is the portfolio I hold now", which is what the Risk
    page asks. It is deliberately not a transaction-accurate replay of what
    the investor actually earned, and the metadata says so.
    """
    weights = portfolio_service.portfolio_weights(db, user)
    if weights.empty:
        raise InsufficientHistory("Portfolio has no priced holdings")

    symbols = list(weights.index)
    asset_returns = market_cache.returns(db, symbols, start, end)
    if asset_returns.empty:
        raise InsufficientHistory("No price history for these holdings")

    # Restrict to the window every holding covers, so a recently listed asset
    # does not silently drop out of part of the series.
    usable = asset_returns.dropna(how="any")
    if len(usable) < MIN_OBSERVATIONS_FOR_RISK:
        # Fall back to the assets that do have history, and report the gap.
        coverage = asset_returns.notna().mean()
        keep = coverage[coverage > MIN_SYMBOL_COVERAGE].index.tolist()
        if not keep:
            raise InsufficientHistory(
                f"Only {len(usable)} overlapping observations across these holdings"
            )
        usable = asset_returns[keep].dropna(how="any")
        weights = weights[keep]

    if len(usable) < MIN_OBSERVATIONS_FOR_RISK:
        raise InsufficientHistory(
            f"Only {len(usable)} overlapping observations; at least "
            f"{MIN_OBSERVATIONS_FOR_RISK} are needed for a reliable risk figure"
        )

    portfolio_returns = portfolio_returns_from_weights(weights, usable)

    benchmark = market_cache.returns(db, [BENCHMARK_SYMBOL], start, end)
    benchmark_returns = (
        benchmark[BENCHMARK_SYMBOL].reindex(portfolio_returns.index)
        if BENCHMARK_SYMBOL in benchmark.columns
        else pd.Series(dtype="float64")
    )

    metadata = {
        "method": "current weights held constant over history",
        "symbols_used": list(usable.columns),
        "symbols_excluded": [s for s in symbols if s not in usable.columns],
        "observations": int(len(portfolio_returns)),
        "start": str(portfolio_returns.index.min().date()) if len(portfolio_returns) else None,
        "end": str(portfolio_returns.index.max().date()) if len(portfolio_returns) else None,
        "risk_free_rate": DEFAULT_RISK_FREE_RATE,
        "benchmark": BENCHMARK_SYMBOL,
        "benchmark_name": BENCHMARK_NAME,
        # Above the floor but below a full year, the figures are real but
        # noisy. Say so here rather than letting the reader assume otherwise.
        "window_reliability": (
            "provisional"
            if len(portfolio_returns) < RELIABLE_OBSERVATIONS_FOR_RISK
            else "full"
        ),
        "minimum_observations": MIN_OBSERVATIONS_FOR_RISK,
        "rebalancing": "daily (the weighted series assumes continuous rebalancing)",
    }
    return portfolio_returns, benchmark_returns, metadata


def analytics(db: Session, user: User, lookback: str | None = None) -> dict:
    """Return and performance figures across standard windows."""
    start = None
    if lookback and lookback in LOOKBACK_WINDOWS:
        start = date.today() - timedelta(days=int(LOOKBACK_WINDOWS[lookback] * 365 / 252) + 5)

    returns, benchmark, metadata = portfolio_return_series(db, user, start=start)
    summary = performance_summary(returns, benchmark)

    # Trailing performance over each window the UI offers.
    windows: dict[str, dict] = {}
    for label, days in LOOKBACK_WINDOWS.items():
        if len(returns) < days:
            continue
        window = returns.iloc[-days:]
        bench_window = benchmark.iloc[-days:] if len(benchmark) >= days else None
        entry = {
            "total_return": float((1 + window).prod() - 1),
            "annualized_return": annualized_return(window),
            "annualized_volatility": annualized_volatility(window),
        }
        if bench_window is not None and bench_window.notna().any():
            entry["benchmark_total_return"] = float((1 + bench_window.fillna(0)).prod() - 1)
            entry["excess_return"] = entry["total_return"] - entry["benchmark_total_return"]
        windows[label] = entry

    cumulative = cumulative_return_series(returns)
    benchmark_cumulative = (
        cumulative_return_series(benchmark.fillna(0)) if benchmark.notna().any() else None
    )

    return {
        "summary": summary,
        "windows": windows,
        "series": {
            "dates": [d.strftime("%Y-%m-%d") for d in cumulative.index],
            "cumulative_return": [float(v) for v in cumulative.to_numpy()],
            "benchmark_cumulative_return": (
                [float(v) for v in benchmark_cumulative.to_numpy()]
                if benchmark_cumulative is not None else None
            ),
        },
        "assumptions": metadata,
    }


def risk(db: Session, user: User) -> dict:
    """Volatility, drawdown, tail risk, benchmark sensitivity and correlation."""
    returns, benchmark, metadata = portfolio_return_series(db, user)
    summary = performance_summary(returns, benchmark)

    drawdowns = drawdown_series(returns)
    detail = drawdown_detail(returns)

    weights = portfolio_service.portfolio_weights(db, user)
    symbols = list(weights.index)
    asset_returns = market_cache.returns(db, symbols).dropna(how="any")

    correlation: dict = {}
    if asset_returns.shape[1] >= 2:
        matrix = correlation_matrix(asset_returns)
        correlation = {
            "symbols": list(matrix.columns),
            "matrix": [[None if pd.isna(v) else round(float(v), 4) for v in row]
                       for row in matrix.to_numpy()],
            "average_pairwise": average_pairwise_correlation(asset_returns),
        }

    # Risk-return scatter: each holding's own annualised profile.
    per_asset = []
    for symbol in asset_returns.columns:
        series = asset_returns[symbol]
        per_asset.append({
            "symbol": symbol,
            "annualized_return": annualized_return(series),
            "annualized_volatility": annualized_volatility(series),
            "weight": float(weights.get(symbol, 0.0)),
        })

    return {
        "summary": summary,
        "drawdown": {
            "max_drawdown": detail["max_drawdown"],
            "current_drawdown": float(drawdowns.iloc[-1]) if len(drawdowns) else None,
            "peak_date": str(detail["peak_date"].date()) if detail["peak_date"] is not None else None,
            "trough_date": str(detail["trough_date"].date()) if detail["trough_date"] is not None else None,
            "recovery_date": str(detail["recovery_date"].date()) if detail["recovery_date"] is not None else None,
            "recovered": detail["recovered"],
            "drawdown_days": detail["drawdown_days"],
            "series": {
                "dates": [d.strftime("%Y-%m-%d") for d in drawdowns.index],
                "drawdown": [float(v) for v in drawdowns.to_numpy()],
            },
        },
        "correlation": correlation,
        "risk_return_scatter": per_asset,
        "assumptions": metadata,
    }


def concentration(db: Session, user: User) -> dict:
    """Concentration at the asset, sector and asset-class level."""
    priced = portfolio_service.value_holdings(db, portfolio_service.get_holdings(db, user))
    values = {r.symbol: r.market_value for r in priced if r.market_value}
    if not values:
        raise InsufficientHistory("Portfolio has no priced holdings")

    sectors = {r.symbol: (r.sector or "Unknown") for r in priced}
    classes = {r.symbol: str(r.asset_class) for r in priced}

    report = concentration_report(values, sectors, classes)

    # The average correlation of the holdings adds the dimension HHI misses:
    # a portfolio can be evenly weighted and still undiversified if its
    # holdings all move together.
    asset_returns = market_cache.returns(db, list(values)).dropna(how="any")
    if asset_returns.shape[1] >= 2:
        report["average_pairwise_correlation"] = average_pairwise_correlation(asset_returns)
    else:
        report["average_pairwise_correlation"] = None

    report["interpretation"] = _interpret_concentration(report)
    return report


def _interpret_concentration(report: dict) -> list[str]:
    """Plain-language observations, stated as measurements rather than advice."""
    notes: list[str] = []

    effective = report.get("effective_holdings")
    count = report.get("n_holdings", 0)
    if effective and count and effective < count * 0.6:
        notes.append(
            f"The portfolio holds {count} positions but behaves like roughly "
            f"{effective:.1f} equally weighted ones, because the weights are uneven."
        )

    top = report.get("top_1_weight")
    if top and top > 0.25:
        notes.append(
            f"The largest holding, {report.get('largest_holding')}, is "
            f"{top:.1%} of the portfolio."
        )

    max_sector = report.get("max_sector_weight")
    if max_sector and max_sector > 0.40:
        notes.append(
            f"{report.get('largest_sector')} accounts for {max_sector:.1%} of "
            "the portfolio, so sector-specific events affect a large share of it."
        )

    correlation = report.get("average_pairwise_correlation")
    if correlation is not None and correlation > 0.6:
        notes.append(
            f"The holdings have an average pairwise return correlation of "
            f"{correlation:.2f}, so they tend to move together and the holding "
            "count overstates how diversified the portfolio is."
        )

    classes = report.get("asset_class_weights", {})
    if len(classes) == 1:
        notes.append(
            f"Everything is in one asset class ({next(iter(classes))})."
        )

    if not notes:
        notes.append("No single holding, sector or asset class dominates the portfolio.")
    return notes
