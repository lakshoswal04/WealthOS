"""Goal tracking and projection."""

from __future__ import annotations

from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from wealthos_core import DEFAULT_RISK_FREE_RATE, annualized_return, annualized_volatility
from wealthos_core.goals import (
    GoalProjection, monte_carlo_paths, months_between, project_goal, projection_path,
)
from app.models import Goal, GoalStatus, User
from app.services import portfolio_service, risk_service

# Used when a portfolio is too new to estimate a return from. A long-run
# balanced-portfolio assumption, stated rather than hidden.
FALLBACK_EXPECTED_RETURN = 0.10
FALLBACK_VOLATILITY = 0.12

# Caps on the return estimate taken from a user's own history. A portfolio
# that happened to return 40% over a short window must not be projected
# forward at 40% for twenty years.
RETURN_ESTIMATE_BOUNDS = (0.02, 0.18)


def expected_return_for_user(db: Session, user: User) -> tuple[float, float, dict]:
    """Estimate the portfolio's forward return and volatility.

    Derived from the user's own holdings where there is enough history,
    otherwise from a stated fallback. The estimate is bounded, because
    extrapolating an unusual historical run over a multi-decade horizon
    produces projections that are arithmetically correct and practically
    absurd.
    """
    try:
        returns, _, metadata = risk_service.portfolio_return_series(db, user)
    except risk_service.InsufficientHistory:
        return (
            FALLBACK_EXPECTED_RETURN,
            FALLBACK_VOLATILITY,
            {
                "source": "default assumption",
                "reason": "not enough portfolio history to estimate a return",
                "expected_annual_return": FALLBACK_EXPECTED_RETURN,
                "return_volatility": FALLBACK_VOLATILITY,
            },
        )

    raw_return = annualized_return(returns)
    volatility = annualized_volatility(returns)

    if np.isnan(raw_return):
        raw_return = FALLBACK_EXPECTED_RETURN
    if np.isnan(volatility):
        volatility = FALLBACK_VOLATILITY

    low, high = RETURN_ESTIMATE_BOUNDS
    bounded = float(np.clip(raw_return, low, high))

    detail = {
        "source": "this portfolio's own historical return",
        "observed_annual_return": round(float(raw_return), 4),
        "expected_annual_return": round(bounded, 4),
        "return_volatility": round(float(volatility), 4),
        "observations": metadata["observations"],
        "window": [metadata["start"], metadata["end"]],
    }
    if abs(bounded - raw_return) > 1e-9:
        detail["note"] = (
            f"The observed {raw_return:.1%} was capped to {bounded:.1%} for "
            f"projection. Returns outside {low:.0%}-{high:.0%} are not assumed "
            "to persist over a long horizon."
        )
    return bounded, float(volatility), detail


def _current_amount(db: Session, user: User, goal: Goal) -> float:
    """What counts toward this goal today.

    The MVP attributes the whole portfolio to each goal rather than
    earmarking assets, so a user with several goals sees each measured
    against the same pool. This is stated in the response so the number is
    not over-read.
    """
    if goal.current_amount and goal.current_amount > 0:
        return float(goal.current_amount)
    summary = portfolio_service.build_summary(db, user)
    return float(summary.total_value)


def list_goals(db: Session, user: User) -> list[Goal]:
    return list(
        db.scalars(
            select(Goal).where(Goal.user_id == user.id).order_by(Goal.priority, Goal.target_date)
        ).all()
    )


def forecast_goal(db: Session, user: User, goal: Goal) -> dict:
    """Project one goal forward, with scenarios and a monthly path."""
    expected, volatility, assumption_detail = expected_return_for_user(db, user)
    current = _current_amount(db, user, goal)

    monthly = float(goal.monthly_contribution or 0.0)
    if monthly <= 0 and user.monthly_savings:
        monthly = float(user.monthly_savings)

    projection: GoalProjection = project_goal(
        target_amount=float(goal.target_amount),
        current_amount=current,
        monthly_contribution=monthly,
        target_date=goal.target_date,
        expected_annual_return=expected,
        return_volatility=volatility,
        goal_id=goal.id,
        name=goal.name,
        started_on=goal.created_at.date() if goal.created_at else None,
    )

    payload = projection.as_dict()
    payload["assumptions"]["return_estimate"] = assumption_detail
    payload["assumptions"]["contribution_source"] = (
        "goal's own monthly contribution"
        if goal.monthly_contribution
        else "the profile's monthly savings, as the goal sets none"
    )
    payload["assumptions"]["current_amount_source"] = (
        "the goal's recorded amount"
        if goal.current_amount and goal.current_amount > 0
        else (
            "total portfolio value; the MVP does not earmark specific assets to "
            "a goal, so every goal is measured against the whole portfolio"
        )
    )

    path = projection_path(current, monthly, expected, projection.months_remaining)
    payload["path"] = {
        "months": list(range(len(path))),
        "projected_value": [round(v, 2) for v in path],
        "target": float(goal.target_amount),
    }
    payload["status"] = goal.status
    payload["goal_type"] = goal.goal_type
    return payload


