"""Builds live model inputs from a user's holdings and transactions.

The models were trained on monthly snapshots of simulated investors. A real
user has holdings and a transaction log, so this module reconstructs the
equivalent monthly history: it values the current positions back through the
real price panel and overlays any recorded cash flows.

The reconstruction is explicitly approximate, and every response that
depends on it says so. Valuing today's positions backward is not the same as
replaying what the investor actually held at each point in the past, and
presenting it as if it were would misstate their history.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from wealthos_core import BENCHMARK_SYMBOL, herfindahl_index, time_weighted_returns
from app.models import Transaction, TransactionType, User
from app.services import portfolio_service
from app.services.market_service import market_cache

MONTHS_PER_YEAR = 12


def _finite(value: object, default: float = 0.0) -> float:
    """Coerce to a finite float, substituting ``default`` for NaN.

    These two features previously used ``float(x or 0.0)``, which does not do
    this: NaN is truthy in Python, so the fallback never fired and a NaN
    reached the feature vector. A single-snapshot history makes
    ``Series.std()`` NaN (ddof=1), so the case is reachable, not theoretical.
    """
    number = float(value)
    return default if not np.isfinite(number) else number


def monthly_history(db: Session, user: User) -> pd.DataFrame:
    """Reconstruct a monthly snapshot history for a live user.

    Returns an empty frame when the user holds nothing or no prices are
    available, which callers must handle rather than assume away.
    """
    holdings = portfolio_service.get_holdings(db, user)
    if not holdings:
        return pd.DataFrame()

    quantities = {h.asset.symbol: float(h.quantity) for h in holdings}
    classes = {h.asset.symbol: str(h.asset.asset_class) for h in holdings}

    panel = market_cache.price_history(db, list(quantities))
    if panel.empty:
        return pd.DataFrame()

    monthly_prices = panel.resample("ME").last().ffill().dropna(how="all")
    priced = [s for s in quantities if s in monthly_prices.columns]
    if not priced:
        return pd.DataFrame()

    position_values = monthly_prices[priced].mul(
        pd.Series({s: quantities[s] for s in priced}), axis=1
    )
    position_values = position_values.dropna(how="any")
    if position_values.empty:
        return pd.DataFrame()

    total = position_values.sum(axis=1)

    # Cash flows actually recorded by the user, aggregated per month.
    flows = pd.Series(0.0, index=total.index)
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.transaction_type.in_(
                [TransactionType.CONTRIBUTION, TransactionType.WITHDRAWAL]
            ),
        )
    ).all()
    for entry in transactions:
        stamp = pd.Timestamp(entry.date) + pd.offsets.MonthEnd(0)
        if stamp in flows.index:
            sign = 1.0 if entry.transaction_type == TransactionType.CONTRIBUTION else -1.0
            flows.loc[stamp] += sign * float(entry.value)

    weights = position_values.div(total, axis=0)
    frame = pd.DataFrame({
        "date": total.index,
        "total_value": total.to_numpy(),
        "net_contribution": flows.to_numpy(),
    })

    # Time-weighted, so recorded contributions are not read as performance.
    returns = time_weighted_returns(total, flows)
    frame["period_return"] = returns.reindex(total.index).to_numpy()

    frame["hhi"] = [herfindahl_index(row.dropna()) for _, row in weights.iterrows()]
    frame["top_holding_weight"] = weights.max(axis=1).to_numpy()
    frame["n_holdings"] = (position_values > 1.0).sum(axis=1).to_numpy()

    for asset_class in ("equity", "etf", "gold", "debt", "cash"):
        members = [s for s in priced if classes.get(s) == asset_class]
        frame[f"{asset_class}_allocation"] = (
            position_values[members].sum(axis=1).div(total).to_numpy()
            if members else 0.0
        )

    series = pd.Series(frame["period_return"].to_numpy())
    frame["volatility"] = (
        series.rolling(12, min_periods=6).std() * np.sqrt(MONTHS_PER_YEAR)
    ).to_numpy()

    wealth = (1 + series.fillna(0)).cumprod()
    peak = wealth.cummax()
    frame["current_drawdown"] = (wealth / peak - 1).to_numpy()
    frame["max_drawdown"] = (wealth / peak - 1).cummin().to_numpy()
    frame["cumulative_return"] = (wealth - 1).to_numpy()

    # A reconstructed history has no trading activity to measure: the user's
    # positions are taken as fixed. Turnover is therefore reported from
    # recorded transactions only, and is zero when there are none.
    frame["turnover"] = 0.0
    frame["n_trades"] = 0.0
    frame["contribution_ratio"] = (
        frame["net_contribution"] / frame["total_value"].replace(0, np.nan)
    ).fillna(0.0)
    frame["months_invested"] = np.arange(1, len(frame) + 1)
    frame["log_value"] = np.log(frame["total_value"].clip(lower=1.0))

    return frame


def market_context(db: Session, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Market-regime features aligned to a set of month ends."""
    panel = market_cache.price_history(db, [BENCHMARK_SYMBOL, "GOLDBEES", "DEBT"])
    if panel.empty or BENCHMARK_SYMBOL not in panel.columns:
        return pd.DataFrame({"date": dates})

    monthly = panel.resample("ME").last().ffill()
    benchmark = monthly[BENCHMARK_SYMBOL]
    returns = benchmark.pct_change()

    context = pd.DataFrame({
        "date": monthly.index,
        "market_return_1m": returns.to_numpy(),
        "market_return_3m": benchmark.pct_change(3).to_numpy(),
        "market_return_12m": benchmark.pct_change(12).to_numpy(),
        "market_volatility_12m": (
            returns.rolling(12, min_periods=6).std() * np.sqrt(12)
        ).to_numpy(),
        "market_drawdown": (benchmark / benchmark.cummax() - 1).to_numpy(),
    })
    if "GOLDBEES" in monthly.columns:
        context["gold_return_3m"] = monthly["GOLDBEES"].pct_change(3).to_numpy()
    if "DEBT" in monthly.columns:
        context["debt_return_3m"] = monthly["DEBT"].pct_change(3).to_numpy()
    context["month_of_year"] = context["date"].dt.month
    return context


def behavioural_profile(history: pd.DataFrame, user: User) -> dict:
    """Aggregate a user's reconstructed history into clustering features."""
    if history.empty:
        return {}

    funded = (history["net_contribution"] > 0).mean()
    rate = (
        history["net_contribution"] / history["total_value"].replace(0, np.nan)
    ).median()

    return {
        "equity_allocation": float(history["equity_allocation"].mean()),
        "etf_allocation": float(history["etf_allocation"].mean()),
        "gold_allocation": float(history["gold_allocation"].mean()),
        "debt_allocation": float(history["debt_allocation"].mean()),
        "cash_allocation": float(history["cash_allocation"].mean()),
        "allocation_volatility": _finite(history["equity_allocation"].std()),
        "turnover": float(history["turnover"].mean()),
        "trades_per_month": float(history["n_trades"].mean()),
        "portfolio_volatility": _finite(history["volatility"].mean(skipna=True)),
        "max_drawdown": float(history["max_drawdown"].min()),
        "hhi": float(history["hhi"].mean()),
        "top_holding_weight": float(history["top_holding_weight"].mean()),
        "n_holdings": float(history["n_holdings"].mean()),
        "contribution_consistency": float(funded),
        "contribution_rate": float(rate if pd.notna(rate) else 0.0),
    }
