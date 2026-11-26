"""The Portfolio Health Score engine."""

from __future__ import annotations

import math

import pytest

from wealthos_core.health import (
    COMPONENT_WEIGHTS, HealthInputs, compute_health_score, sensitivity_analysis,
)


def _excellent() -> HealthInputs:
    """A well-built portfolio: diversified, on-profile, on-track, patient."""
    return HealthInputs(
        n_holdings=20, n_sectors=9, n_asset_classes=4,
        hhi_normalized=0.02, average_pairwise_correlation=0.20,
        annualized_volatility=0.12, max_drawdown=-0.15, risk_tolerance="moderate",
        top_1_weight=0.10, top_5_weight=0.45, max_sector_weight=0.22,
        asset_class_weights={"equity": 0.5, "debt": 0.25, "gold": 0.15, "cash": 0.10},
        has_goals=True, goal_progress_ratio=1.15, goal_funding_ratio=1.05,
        annual_turnover=0.15, contribution_consistency=1.0, allocation_drift=0.05,
    )


def _poor() -> HealthInputs:
    """A fragile one: concentrated, over-risked, behind, and churning."""
    return HealthInputs(
        n_holdings=2, n_sectors=1, n_asset_classes=1,
        hhi_normalized=0.85, average_pairwise_correlation=0.92,
        annualized_volatility=0.45, max_drawdown=-0.62, risk_tolerance="conservative",
        top_1_weight=0.75, top_5_weight=1.0, max_sector_weight=1.0,
        asset_class_weights={"equity": 1.0},
        has_goals=True, goal_progress_ratio=0.25, goal_funding_ratio=0.30,
        annual_turnover=2.5, contribution_consistency=0.1, allocation_drift=0.70,
    )


def test_score_is_bounded_to_zero_and_one_hundred():
    for data in (_excellent(), _poor()):
        assert 0.0 <= compute_health_score(data).total <= 100.0


def test_a_sound_portfolio_outscores_a_fragile_one():
    assert compute_health_score(_excellent()).total > compute_health_score(_poor()).total + 30


def test_every_component_is_reported_with_its_derivation(): 
    score = compute_health_score(_excellent())

    assert len(score.components) == 6
    assert {c.name for c in score.components} == set(COMPONENT_WEIGHTS)
    for component in score.components:
        assert component.reason           # always explains itself
        assert component.inputs           # always shows what it measured
        assert component.weight == COMPONENT_WEIGHTS[component.name]


def test_total_is_the_weighted_average_of_its_components():
    score = compute_health_score(_excellent())
    scored = [c for c in score.components if not math.isnan(c.score)]

    expected = sum(c.score * c.weight for c in scored) / sum(c.weight for c in scored)
    assert score.total == pytest.approx(expected)


def test_a_component_with_no_data_is_excluded_rather_than_scored_zero():
    # A user with no goals must not be punished for a component that simply
    # could not be measured.
    data = _excellent()
    data.has_goals = False
    score = compute_health_score(data)

    assert "goal_alignment" in score.missing_inputs
    scored = [c for c in score.components if not math.isnan(c.score)]
    assert len(scored) == 5
    # Renormalised over the remaining weights, so still a strong score.
    assert score.total > 70


def test_missing_goals_does_not_lower_the_score_below_a_zero_scored_goal():
    without_goals = _excellent()
    without_goals.has_goals = False

    badly_behind = _excellent()
    badly_behind.goal_progress_ratio = 0.1
    badly_behind.goal_funding_ratio = 0.1

    assert compute_health_score(without_goals).total > compute_health_score(badly_behind).total


def test_risk_band_follows_the_stated_tolerance():
    # The same 20% volatility is appropriate for an aggressive investor and
    # excessive for a conservative one. The component must reflect that.
    conservative = _excellent()
    conservative.risk_tolerance = "conservative"
    conservative.annualized_volatility = 0.20

    aggressive = _excellent()
    aggressive.risk_tolerance = "aggressive"
    aggressive.annualized_volatility = 0.20

    def risk_score(data):
        return next(c.score for c in compute_health_score(data).components if c.name == "risk")

    assert risk_score(aggressive) > risk_score(conservative)


