"""The Portfolio Health Score.

This is an analytics engine, not a model. Every component is a documented
function of measurable inputs, so a score can always be explained, audited
and reproduced. An opaque learned score would be easier to build and
impossible to defend to the person whose portfolio it judges.

The score runs 0-100 across six weighted components:

    Diversification  20   spread across holdings and sectors, and whether
                          those holdings actually move independently
    Risk             20   volatility and drawdown measured against the band
                          implied by the investor's own stated tolerance
    Concentration    15   how much sits in the largest positions
    Liquidity        10   how quickly the portfolio could be realised
    Goal alignment   20   progress against what the stated goals require
    Behaviour        15   turnover, contribution consistency, allocation drift

Weights reflect a stated rationale rather than tuning. Diversification and
risk carry the most weight because they drive the outcomes a retail investor
is least equipped to see for themselves. Goal alignment matches them because
a portfolio that is excellent in isolation can still be failing its purpose.
Liquidity is smallest because the MVP universe is uniformly liquid, so the
component has little room to discriminate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .constants import ASSET_CLASS_LIQUIDITY
from .jsonsafe import round_or_none

__all__ = [
    "HealthInputs",
    "ComponentScore",
    "HealthScore",
    "compute_health_score",
    "sensitivity_analysis",
    "RISK_TOLERANCE_VOLATILITY_BANDS",
    "COMPONENT_WEIGHTS",
]


COMPONENT_WEIGHTS = {
    "diversification": 20.0,
    "risk": 20.0,
    "concentration": 15.0,
    "liquidity": 10.0,
    "goal_alignment": 20.0,
    "behaviour": 15.0,
}

# Annualised volatility ranges considered appropriate for each stated risk
# tolerance. A portfolio inside its band scores full marks; outside it loses
# points in the direction of the mismatch.
RISK_TOLERANCE_VOLATILITY_BANDS = {
    "conservative": (0.04, 0.10),
    "moderate": (0.08, 0.17),
    "aggressive": (0.14, 0.28),
}
DEFAULT_VOLATILITY_BAND = RISK_TOLERANCE_VOLATILITY_BANDS["moderate"]

# Drawdown tolerated before the risk component starts losing points.
DRAWDOWN_TOLERANCE = {
    "conservative": 0.12,
    "moderate": 0.25,
    "aggressive": 0.40,
}


@dataclass
class HealthInputs:
    """Everything the score needs, already measured by the analytics layer."""

    # --- diversification ---
    n_holdings: int = 0
    n_sectors: int = 0
    n_asset_classes: int = 0
    hhi_normalized: float = float("nan")
    average_pairwise_correlation: float = float("nan")

    # --- risk ---
    annualized_volatility: float = float("nan")
    max_drawdown: float = float("nan")
    risk_tolerance: str = "moderate"

    # --- concentration ---
    top_1_weight: float = float("nan")
    top_5_weight: float = float("nan")
    max_sector_weight: float = float("nan")

    # --- liquidity ---
    asset_class_weights: dict[str, float] = field(default_factory=dict)

    # --- goal alignment ---
    has_goals: bool = False
    goal_progress_ratio: float = float("nan")   # actual / required-by-now
    goal_funding_ratio: float = float("nan")    # projected / target at target date

    # --- behaviour ---
    annual_turnover: float = float("nan")
    contribution_consistency: float = float("nan")  # 0-1, share of months funded
    allocation_drift: float = float("nan")          # absolute weight change per year


@dataclass
class ComponentScore:
    name: str
    score: float          # 0-100
    weight: float         # points this component contributes at full marks
    contribution: float   # score/100 * weight
    inputs: dict
    reason: str


@dataclass
class HealthScore:
    total: float
    grade: str
    components: list[ComponentScore]
    summary: str
    missing_inputs: list[str]

    def as_dict(self) -> dict:
        # round_or_none, not round: an unscorable portfolio carries NaN in
        # `total` and in every component score, and round() preserves NaN
        # rather than rejecting it. See wealthos_core.jsonsafe.
        return {
            "total": round_or_none(self.total, 1),
            "grade": self.grade,
            "summary": self.summary,
            "missing_inputs": self.missing_inputs,
            "components": [
                {
                    "name": c.name,
                    "score": round_or_none(c.score, 1),
                    "weight": c.weight,
                    "contribution": round_or_none(c.contribution, 2),
                    "inputs": c.inputs,
                    "reason": c.reason,
                }
                for c in self.components
            ],
        }


# --------------------------------------------------------------------------
# Scoring helpers
# --------------------------------------------------------------------------

def _ramp(value: float, worst: float, best: float) -> float:
    """Map a value onto 0-100, linearly between ``worst`` and ``best``.

    Works in either direction: ``worst`` may be the larger number when a
    lower value is better.
    """
    if np.isnan(value):
        return float("nan")
    if worst == best:
        return 100.0
    fraction = (value - worst) / (best - worst)
    return float(np.clip(fraction, 0.0, 1.0) * 100.0)


def _band_score(value: float, low: float, high: float,
                under_penalty: float = 0.6, over_penalty: float = 1.0) -> float:
    """Full marks inside a band, decaying outside it.

    Overshooting is penalised harder than undershooting: taking more risk
    than intended can cause a loss the investor did not sign up for, while
    taking less mostly costs return.
    """
    if np.isnan(value):
        return float("nan")
    if low <= value <= high:
        return 100.0

    width = max(high - low, 1e-9)
    if value < low:
        distance = (low - value) / width
        return float(max(0.0, 100.0 - 100.0 * distance * under_penalty))
    distance = (value - high) / width
    return float(max(0.0, 100.0 - 100.0 * distance * over_penalty))


def _mean_available(values: list[float]) -> float:
    """Average the sub-scores that could be computed, ignoring the rest."""
    present = [v for v in values if not np.isnan(v)]
    return float(np.mean(present)) if present else float("nan")


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

def _score_diversification(data: HealthInputs) -> ComponentScore:
    if not data.n_holdings:
        # No holdings is an absence of data, not a badly built portfolio.
        # Scoring it zero would grade an empty account "Poor", which tells
        # the user nothing and is not true.
        return ComponentScore(
            name="diversification",
            score=float("nan"),
            weight=COMPONENT_WEIGHTS["diversification"],
            contribution=0.0,
            inputs={"n_holdings": 0},
            reason="The portfolio holds nothing, so diversification cannot be assessed.",
        )

    # Below 8 holdings a portfolio carries substantial single-name risk; past
    # about 25 the marginal benefit of one more name is small.
    holdings_score = _ramp(float(data.n_holdings), 1.0, 20.0)
    sectors_score = _ramp(float(data.n_sectors), 1.0, 8.0)
    classes_score = _ramp(float(data.n_asset_classes), 1.0, 4.0)
    evenness_score = _ramp(data.hhi_normalized, 0.6, 0.0)
    # The part holding counts cannot see: holdings that all move together.
    correlation_score = _ramp(data.average_pairwise_correlation, 0.9, 0.2)

    score = _mean_available(
        [holdings_score, sectors_score, classes_score, evenness_score, correlation_score]
    )

    if np.isnan(score):
        reason = "Not enough holdings data to assess diversification."
    elif score >= 75:
        reason = (
            f"Spread across {data.n_holdings} holdings in {data.n_sectors} sectors "
            f"and {data.n_asset_classes} asset classes, with reasonably "
            "independent price behaviour."
        )
    elif score >= 50:
        reason = (
            f"Moderately diversified: {data.n_holdings} holdings across "
            f"{data.n_sectors} sectors, but the spread is uneven or the holdings "
            "move together more than their number suggests."
        )
    else:
        reason = (
            f"Concentrated: only {data.n_holdings} holdings across "
            f"{data.n_sectors} sectors, so individual positions drive most of "
            "the portfolio's movement."
        )

    return ComponentScore(
        name="diversification",
        score=score,
        weight=COMPONENT_WEIGHTS["diversification"],
        contribution=(0.0 if np.isnan(score) else score / 100 * COMPONENT_WEIGHTS["diversification"]),
        inputs={
            "n_holdings": data.n_holdings,
            "n_sectors": data.n_sectors,
            "n_asset_classes": data.n_asset_classes,
            "hhi_normalized": _clean(data.hhi_normalized),
            "average_pairwise_correlation": _clean(data.average_pairwise_correlation),
            "subscores": {
                "holdings": _clean(holdings_score), "sectors": _clean(sectors_score),
                "asset_classes": _clean(classes_score), "evenness": _clean(evenness_score),
                "correlation": _clean(correlation_score),
            },
        },
        reason=reason,
    )


def _score_risk(data: HealthInputs) -> ComponentScore:
    tolerance = (data.risk_tolerance or "moderate").lower()
    low, high = RISK_TOLERANCE_VOLATILITY_BANDS.get(tolerance, DEFAULT_VOLATILITY_BAND)
    tolerated_drawdown = DRAWDOWN_TOLERANCE.get(tolerance, 0.25)

    volatility_score = _band_score(data.annualized_volatility, low, high)
    drawdown_score = _ramp(abs(data.max_drawdown), tolerated_drawdown * 2, 0.0)

    score = _mean_available([volatility_score, drawdown_score])

    volatility = data.annualized_volatility
    if np.isnan(volatility):
        reason = "Not enough price history to measure portfolio risk."
    elif volatility > high:
        reason = (
            f"Volatility of {volatility:.1%} is above the {low:.0%}-{high:.0%} range "
            f"typical of a {tolerance} profile, so the portfolio carries more risk "
            "than the stated tolerance implies."
        )
    elif volatility < low:
        reason = (
            f"Volatility of {volatility:.1%} is below the {low:.0%}-{high:.0%} range "
            f"for a {tolerance} profile. The portfolio is calmer than the stated "
            "tolerance allows for, which may limit long-term growth."
        )
    else:
        reason = (
            f"Volatility of {volatility:.1%} sits within the {low:.0%}-{high:.0%} "
            f"range expected for a {tolerance} profile, with a worst drawdown of "
            f"{abs(data.max_drawdown):.1%}."
        )

    return ComponentScore(
        name="risk",
        score=score,
        weight=COMPONENT_WEIGHTS["risk"],
        contribution=(0.0 if np.isnan(score) else score / 100 * COMPONENT_WEIGHTS["risk"]),
        inputs={
            "annualized_volatility": _clean(data.annualized_volatility),
            "max_drawdown": _clean(data.max_drawdown),
            "risk_tolerance": tolerance,
            "target_volatility_band": [low, high],
            "tolerated_drawdown": tolerated_drawdown,
            "subscores": {
                "volatility": _clean(volatility_score),
                "drawdown": _clean(drawdown_score),
            },
        },
        reason=reason,
    )


def _score_concentration(data: HealthInputs) -> ComponentScore:
    top_1 = _ramp(data.top_1_weight, 0.50, 0.10)
    top_5 = _ramp(data.top_5_weight, 1.00, 0.50)
    sector = _ramp(data.max_sector_weight, 0.70, 0.25)

    score = _mean_available([top_1, top_5, sector])

    if np.isnan(score):
        reason = "Not enough holdings data to assess concentration."
    elif not np.isnan(data.top_1_weight) and data.top_1_weight > 0.30:
        reason = (
            f"The largest position is {data.top_1_weight:.1%} of the portfolio and "
            f"the top five are {data.top_5_weight:.1%}, so a small number of "
            "holdings determine most outcomes."
        )
    elif not np.isnan(data.max_sector_weight) and data.max_sector_weight > 0.45:
        reason = (
            f"One sector accounts for {data.max_sector_weight:.1%} of the "
            "portfolio, concentrating exposure to events affecting that sector."
        )
    else:
        reason = (
            f"Position sizes are reasonable: the largest holding is "
            f"{data.top_1_weight:.1%} and the top five are {data.top_5_weight:.1%}."
        )

    return ComponentScore(
        name="concentration",
        score=score,
        weight=COMPONENT_WEIGHTS["concentration"],
        contribution=(0.0 if np.isnan(score) else score / 100 * COMPONENT_WEIGHTS["concentration"]),
        inputs={
            "top_1_weight": _clean(data.top_1_weight),
            "top_5_weight": _clean(data.top_5_weight),
            "max_sector_weight": _clean(data.max_sector_weight),
            "subscores": {
                "top_1": _clean(top_1), "top_5": _clean(top_5), "sector": _clean(sector),
            },
        },
        reason=reason,
    )


def _score_liquidity(data: HealthInputs) -> ComponentScore:
    weights = data.asset_class_weights or {}
    total = sum(weights.values())

    if total <= 0:
        score = float("nan")
        weighted_liquidity = float("nan")
        reason = "No holdings to assess liquidity."
    else:
        weighted_liquidity = sum(
            (weight / total) * ASSET_CLASS_LIQUIDITY.get(str(asset_class).lower(), 0.5)
            for asset_class, weight in weights.items()
        )
        # The score is the weighted liquidity rating itself, on a 0-100 scale.
        #
        # A ramp between the best and worst achievable blends was tried first
        # and rejected: every asset in this universe is exchange-traded and
        # sellable within a day, so the worst achievable blend (all equity,
        # 0.70) is still perfectly liquid in practice. Stretching that narrow
        # real range across the full 0-100 scale manufactured large score
        # differences out of a distinction that barely exists, and dragged
        # sound portfolios down. Reporting the rating directly keeps the
        # component honest and trivially interpretable: an all-equity
        # portfolio scores 70, an all-cash one 100.
        score = float(weighted_liquidity * 100.0)
        reason = (
            f"Weighted liquidity rating of {weighted_liquidity:.2f}, where cash "
            "is 1.00 and listed equity 0.70. Every asset in this platform's "
            "universe is exchange-traded, so liquidity risk here is low and "
            "this component varies little between portfolios."
        )

    return ComponentScore(
        name="liquidity",
        score=score,
        weight=COMPONENT_WEIGHTS["liquidity"],
        contribution=(0.0 if np.isnan(score) else score / 100 * COMPONENT_WEIGHTS["liquidity"]),
        inputs={
            "asset_class_weights": {k: round(float(v), 4) for k, v in weights.items()},
            "weighted_liquidity": _clean(weighted_liquidity),
        },
        reason=reason,
    )


def _score_goal_alignment(data: HealthInputs) -> ComponentScore:
    if not data.has_goals:
        return ComponentScore(
            name="goal_alignment",
            score=float("nan"),
            weight=COMPONENT_WEIGHTS["goal_alignment"],
            contribution=0.0,
            inputs={"has_goals": False},
            reason=(
                "No goals have been set, so this component cannot be scored. "
                "Adding a goal lets the platform judge the portfolio against "
                "what it is actually for."
            ),
        )

    # 1.0 means exactly on the required trajectory; beyond 1.2 is comfortably
    # ahead and scores full marks.
    progress_score = _ramp(data.goal_progress_ratio, 0.4, 1.2)
    funding_score = _ramp(data.goal_funding_ratio, 0.4, 1.1)
    score = _mean_available([progress_score, funding_score])

    if np.isnan(score):
        reason = "Goals are set but there is not enough data to project progress."
    elif not np.isnan(data.goal_funding_ratio) and data.goal_funding_ratio >= 1.0:
        reason = (
            f"On the stated assumptions, the goals are projected to reach "
            f"{data.goal_funding_ratio:.0%} of their targets."
        )
    else:
        reason = (
            f"On the stated assumptions, the goals are projected to reach "
            f"{data.goal_funding_ratio:.0%} of their targets, leaving a shortfall. "
            "Contributions, target dates and expected returns all affect this."
        )

    return ComponentScore(
        name="goal_alignment",
        score=score,
        weight=COMPONENT_WEIGHTS["goal_alignment"],
        contribution=(0.0 if np.isnan(score) else score / 100 * COMPONENT_WEIGHTS["goal_alignment"]),
        inputs={
            "has_goals": True,
            "goal_progress_ratio": _clean(data.goal_progress_ratio),
            "goal_funding_ratio": _clean(data.goal_funding_ratio),
            "subscores": {
                "progress": _clean(progress_score), "funding": _clean(funding_score),
            },
        },
        reason=reason,
    )


def _score_behaviour(data: HealthInputs) -> ComponentScore:
    # Turnover above roughly 100% a year means the whole portfolio is
    # replaced annually, which costs more in fees and tax than it typically
    # recovers in a long-horizon retail portfolio.
    turnover_score = _ramp(data.annual_turnover, 2.0, 0.15)
    consistency_score = _ramp(data.contribution_consistency, 0.0, 1.0)
    drift_score = _ramp(data.allocation_drift, 0.60, 0.05)

    score = _mean_available([turnover_score, consistency_score, drift_score])

    if np.isnan(score):
        reason = "Not enough transaction history to assess investing behaviour."
    elif not np.isnan(data.annual_turnover) and data.annual_turnover > 1.0:
        reason = (
            f"Annual turnover of {data.annual_turnover:.0%} means the portfolio is "
            "effectively replaced each year, which incurs costs that a "
            "long-horizon portfolio rarely recovers."
        )
    elif not np.isnan(data.contribution_consistency) and data.contribution_consistency < 0.5:
        reason = (
            f"Contributions were made in {data.contribution_consistency:.0%} of "
            "months. Irregular investing makes goal projections less reliable."
        )
    else:
        reason = (
            f"Steady behaviour: {data.annual_turnover:.0%} annual turnover and "
            f"contributions in {data.contribution_consistency:.0%} of months."
        )

    return ComponentScore(
        name="behaviour",
        score=score,
        weight=COMPONENT_WEIGHTS["behaviour"],
        contribution=(0.0 if np.isnan(score) else score / 100 * COMPONENT_WEIGHTS["behaviour"]),
        inputs={
            "annual_turnover": _clean(data.annual_turnover),
            "contribution_consistency": _clean(data.contribution_consistency),
            "allocation_drift": _clean(data.allocation_drift),
            "subscores": {
                "turnover": _clean(turnover_score),
                "consistency": _clean(consistency_score),
                "drift": _clean(drift_score),
            },
        },
        reason=reason,
    )


def _clean(value: float) -> float | None:
    """JSON cannot carry NaN; absent values are reported as null."""
    try:
        return round_or_none(value, 6)
    except (TypeError, ValueError):
        return value


def _grade(total: float) -> str:
    if total >= 85:
        return "Excellent"
    if total >= 70:
        return "Good"
    if total >= 55:
        return "Fair"
    if total >= 40:
        return "Needs attention"
    return "Poor"


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def compute_health_score(data: HealthInputs) -> HealthScore:
    """Score a portfolio, returning both the total and its full derivation.

    Components whose inputs are unavailable are excluded and the remaining
    weights are renormalised, so a user with no goals is not silently
    penalised for a component that could not be measured. Which components
    were skipped is reported.
    """
    components = [
        _score_diversification(data),
        _score_risk(data),
        _score_concentration(data),
        _score_liquidity(data),
        _score_goal_alignment(data),
        _score_behaviour(data),
    ]

    scored = [c for c in components if not np.isnan(c.score)]
    missing = [c.name for c in components if np.isnan(c.score)]

    if not scored:
        return HealthScore(
            total=float("nan"), grade="Unknown", components=components,
            summary="Not enough data to score this portfolio.",
            missing_inputs=missing,
        )

    available_weight = sum(c.weight for c in scored)
    total = sum(c.score * c.weight for c in scored) / available_weight

    strongest = max(scored, key=lambda c: c.score)
    weakest = min(scored, key=lambda c: c.score)

    summary = (
        f"{_grade(total)} ({total:.0f}/100). "
        f"Strongest: {strongest.name.replace('_', ' ')} ({strongest.score:.0f}). "
        f"Weakest: {weakest.name.replace('_', ' ')} ({weakest.score:.0f})."
    )
    if missing:
        summary += (
            f" Scored on {len(scored)} of 6 components; "
            f"{', '.join(m.replace('_', ' ') for m in missing)} could not be measured."
        )

    return HealthScore(
        total=total, grade=_grade(total), components=components,
        summary=summary, missing_inputs=missing,
    )


def sensitivity_analysis(
    data: HealthInputs,
    perturbation: float = 0.10,
    compute: Callable[[HealthInputs], HealthScore] | None = None,
) -> list[dict]:
    """Measure how much each input moves the total score.

    Required by the PRD as evidence that the score is explainable. Each
    numeric input is shifted up and down by ``perturbation`` (relative, or
    absolute for inputs already expressed as a fraction) and the resulting
    change in the total is recorded. Inputs with a large swing are the ones
    actually driving the score.

    ``compute`` selects the scoring function, defaulting to v1. Passing
    ``compute_health_score_v2`` runs the identical analysis against v2, which
    is how the two are compared for saturation without a second copy of this
    logic going out of step with the first.
    """
    from dataclasses import replace

    scorer = compute or compute_health_score
    baseline = scorer(data).total
    if np.isnan(baseline):
        return []

    numeric_fields = [
        "n_holdings", "n_sectors", "n_asset_classes", "hhi_normalized",
        "average_pairwise_correlation", "annualized_volatility", "max_drawdown",
        "top_1_weight", "top_5_weight", "max_sector_weight",
        "goal_progress_ratio", "goal_funding_ratio",
        "annual_turnover", "contribution_consistency", "allocation_drift",
    ]

    results = []
    for name in numeric_fields:
        value = getattr(data, name)
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue

        step = abs(value) * perturbation if value else perturbation
        up = scorer(replace(data, **{name: value + step})).total
        down = scorer(replace(data, **{name: value - step})).total

        if np.isnan(up) or np.isnan(down):
            continue

        swing = abs(up - down)
        # A component already at full marks does not move when its input is
        # nudged. Reporting that as "lower is better" would be wrong and
        # misleading; it means the input is saturated at this level.
        if swing < 1e-9:
            direction = "no effect at this level"
        elif up > down:
            direction = "higher is better"
        else:
            direction = "lower is better"

        results.append({
            "input": name,
            "baseline_value": round(float(value), 6),
            "perturbation": round(float(step), 6),
            "score_if_increased": round(float(up), 2),
            "score_if_decreased": round(float(down), 2),
            "swing": round(float(swing), 3),
            "direction": direction,
            "saturated": bool(swing < 1e-9),
        })

    results.sort(key=lambda r: r["swing"], reverse=True)
    return results
