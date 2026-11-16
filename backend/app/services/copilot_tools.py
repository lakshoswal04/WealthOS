"""The read-only tools the Wealth Copilot may call.

Every tool returns structured JSON computed by the service layer. The model
never calculates a financial figure: it selects which measurements to fetch
and then narrates them. That separation is what makes the Copilot's output
checkable, and it is what the groundedness validator enforces.

All tools are read-only. None can modify a portfolio, place a trade, or
change a goal.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models import User
from app.services import (
    goal_service, health_service, insight_service, portfolio_service, risk_service,
)
from app.services.risk_service import InsufficientHistory


def _guarded(call: Callable[[], Any]) -> dict:
    """Run a service call, turning an expected failure into a stated reason.

    A tool that raises would leave the model with nothing to say and invite
    it to invent an answer. A tool that returns an explicit "unavailable"
    gives it something true to report instead.
    """
    try:
        return call()
    except InsufficientHistory as exc:
        return {"available": False, "reason": str(exc)}
    except Exception as exc:  # a broken tool must not become a fabricated answer
        return {
            "available": False,
            "reason": f"This measurement could not be computed ({type(exc).__name__}).",
        }


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------

def get_portfolio_summary(db: Session, user: User, **_: Any) -> dict:
    summary = portfolio_service.build_summary(db, user)
    return {
        "total_value": round(summary.total_value, 2),
        "total_cost": round(summary.total_cost, 2),
        "unrealized_gain": round(summary.unrealized_gain, 2),
        "unrealized_gain_pct": round(summary.unrealized_gain_pct * 100, 2),
        "n_holdings": summary.n_holdings,
        "n_sectors": summary.n_sectors,
        "as_of": str(summary.as_of) if summary.as_of else None,
        "allocation_by_class": [
            {"label": a.label, "value": round(a.value, 2), "weight_pct": round(a.weight * 100, 2)}
            for a in summary.allocation_by_class
        ],
        "top_holdings": [
            {
                "symbol": h.symbol,
                "market_value": round(h.market_value or 0, 2),
                "weight_pct": round((h.weight or 0) * 100, 2),
                "unrealized_gain_pct": round((h.unrealized_gain_pct or 0) * 100, 2),
            }
            for h in summary.top_holdings[:5]
        ],
    }


def get_risk_metrics(db: Session, user: User, **_: Any) -> dict:
    data = risk_service.risk(db, user)
    summary = data["summary"]
    return {
        "annualized_return_pct": round(summary["annualized_return"] * 100, 2),
        "annualized_volatility_pct": round(summary["annualized_volatility"] * 100, 2),
        "sharpe_ratio": round(summary["sharpe_ratio"], 3),
        "sortino_ratio": round(summary["sortino_ratio"], 3),
        "max_drawdown_pct": round(summary["max_drawdown"] * 100, 2),
        "current_drawdown_pct": round((data["drawdown"]["current_drawdown"] or 0) * 100, 2),
        "beta": round(summary["beta"], 3),
        "value_at_risk_95_pct": round(summary["var_95"] * 100, 2),
        "drawdown_peak_date": data["drawdown"]["peak_date"],
        "drawdown_trough_date": data["drawdown"]["trough_date"],
        "recovered": data["drawdown"]["recovered"],
        "average_pairwise_correlation": (
            round(data["correlation"]["average_pairwise"], 3)
            if data.get("correlation") else None
        ),
        "assumptions": data["assumptions"],
    }


def get_concentration(db: Session, user: User, **_: Any) -> dict:
    data = risk_service.concentration(db, user)
    return {
        "n_holdings": data["n_holdings"],
        "effective_holdings": round(data["effective_holdings"], 2),
        "hhi": round(data["hhi"], 4),
        "top_1_weight_pct": round(data["top_1_weight"] * 100, 2),
        "top_5_weight_pct": round(data["top_5_weight"] * 100, 2),
        "largest_holding": data["largest_holding"],
        "largest_sector": data.get("largest_sector"),
        "max_sector_weight_pct": round((data.get("max_sector_weight") or 0) * 100, 2),
        "sector_weights_pct": {
            k: round(v * 100, 2) for k, v in (data.get("sector_weights") or {}).items()
        },
        "average_pairwise_correlation": data.get("average_pairwise_correlation"),
        "observations": data["interpretation"],
    }


def get_health_score(db: Session, user: User, **_: Any) -> dict:
    data = health_service.health_score(db, user)
    return {
        "total": data["total"],
        "grade": data["grade"],
        "summary": data["summary"],
        "components": [
            {
                "name": c["name"], "score": c["score"],
                "weight": c["weight"], "reason": c["reason"],
            }
            for c in data["components"]
        ],
        "components_not_measured": data["missing_inputs"],
    }


def get_goal_status(db: Session, user: User, **_: Any) -> dict:
    alignment = goal_service.portfolio_goal_alignment(db, user)
    if not alignment["has_goals"]:
        return {"has_goals": False, "reason": "No goals have been set."}
    return {
        "has_goals": True,
        "n_goals": alignment["n_goals"],
        "n_on_track": alignment["n_on_track"],
        "goals": [
            {
                "name": g["name"],
                "target_amount": g["target_amount"],
                "projected_value": g["projected_value"],
                "funding_pct": round(g["funding_ratio"] * 100, 1),
                "shortfall": g["shortfall"],
                "on_track": g["on_track"],
                "months_remaining": g["months_remaining"],
                "monthly_contribution": g["monthly_contribution"],
                "required_monthly_contribution": g["required_monthly_contribution"],
                "target_date": g["target_date"],
            }
            for g in alignment["goals"]
        ],
    }


def get_forecast(db: Session, user: User, horizon_months: int = 12, **_: Any) -> dict:
    return insight_service.wealth_forecast(db, user, int(horizon_months))


def get_investor_profile(db: Session, user: User, **_: Any) -> dict:
    return insight_service.investor_profile(db, user)


def get_anomalies(db: Session, user: User, **_: Any) -> dict:
    return insight_service.detect_anomalies(db, user, limit=12)


# --------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------
# strict=True with additionalProperties=False guarantees the arguments the
# model sends validate exactly, so a dispatch never receives a surprise key.

def _schema(name: str, description: str, properties: dict | None = None,
            required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "get_portfolio_summary",
        "Total portfolio value, cost, unrealised gain, allocation by asset class "
        "and the largest holdings. Use for 'what do I own' and 'how much is it worth'.",
    ),
    _schema(
        "get_risk_metrics",
        "Volatility, Sharpe and Sortino ratios, maximum and current drawdown, beta "
        "and Value at Risk, with the assumptions behind them. Use for 'how risky is "
        "my portfolio' and any question about returns relative to risk.",
    ),
    _schema(
        "get_concentration",
        "Concentration by holding, sector and asset class: HHI, effective number of "
        "holdings, largest positions and average pairwise correlation. Use for "
        "'am I diversified' and 'what am I over-exposed to'.",
    ),
    _schema(
        "get_health_score",
        "The Portfolio Health Score out of 100 with all six component scores, their "
        "weights and the reason for each. Use for 'how healthy is my portfolio' and "
        "'why is my score what it is'.",
    ),
    _schema(
        "get_goal_status",
        "Every financial goal with its target, projected value, funding percentage, "
        "shortfall and required monthly contribution. Use for 'am I on track'.",
    ),
    _schema(
        "get_forecast",
        "Projected portfolio value at a horizon, from the trained forecasting models, "
        "with the range across models. Use for 'what will my portfolio be worth'.",
        properties={
            "horizon_months": {
                "type": "integer",
                "enum": [1, 3, 6, 12],
                "description": "Months ahead to project. Defaults to 12.",
            }
        },
        required=["horizon_months"],
    ),
    _schema(
        "get_investor_profile",
        "The behavioural cluster this portfolio resembles and how it differs from "
        "that cluster's average. Use for 'what kind of investor am I'.",
    ),
    _schema(
        "get_anomalies",
        "Months whose portfolio behaviour the anomaly model could not reconstruct, "
        "with the features that drove each flag. Use for 'has anything unusual "
        "happened'.",
    ),
]

TOOL_FUNCTIONS: dict[str, Callable] = {
    "get_portfolio_summary": get_portfolio_summary,
    "get_risk_metrics": get_risk_metrics,
    "get_concentration": get_concentration,
    "get_health_score": get_health_score,
    "get_goal_status": get_goal_status,
    "get_forecast": get_forecast,
    "get_investor_profile": get_investor_profile,
    "get_anomalies": get_anomalies,
}


def run_tool(name: str, db: Session, user: User, arguments: dict) -> dict:
    """Dispatch one tool call."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"error": f"Unknown tool: {name}"}
    return _guarded(lambda: function(db, user, **(arguments or {})))
