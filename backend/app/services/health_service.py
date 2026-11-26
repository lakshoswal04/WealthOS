"""Assembles the Portfolio Health Score from the analytics layer."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from wealthos_core.health import HealthInputs, compute_health_score, sensitivity_analysis
from app.models import Transaction, TransactionType, User
from app.services import goal_service, portfolio_service, risk_service

BEHAVIOUR_WINDOW_DAYS = 365


def _behaviour_metrics(db: Session, user: User, portfolio_value: float) -> dict:
    """Turnover, contribution consistency and allocation drift.

    All three need transaction history. Where there is none they are left as
    NaN so the health score drops the component rather than scoring the user
    on an assumption.
    """
    since = date.today() - timedelta(days=BEHAVIOUR_WINDOW_DAYS)
    transactions = list(
        db.scalars(
            select(Transaction).where(
                Transaction.user_id == user.id, Transaction.date >= since
            )
        ).all()
    )

    if not transactions:
        return {
            "annual_turnover": float("nan"),
            "contribution_consistency": float("nan"),
            "allocation_drift": float("nan"),
            "n_transactions": 0,
        }

    # Turnover: the smaller of total buys and total sells, over average
    # portfolio value. Using the smaller side is the standard convention; it
    # stops a year of pure accumulation from reading as high turnover.
    buys = sum(t.value for t in transactions if t.transaction_type == TransactionType.BUY)
    sells = sum(t.value for t in transactions if t.transaction_type == TransactionType.SELL)
    turnover = (
        min(buys, sells) / portfolio_value if portfolio_value > 0 else float("nan")
    )

    contributions = [
        t for t in transactions if t.transaction_type == TransactionType.CONTRIBUTION
    ]
    if contributions:
        funded_months = {(t.date.year, t.date.month) for t in contributions}
        earliest = min(t.date for t in contributions)
        elapsed_months = max(
            1, (date.today().year - earliest.year) * 12 + date.today().month - earliest.month + 1
        )
        consistency = min(1.0, len(funded_months) / elapsed_months)
    else:
        consistency = float("nan")

    return {
        "annual_turnover": float(turnover),
        "contribution_consistency": float(consistency),
        # Needs a snapshot history to measure properly; computed in Phase 7
        # once portfolio snapshots exist.
        "allocation_drift": float("nan"),
        "n_transactions": len(transactions),
    }


def _or_nan(value: float | None) -> float:
    """None means "not measured"; any float, including 0.0, is a measurement."""
    return float("nan") if value is None else float(value)


def build_health_inputs(db: Session, user: User) -> tuple[HealthInputs, dict]:
    """Gather every measurement the score needs."""
    context: dict = {}

    concentration: dict = {}
    try:
        concentration = risk_service.concentration(db, user)
        context["concentration"] = True
    except risk_service.InsufficientHistory:
        context["concentration"] = False

    risk_summary: dict = {}
    try:
        returns, benchmark, metadata = risk_service.portfolio_return_series(db, user)
        from wealthos_core import performance_summary

        risk_summary = performance_summary(returns, benchmark)
        context["risk_window"] = [metadata["start"], metadata["end"]]
        context["risk_observations"] = metadata["observations"]
    except risk_service.InsufficientHistory as exc:
        context["risk_unavailable"] = str(exc)

    alignment = goal_service.portfolio_goal_alignment(db, user)
    summary = portfolio_service.build_summary(db, user)
    behaviour = _behaviour_metrics(db, user, summary.total_value)
    context["behaviour"] = behaviour

    asset_class_weights = {
        slice_.label: slice_.weight for slice_ in summary.allocation_by_class
    }

    inputs = HealthInputs(
        n_holdings=concentration.get("n_holdings", summary.n_holdings),
        n_sectors=concentration.get("n_sectors", summary.n_sectors),
        n_asset_classes=len(asset_class_weights),
        hhi_normalized=concentration.get("hhi_normalized", float("nan")),
        # `or float("nan")` here would be wrong: 0.0 is falsy, and a mean
        # pairwise correlation of exactly 0.0 is the *ideal* result — holdings
        # that move independently. Treating it as unmeasurable dropped
        # diversification's correlation term for the best portfolios.
        average_pairwise_correlation=_or_nan(
            concentration.get("average_pairwise_correlation")
        ),
        annualized_volatility=risk_summary.get("annualized_volatility", float("nan")),
        max_drawdown=risk_summary.get("max_drawdown", float("nan")),
        risk_tolerance=str(user.risk_tolerance or "moderate"),
        top_1_weight=concentration.get("top_1_weight", float("nan")),
        top_5_weight=concentration.get("top_5_weight", float("nan")),
        max_sector_weight=concentration.get("max_sector_weight", float("nan")),
        asset_class_weights=asset_class_weights,
        has_goals=alignment["has_goals"],
        goal_progress_ratio=alignment["goal_progress_ratio"],
        goal_funding_ratio=alignment["goal_funding_ratio"],
        annual_turnover=behaviour["annual_turnover"],
        contribution_consistency=behaviour["contribution_consistency"],
        allocation_drift=behaviour["allocation_drift"],
    )
    return inputs, context


def health_score(db: Session, user: User, include_sensitivity: bool = False) -> dict:
    """The decomposable Portfolio Health Score."""
    inputs, context = build_health_inputs(db, user)
    score = compute_health_score(inputs)

    payload = score.as_dict()
    payload["context"] = context
    payload["weights"] = {
        c["name"]: c["weight"] for c in payload["components"]
    }
    payload["methodology"] = (
        "A weighted average of six measured components, each a documented "
        "function of portfolio metrics rather than a learned model. "
        "Components whose inputs are unavailable are excluded and the "
        "remaining weights renormalised, so an unmeasurable component neither "
        "helps nor penalises the score."
    )

    if include_sensitivity:
        payload["sensitivity"] = sensitivity_analysis(inputs)

    return payload