def portfolio_goal_alignment(db: Session, user: User) -> dict:
    """Aggregate goal position, feeding the Health Score's goal component."""
    goals = [g for g in list_goals(db, user) if g.status == GoalStatus.ACTIVE]
    if not goals:
        return {"has_goals": False, "goal_progress_ratio": float("nan"),
                "goal_funding_ratio": float("nan"), "goals": []}

    forecasts = [forecast_goal(db, user, g) for g in goals]

    # Weight by target size: a large retirement goal should dominate a small
    # travel goal in the aggregate.
    total_target = sum(f["target_amount"] for f in forecasts) or 1.0
    funding = sum(
        f["funding_ratio"] * f["target_amount"] for f in forecasts
        if f["funding_ratio"] is not None and not np.isnan(f["funding_ratio"])
    ) / total_target

    progress_values = [
        f["progress_ratio"] for f in forecasts
        if f["progress_ratio"] is not None and not np.isnan(f["progress_ratio"])
    ]
    progress = float(np.mean(progress_values)) if progress_values else float("nan")

    return {
        "has_goals": True,
        "goal_progress_ratio": progress,
        "goal_funding_ratio": float(funding),
        "n_goals": len(goals),
        "n_on_track": sum(1 for f in forecasts if f["on_track"]),
        "goals": forecasts,
    }

# Bounds on what a user may dial in on the simulator. They stop the sliders
# producing projections that are arithmetically valid and financially absurd.
SIMULATION_BOUNDS = {
    "annual_return": (-0.10, 0.30),
    "annual_volatility": (0.0, 0.60),
    "monthly_contribution": (0.0, 10_000_000.0),
    "months": (1, 600),
}

SIMULATION_PATHS = 2000


def simulate_goal(
    db: Session,
    user: User,
    goal: Goal,
    monthly_contribution: float | None = None,
    annual_return: float | None = None,
    annual_volatility: float | None = None,
    months: int | None = None,
) -> dict:
    """Project a goal under user-supplied assumptions, with a range.

    Every override is optional; anything left unset falls back to the same
    values the ordinary forecast uses, so the simulator opens on the user's
    real position rather than on invented defaults.

    Returns both the deterministic path and a Monte Carlo fan. The fan is the
    point: a single line implies a precision that does not exist, and the
    probability of actually reaching the target is the number a user can act
    on.
    """
    estimated_return, estimated_volatility, estimate_detail = expected_return_for_user(db, user)
    current = _current_amount(db, user, goal)

    default_contribution = float(goal.monthly_contribution or 0.0)
    if default_contribution <= 0 and user.monthly_savings:
        default_contribution = float(user.monthly_savings)

    default_months = months_between(date.today(), goal.target_date)

    def clamp(value: float, key: str) -> float:
        low, high = SIMULATION_BOUNDS[key]
        return float(min(max(value, low), high))

    contribution = clamp(
        default_contribution if monthly_contribution is None else monthly_contribution,
        "monthly_contribution",
    )
    rate = clamp(estimated_return if annual_return is None else annual_return, "annual_return")
    volatility = clamp(
        estimated_volatility if annual_volatility is None else annual_volatility,
        "annual_volatility",
    )
    horizon = int(clamp(float(default_months if months is None else months), "months"))

    projection = project_goal(
        target_amount=float(goal.target_amount),
        current_amount=current,
        monthly_contribution=contribution,
        target_date=goal.target_date,
        expected_annual_return=rate,
        return_volatility=volatility,
        goal_id=goal.id,
        name=goal.name,
        started_on=goal.created_at.date() if goal.created_at else None,
    )

    deterministic = projection_path(current, contribution, rate, horizon)
    fan = monte_carlo_paths(
        current_amount=current,
        monthly_contribution=contribution,
        annual_return=rate,
        annual_volatility=volatility,
        months=horizon,
        target_amount=float(goal.target_amount),
        n_paths=SIMULATION_PATHS,
    )

    return {
        "goal_id": goal.id,
        "name": goal.name,
        "target_amount": float(goal.target_amount),
        "current_amount": round(current, 2),
        "months": horizon,
        "inputs": {
            "monthly_contribution": round(contribution, 2),
            "annual_return": round(rate, 4),
            "annual_volatility": round(volatility, 4),
            "months": horizon,
        },
        "defaults": {
            "monthly_contribution": round(default_contribution, 2),
            "annual_return": round(estimated_return, 4),
            "annual_volatility": round(estimated_volatility, 4),
            "months": default_months,
        },
        "bounds": {k: list(v) for k, v in SIMULATION_BOUNDS.items()},
        "deterministic": {
            "months": list(range(len(deterministic))),
            "projected_value": [round(v, 2) for v in deterministic],
            "final_value": round(deterministic[-1], 2) if deterministic else 0.0,
        },
        "monte_carlo": fan,
        "success_probability": fan["success_probability"],
        "required_monthly_contribution": projection.required_monthly_contribution,
        "funding_ratio": projection.funding_ratio,
        "on_track": projection.on_track,
        "return_estimate": estimate_detail,
    }
