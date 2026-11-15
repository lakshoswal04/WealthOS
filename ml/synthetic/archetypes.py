"""Latent investor archetypes used to generate the synthetic cohort.

Each archetype is a set of distributions over profile, allocation and
behaviour. Generating from known archetypes buys something a purely random
cohort cannot: the clustering model can be scored against the true
generating label with Adjusted Rand Index, not just silhouette. Silhouette
says whether clusters are tight; ARI says whether they are the *right*
clusters.

Two deliberate design choices:

Stated risk tolerance does not always match behaviour. A fraction of every
archetype is given a tolerance inconsistent with how it actually invests,
because detecting that divergence is one of the product's stated goals, and
a cohort where the two always agree would make the problem trivial.

Archetypes overlap. Real investors do not fall into clean groups, and a
cohort of perfectly separated blobs would flatter the clustering model into
a silhouette score that says nothing about real performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["Archetype", "ARCHETYPES", "ARCHETYPE_NAMES", "sample_profile"]


@dataclass(frozen=True)
class Archetype:
    name: str
    description: str
    share: float                       # fraction of the cohort

    # --- profile ---
    age_range: tuple[int, int]
    income_lognormal: tuple[float, float]       # (mu, sigma) of log annual income
    savings_rate_range: tuple[float, float]     # fraction of income saved monthly
    horizon_range: tuple[int, int]
    stated_risk: str
    # How often the stated tolerance contradicts the actual allocation.
    risk_mismatch_probability: float

    # --- target allocation, as Dirichlet concentrations ---
    # equity, etf, gold, debt, cash. Larger values mean a tighter
    # distribution around the implied mean.
    allocation_alpha: tuple[float, float, float, float, float]

    # --- holdings ---
    n_equity_range: tuple[int, int]
    # Dirichlet concentration within equity holdings; low = concentrated.
    equity_weight_alpha: float

    # --- behaviour ---
    annual_turnover_range: tuple[float, float]
    contribution_probability: tuple[float, float]   # chance a given month is funded
    rebalance_months: int                            # 0 means never
    lump_sum_multiple: tuple[float, float]           # opening balance, in months of savings


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        name="conservative_saver",
        description=(
            "Prioritises capital preservation. Heavy in debt and cash, few "
            "equity positions, contributes reliably and rarely trades."
        ),
        share=0.18,
        age_range=(38, 65),
        income_lognormal=(13.5, 0.45),
        savings_rate_range=(0.15, 0.30),
        horizon_range=(5, 15),
        stated_risk="conservative",
        risk_mismatch_probability=0.12,
        allocation_alpha=(8.0, 5.0, 6.0, 22.0, 12.0),
        n_equity_range=(3, 8),
        equity_weight_alpha=6.0,
        annual_turnover_range=(0.02, 0.18),
        contribution_probability=(0.85, 0.98),
        rebalance_months=12,
        lump_sum_multiple=(6.0, 30.0),
    ),
    Archetype(
        name="balanced_investor",
        description=(
            "A conventional mix of equity, ETFs, gold and debt. Moderate "
            "turnover and steady contributions."
        ),
        share=0.26,
        age_range=(30, 55),
        income_lognormal=(13.8, 0.5),
        savings_rate_range=(0.18, 0.35),
        horizon_range=(10, 25),
        stated_risk="moderate",
        risk_mismatch_probability=0.15,
        allocation_alpha=(20.0, 14.0, 7.0, 11.0, 4.0),
        n_equity_range=(6, 16),
        equity_weight_alpha=5.0,
        annual_turnover_range=(0.08, 0.40),
        contribution_probability=(0.70, 0.95),
        rebalance_months=12,
        lump_sum_multiple=(3.0, 24.0),
    ),
    Archetype(
        name="aggressive_growth",
        description=(
            "Almost entirely equity, concentrated in a handful of convictions, "
            "with little interest in debt or gold."
        ),
        share=0.20,
        age_range=(24, 42),
        income_lognormal=(13.9, 0.6),
        savings_rate_range=(0.20, 0.45),
        horizon_range=(15, 35),
        stated_risk="aggressive",
        risk_mismatch_probability=0.18,
        allocation_alpha=(34.0, 9.0, 3.0, 2.5, 2.0),
        n_equity_range=(4, 12),
        equity_weight_alpha=2.2,
        annual_turnover_range=(0.20, 0.80),
        contribution_probability=(0.55, 0.90),
        rebalance_months=0,
        lump_sum_multiple=(1.0, 14.0),
    ),
    Archetype(
        name="active_trader",
        description=(
            "Trades frequently and rotates positions. High turnover, erratic "
            "contributions, concentrated bets."
        ),
        share=0.12,
        age_range=(25, 48),
        income_lognormal=(13.7, 0.7),
        savings_rate_range=(0.10, 0.40),
        horizon_range=(3, 15),
        stated_risk="aggressive",
        risk_mismatch_probability=0.22,
        allocation_alpha=(30.0, 6.0, 4.0, 3.0, 5.0),
        n_equity_range=(5, 18),
        equity_weight_alpha=1.8,
        annual_turnover_range=(0.90, 3.00),
        contribution_probability=(0.30, 0.75),
        rebalance_months=3,
        lump_sum_multiple=(1.0, 10.0),
    ),
    Archetype(
        name="goal_focused_sip",
        description=(
            "Systematic monthly investing, mostly through index ETFs. Very "
            "consistent, very low turnover, broadly diversified."
        ),
        share=0.17,
        age_range=(26, 45),
        income_lognormal=(13.6, 0.45),
        savings_rate_range=(0.20, 0.40),
        horizon_range=(12, 30),
        stated_risk="moderate",
        risk_mismatch_probability=0.10,
        allocation_alpha=(10.0, 26.0, 6.0, 9.0, 3.0),
        n_equity_range=(2, 8),
        equity_weight_alpha=7.0,
        annual_turnover_range=(0.01, 0.12),
        contribution_probability=(0.92, 1.00),
        rebalance_months=6,
        lump_sum_multiple=(0.0, 8.0),
    ),
    Archetype(
        name="dormant_holder",
        description=(
            "Invested once and largely stopped. Rare contributions, almost no "
            "trading, allocation drifts wherever the market takes it."
        ),
        share=0.07,
        age_range=(32, 62),
        income_lognormal=(13.4, 0.55),
        savings_rate_range=(0.03, 0.15),
        horizon_range=(5, 25),
        stated_risk="moderate",
        risk_mismatch_probability=0.25,
        allocation_alpha=(18.0, 10.0, 6.0, 7.0, 6.0),
        n_equity_range=(2, 10),
        equity_weight_alpha=3.0,
        annual_turnover_range=(0.00, 0.05),
        contribution_probability=(0.02, 0.22),
        rebalance_months=0,
        lump_sum_multiple=(8.0, 40.0),
    ),
)

ARCHETYPE_NAMES = tuple(a.name for a in ARCHETYPES)

RISK_LEVELS = ("conservative", "moderate", "aggressive")


def sample_profile(archetype: Archetype, rng: np.random.Generator) -> dict:
    """Draw one investor's profile and behavioural parameters."""
    age = int(rng.integers(*archetype.age_range))

    mu, sigma = archetype.income_lognormal
    annual_income = float(np.clip(rng.lognormal(mu, sigma), 180_000, 60_000_000))

    savings_rate = float(rng.uniform(*archetype.savings_rate_range))
    monthly_savings = annual_income * savings_rate / 12.0

    horizon = int(rng.integers(*archetype.horizon_range))

    # Stated tolerance usually matches the archetype, but sometimes does not.
    stated_risk = archetype.stated_risk
    if rng.random() < archetype.risk_mismatch_probability:
        alternatives = [r for r in RISK_LEVELS if r != archetype.stated_risk]
        stated_risk = str(rng.choice(alternatives))

    target_allocation = rng.dirichlet(np.array(archetype.allocation_alpha))

    return {
        "archetype": archetype.name,
        "age": age,
        "annual_income": round(annual_income, 2),
        "monthly_savings": round(monthly_savings, 2),
        "investment_horizon_years": horizon,
        "risk_tolerance": stated_risk,
        "risk_matches_archetype": stated_risk == archetype.stated_risk,
        "target_allocation": {
            "equity": float(target_allocation[0]),
            "etf": float(target_allocation[1]),
            "gold": float(target_allocation[2]),
            "debt": float(target_allocation[3]),
            "cash": float(target_allocation[4]),
        },
        "n_equity_holdings": int(rng.integers(*archetype.n_equity_range)),
        "equity_weight_alpha": archetype.equity_weight_alpha,
        "annual_turnover": float(rng.uniform(*archetype.annual_turnover_range)),
        "contribution_probability": float(rng.uniform(*archetype.contribution_probability)),
        "rebalance_months": archetype.rebalance_months,
        "lump_sum_multiple": float(rng.uniform(*archetype.lump_sum_multiple)),
    }
