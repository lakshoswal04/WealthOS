"""Goal projection.

Projections are deterministic compound-growth arithmetic under explicitly
stated assumptions, not predictions. Every result carries the return,
contribution and horizon that produced it, and scenarios are always returned
as a range rather than a single number, because presenting one figure
invites it to be read as a promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .constants import MONTHS_PER_YEAR

__all__ = [
    "GoalProjection",
    "months_between",
    "future_value",
    "required_monthly_contribution",
    "project_goal",
    "SCENARIOS",
]

# Return scenarios, expressed as offsets from the portfolio's expected
# return in units of the standard error of the long-run average return
# (sigma / sqrt(years)), not of single-year volatility. Showing a band rather
# than a point estimate is what keeps a projection from reading as a
# guarantee.
SCENARIOS = {
    "pessimistic": -1.0,
    "expected": 0.0,
    "optimistic": +1.0,
}


@dataclass
class GoalProjection:
    goal_id: int | None
    name: str
    target_amount: float
    current_amount: float
    monthly_contribution: float
    target_date: date
    months_remaining: int

    projected_value: float
    funding_ratio: float            # projected / target
    shortfall: float                # positive when short
    on_track: bool

    progress_ratio: float           # actual / what should be saved by now
    required_monthly_contribution: float
    contribution_gap: float

    assumptions: dict
    scenarios: dict

    def as_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "name": self.name,
            "target_amount": round(self.target_amount, 2),
            "current_amount": round(self.current_amount, 2),
            "monthly_contribution": round(self.monthly_contribution, 2),
            "target_date": str(self.target_date),
            "months_remaining": self.months_remaining,
            "projected_value": round(self.projected_value, 2),
            "funding_ratio": round(self.funding_ratio, 4),
            "shortfall": round(self.shortfall, 2),
            "on_track": self.on_track,
            "progress_ratio": round(self.progress_ratio, 4),
            "required_monthly_contribution": round(self.required_monthly_contribution, 2),
            "contribution_gap": round(self.contribution_gap, 2),
            "assumptions": self.assumptions,
            "scenarios": self.scenarios,
        }


def months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``, floored at zero."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def future_value(
    present_value: float,
    monthly_contribution: float,
    annual_return: float,
    months: int,
) -> float:
    """Value after ``months`` of compounding plus monthly contributions.

    ``FV = PV(1+r)^n + PMT · ((1+r)^n − 1) / r`` with ``r`` the monthly rate,
    derived from the annual rate geometrically rather than by dividing by 12,
    so the compounding is consistent.

    Contributions are treated as arriving at the end of each month, which is
    the conservative convention.
    """
    if months <= 0:
        return float(present_value)

    monthly_rate = (1.0 + annual_return) ** (1.0 / MONTHS_PER_YEAR) - 1.0

    if abs(monthly_rate) < 1e-12:
        return float(present_value + monthly_contribution * months)

    growth = (1.0 + monthly_rate) ** months
    return float(present_value * growth + monthly_contribution * (growth - 1.0) / monthly_rate)


def required_monthly_contribution(
    target_amount: float,
    present_value: float,
    annual_return: float,
    months: int,
) -> float:
    """Monthly amount needed to reach the target by the target date.

    Returns 0 when existing savings already grow past the target unaided.
    """
    if months <= 0:
        return max(0.0, float(target_amount - present_value))

    monthly_rate = (1.0 + annual_return) ** (1.0 / MONTHS_PER_YEAR) - 1.0

    if abs(monthly_rate) < 1e-12:
        return max(0.0, float((target_amount - present_value) / months))

    growth = (1.0 + monthly_rate) ** months
    grown_savings = present_value * growth
    if grown_savings >= target_amount:
        return 0.0

    return float((target_amount - grown_savings) * monthly_rate / (growth - 1.0))


def project_goal(
    target_amount: float,
    current_amount: float,
    monthly_contribution: float,
    target_date: date,
    expected_annual_return: float,
    return_volatility: float = 0.0,
    as_of: date | None = None,
    goal_id: int | None = None,
    name: str = "",
    started_on: date | None = None,
) -> GoalProjection:
    """Project a goal forward under stated assumptions.

    ``progress_ratio`` compares what has actually been saved with what a
    straight-line plan would have accumulated by now. It is the measure that
    distinguishes "started late but contributing hard" from "quietly falling
    behind", which a simple percent-of-target figure hides.
    """
    as_of = as_of or date.today()
    months = months_between(as_of, target_date)

    projected = future_value(current_amount, monthly_contribution, expected_annual_return, months)
    funding_ratio = projected / target_amount if target_amount > 0 else float("nan")
    shortfall = max(0.0, target_amount - projected)

    required = required_monthly_contribution(
        target_amount, current_amount, expected_annual_return, months
    )

    # Where a straight-line plan would stand today.
    if started_on is not None:
        elapsed = months_between(started_on, as_of)
        total_months = elapsed + months
        expected_by_now = (
            target_amount * (elapsed / total_months) if total_months > 0 else 0.0
        )
    else:
        total_months = months + 1
        expected_by_now = target_amount / total_months if total_months > 0 else 0.0

    progress_ratio = (
        current_amount / expected_by_now if expected_by_now > 0 else float("nan")
    )

    # Scenario spread uses the standard error of the AVERAGE annual return
    # over the horizon, which is sigma / sqrt(years), not sigma itself.
    #
    # This distinction matters a great deal. Applying a full annual sigma of
    # 11% as a rate sustained for fifteen years produced a band from 90% to
    # 642% funded here, which is not an uncertainty range so much as an
    # arithmetic artifact: single-year volatility does not persist as a
    # permanent shift in the long-run average. Good and bad years partially
    # offset, so the mean return over a long horizon is far more tightly
    # determined than any one year's return.
    years = max(months / MONTHS_PER_YEAR, 1.0 / MONTHS_PER_YEAR)
    return_standard_error = return_volatility / np.sqrt(years)

    scenarios: dict[str, dict] = {}
    for label, sigma in SCENARIOS.items():
        rate = expected_annual_return + sigma * return_standard_error
        # A scenario below total loss is not meaningful.
        rate = max(rate, -0.95)
        value = future_value(current_amount, monthly_contribution, rate, months)
        scenarios[label] = {
            "annual_return": round(float(rate), 4),
            "projected_value": round(float(value), 2),
            "funding_ratio": round(float(value / target_amount), 4) if target_amount > 0 else None,
            "shortfall": round(float(max(0.0, target_amount - value)), 2),
        }

    return GoalProjection(
        goal_id=goal_id,
        name=name,
        target_amount=float(target_amount),
        current_amount=float(current_amount),
        monthly_contribution=float(monthly_contribution),
        target_date=target_date,
        months_remaining=months,
        projected_value=float(projected),
        funding_ratio=float(funding_ratio),
        shortfall=float(shortfall),
        on_track=bool(projected >= target_amount),
        progress_ratio=float(progress_ratio),
        required_monthly_contribution=float(required),
        contribution_gap=float(max(0.0, required - monthly_contribution)),
        assumptions={
            "expected_annual_return": round(float(expected_annual_return), 4),
            "return_volatility": round(float(return_volatility), 4),
            "return_standard_error": round(float(return_standard_error), 4),
            "as_of": str(as_of),
            "months_remaining": months,
            "contribution_timing": "end of month",
            "compounding": "monthly, derived geometrically from the annual rate",
            "note": (
                "A projection under these assumptions, not a prediction. Actual "
                "returns vary and may be negative."
            ),
        },
        scenarios=scenarios,
    )


def projection_path(
    current_amount: float,
    monthly_contribution: float,
    annual_return: float,
    months: int,
) -> list[float]:
    """Month-by-month projected values, for the goal chart."""
    monthly_rate = (1.0 + annual_return) ** (1.0 / MONTHS_PER_YEAR) - 1.0
    value = float(current_amount)
    path = [value]
    for _ in range(max(months, 0)):
        value = value * (1.0 + monthly_rate) + monthly_contribution
        path.append(value)
    return path