def test_taking_too_much_risk_is_penalised_harder_than_too_little():
    # Overshooting can cause a loss the investor never agreed to; undershooting
    # mostly costs return.
    under = _excellent()
    under.annualized_volatility = 0.02   # 6pp below the moderate band's floor

    over = _excellent()
    over.annualized_volatility = 0.23    # 6pp above its ceiling

    def risk_score(data):
        return next(c.score for c in compute_health_score(data).components if c.name == "risk")

    assert risk_score(under) > risk_score(over)


def test_correlated_holdings_score_lower_than_independent_ones():
    # Twenty holdings that all move together are not twenty bets. Holding
    # counts alone cannot see this, which is why correlation is a component.
    independent = _excellent()
    independent.average_pairwise_correlation = 0.15

    correlated = _excellent()
    correlated.average_pairwise_correlation = 0.95

    def diversification(data):
        return next(
            c.score for c in compute_health_score(data).components if c.name == "diversification"
        )

    assert diversification(independent) > diversification(correlated)


def test_liquidity_score_is_the_weighted_rating_itself():
    # All-cash is 100, all listed equity is 70. Reporting the rating directly
    # keeps the component interpretable in a universe where everything is
    # exchange-traded.
    cash = _excellent()
    cash.asset_class_weights = {"cash": 1.0}
    equity = _excellent()
    equity.asset_class_weights = {"equity": 1.0}

    def liquidity(data):
        return next(c.score for c in compute_health_score(data).components if c.name == "liquidity")

    assert liquidity(cash) == pytest.approx(100.0)
    assert liquidity(equity) == pytest.approx(70.0)


def test_an_empty_portfolio_scores_nothing_rather_than_zero():
    """Both facts hold, so `or` was hiding whichever one broke.

    On the dataclass the total stays NaN — that is the internal convention.
    It becomes null at the serialisation boundary; see
    tests/test_json_safety.py.
    """
    score = compute_health_score(HealthInputs())
    assert math.isnan(score.total)
    assert score.grade == "Unknown"
    assert score.as_dict()["total"] is None


def test_grades_follow_the_total():
    assert compute_health_score(_excellent()).grade in {"Excellent", "Good"}
    assert compute_health_score(_poor()).grade in {"Poor", "Needs attention"}


# --------------------------------------------------------------------------
# Sensitivity
# --------------------------------------------------------------------------

def test_sensitivity_ranks_inputs_by_their_effect():
    results = sensitivity_analysis(_excellent())

    assert results
    swings = [r["swing"] for r in results]
    assert swings == sorted(swings, reverse=True)
    for entry in results:
        assert entry["swing"] >= 0
        assert entry["direction"] in {
            "higher is better", "lower is better", "no effect at this level",
        }


def test_sensitivity_identifies_the_right_direction():
    # Uses a mid-range portfolio on purpose. In the "excellent" fixture most
    # components already sit at full marks, so nudging their inputs moves
    # nothing and there is no direction to detect.
    data = _excellent()
    data.n_sectors = 4
    data.top_1_weight = 0.30
    data.top_5_weight = 0.75
    data.max_sector_weight = 0.45

    results = {r["input"]: r for r in sensitivity_analysis(data)}

    assert results["n_sectors"]["direction"] == "higher is better"
    assert results["top_5_weight"]["direction"] == "lower is better"
    assert results["top_1_weight"]["direction"] == "lower is better"


def test_a_saturated_input_is_reported_as_having_no_effect():
    # n_sectors=9 is past the point where more sectors add anything, so the
    # score does not move. That must read as "no effect", not as a direction.
    results = {r["input"]: r for r in sensitivity_analysis(_excellent())}

    sectors = results["n_sectors"]
    assert sectors["saturated"] is True
    assert sectors["direction"] == "no effect at this level"
    assert sectors["swing"] == pytest.approx(0.0)


def test_sensitivity_skips_inputs_that_were_never_measured():
    data = _excellent()
    data.annual_turnover = float("nan")

    assert "annual_turnover" not in {r["input"] for r in sensitivity_analysis(data)}
