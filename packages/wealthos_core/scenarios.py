"""A bank of fully specified portfolios, for validating the Health Score.

A score is only useful if it separates portfolios that differ and agrees
with itself on portfolios that do not. Neither property can be demonstrated
on one example, and neither can be demonstrated on real user data, because
there is no ground truth to compare against. So the bank below states, for
each scenario, what a competent analyst would say about it — and the tests
check that the score agrees.

Every field is written out rather than defaulted. A scenario that leans on
defaults is a scenario whose author did not decide what it represents, and
the difference between "unmeasured" and "measured as zero" is exactly what
these inputs have to pin down.

``EXPECTED_ORDER`` is the claim under test: it is an ordering a human can
argue with, which is the point. If the score disagrees with it, either the
score or the ordering is wrong, and the disagreement is worth having.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .health import HealthInputs

__all__ = ["Scenario", "SCENARIOS", "QUALITY_TIERS", "UNSCORABLE",
           "scenario", "names", "tier_of"]


@dataclass(frozen=True)
class Scenario:
    """A named portfolio with the verdict it is expected to receive."""

    name: str
    description: str
    inputs: HealthInputs
    expectation: str


def _textbook() -> HealthInputs:
    """A deliberately good portfolio: the top of the range.

    Twenty-eight holdings across eight sectors and four asset classes, a 12%
    cash-and-debt buffer, volatility inside a moderate band, a drawdown
    inside tolerance, goals slightly ahead, low turnover and steady funding.
    """
    return HealthInputs(
        n_holdings=28, n_sectors=8, n_asset_classes=4,
        hhi_normalized=0.04, average_pairwise_correlation=0.28,
        annualized_volatility=0.13, max_drawdown=-0.18, risk_tolerance="moderate",
        top_1_weight=0.08, top_5_weight=0.34, max_sector_weight=0.22,
        asset_class_weights={"equity": 0.58, "etf": 0.18, "gold": 0.06,
                             "debt": 0.10, "cash": 0.08},
        has_goals=True, goal_progress_ratio=1.08, goal_funding_ratio=1.04,
        annual_turnover=0.18, contribution_consistency=0.92,
        allocation_drift=0.07,
    )


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="textbook_balanced",
        description="28 holdings, 8 sectors, 4 asset classes, goals on track",
        inputs=_textbook(),
        expectation="Should score at the top of the range. Nothing is wrong with it.",
    ),
    Scenario(
        name="diversified_no_buffer",
        description="As textbook, but nothing in cash or debt",
        inputs=replace(
            _textbook(),
            asset_class_weights={"equity": 0.74, "etf": 0.20, "gold": 0.06},
            n_asset_classes=3,
        ),
        expectation=(
            "Should score below textbook_balanced and above the concentrated "
            "cases. This is the scenario v1 could barely distinguish: its "
            "liquidity component moved about three points."
        ),
    ),
    Scenario(
        name="concentrated_equity",
        description="6 holdings, 2 sectors, one position at 38%",
        inputs=HealthInputs(
            n_holdings=6, n_sectors=2, n_asset_classes=1,
            hhi_normalized=0.31, average_pairwise_correlation=0.74,
            annualized_volatility=0.26, max_drawdown=-0.37,
            risk_tolerance="moderate",
            top_1_weight=0.38, top_5_weight=0.92, max_sector_weight=0.66,
            asset_class_weights={"equity": 1.0},
            has_goals=True, goal_progress_ratio=0.72, goal_funding_ratio=0.68,
            annual_turnover=0.55, contribution_consistency=0.58,
            allocation_drift=0.22,
        ),
        expectation=(
            "Should score poorly on diversification, concentration, risk and "
            "liquidity at once — the failures are correlated in reality and "
            "the score should reflect that rather than averaging them away."
        ),
    ),
    Scenario(
        name="single_holding",
        description="One stock, nothing else",
        inputs=HealthInputs(
            n_holdings=1, n_sectors=1, n_asset_classes=1,
            hhi_normalized=1.0, average_pairwise_correlation=float("nan"),
            annualized_volatility=0.42, max_drawdown=-0.58,
            risk_tolerance="moderate",
            top_1_weight=1.0, top_5_weight=1.0, max_sector_weight=1.0,
            asset_class_weights={"equity": 1.0},
            has_goals=True, goal_progress_ratio=0.35, goal_funding_ratio=0.30,
            annual_turnover=0.0, contribution_consistency=0.25,
            allocation_drift=0.0,
        ),
        expectation=(
            "The worst scorable case. Correlation is NaN because a single "
            "holding has no pairs to correlate — unmeasurable, not zero."
        ),
    ),
    Scenario(
        name="risk_mismatch_too_hot",
        description="Well-built portfolio, but the investor is conservative",
        inputs=replace(
            _textbook(),
            risk_tolerance="conservative",
            annualized_volatility=0.24, max_drawdown=-0.31,
        ),
        expectation=(
            "Diversification and concentration should stay high while risk "
            "falls: the portfolio is fine, it is the wrong portfolio for this "
            "investor. Also the case v1 handled worst — it scored a "
            "conservative investor 50 on risk for a drawdown sitting exactly "
            "at their own stated tolerance. Held identical to too_cold except "
            "for tolerance and the two risk measures."
        ),
    ),
    Scenario(
        name="risk_mismatch_too_cold",
        description="Aggressive investor holding a portfolio that barely moves",
        inputs=replace(
            _textbook(),
            risk_tolerance="aggressive",
            annualized_volatility=0.05, max_drawdown=-0.04,
        ),
        expectation=(
            "Should be penalised, but far less harshly than too_hot: "
            "undershooting risk costs return, overshooting can cost capital, "
            "and _band_score encodes that asymmetry with a 0.6 under-penalty "
            "against 1.0 over. Derived from the textbook portfolio by changing "
            "only the tolerance and the two risk measures, so the comparison "
            "with too_hot isolates the risk component instead of confounding "
            "it with a different portfolio."
        ),
    ),
    Scenario(
        name="conservative_appropriate",
        description="Low-volatility portfolio held by a conservative investor",
        inputs=HealthInputs(
            n_holdings=18, n_sectors=7, n_asset_classes=4,
            hhi_normalized=0.07, average_pairwise_correlation=0.33,
            annualized_volatility=0.08, max_drawdown=-0.09,
            risk_tolerance="conservative",
            top_1_weight=0.11, top_5_weight=0.42, max_sector_weight=0.24,
            asset_class_weights={"equity": 0.30, "debt": 0.40,
                                 "gold": 0.10, "cash": 0.20},
            has_goals=True, goal_progress_ratio=1.0, goal_funding_ratio=0.98,
            annual_turnover=0.12, contribution_consistency=0.95,
            allocation_drift=0.05,
        ),
        expectation=(
            "Should score well. The same volatility that is a mismatch for an "
            "aggressive investor is correct for this one, so the score must "
            "depend on the stated tolerance and not on the volatility alone."
        ),
    ),
    Scenario(
        name="churner",
        description="Diversified holdings, traded constantly",
        inputs=replace(
            _textbook(),
            annual_turnover=2.4, contribution_consistency=0.33,
            allocation_drift=0.55,
        ),
        expectation=(
            "Only behaviour should fall. It carries weight 15, so the total "
            "should drop noticeably without collapsing — the holdings really "
            "are fine."
        ),
    ),
    Scenario(
        name="no_goals",
        description="Good portfolio, no goals set",
        inputs=replace(
            _textbook(),
            has_goals=False,
            goal_progress_ratio=float("nan"), goal_funding_ratio=float("nan"),
        ),
        expectation=(
            "Goal alignment must be reported missing, not scored zero, and the "
            "remaining weights renormalised. An unset goal is an absence of "
            "information about the user, not a fault in the portfolio."
        ),
    ),
    Scenario(
        name="thin_history",
        description="Newly opened account: holdings known, no price history yet",
        inputs=HealthInputs(
            n_holdings=11, n_sectors=5, n_asset_classes=3,
            hhi_normalized=0.11, average_pairwise_correlation=float("nan"),
            annualized_volatility=float("nan"), max_drawdown=float("nan"),
            risk_tolerance="moderate",
            top_1_weight=0.17, top_5_weight=0.55, max_sector_weight=0.31,
            asset_class_weights={"equity": 0.65, "debt": 0.25, "cash": 0.10},
            has_goals=False,
            goal_progress_ratio=float("nan"), goal_funding_ratio=float("nan"),
            annual_turnover=float("nan"), contribution_consistency=float("nan"),
            allocation_drift=float("nan"),
        ),
        expectation=(
            "Risk, goal alignment and behaviour should all be reported missing. "
            "The score must come from what is known and say what is not."
        ),
    ),
    Scenario(
        name="empty",
        description="An account with nothing in it",
        inputs=HealthInputs(),
        expectation=(
            "Unscorable. Grade Unknown and a null total — not a zero, which "
            "would read as a verdict on a portfolio that does not exist."
        ),
    ),
)


# The claim under test, stated as tiers rather than a total order.
#
# A strict ranking of all ten would have the suite asserting that
# conservative_appropriate (91.3) beats risk_mismatch_too_cold (91.1) — a
# 0.2-point claim no analyst could defend and no useful score needs to make.
# Tiers assert only what is worth asserting: every portfolio in a tier scores
# above every portfolio in the tier below. That is falsifiable, and it is the
# property a user actually relies on.
QUALITY_TIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sound", (
        "textbook_balanced",
        "no_goals",
        "conservative_appropriate",
        "risk_mismatch_too_cold",
        "diversified_no_buffer",
    )),
    ("compromised", (
        "churner",
        "risk_mismatch_too_hot",
        "thin_history",
    )),
    ("poor", (
        "concentrated_equity",
    )),
    ("severe", (
        "single_holding",
    )),
)

# `empty` belongs to no tier: it has no score to place.
UNSCORABLE: tuple[str, ...] = ("empty",)

# The two mismatch scenarios are identical but for the risk inputs, so the
# gap between them is attributable to the risk component alone. That is the
# comparison worth making; a first draft of this bank gave them different
# portfolios, and the ordering that produced was meaningless.


def names() -> tuple[str, ...]:
    return tuple(s.name for s in SCENARIOS)


def scenario(name: str) -> Scenario:
    for item in SCENARIOS:
        if item.name == name:
            return item
    raise KeyError(f"no scenario named {name!r}; have {names()}")


def tier_of(name: str) -> str:
    for tier, members in QUALITY_TIERS:
        if name in members:
            return tier
    if name in UNSCORABLE:
        return "unscorable"
    raise KeyError(f"{name!r} is in no tier")
