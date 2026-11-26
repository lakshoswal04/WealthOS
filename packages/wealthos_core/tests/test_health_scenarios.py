"""Validation of Health Score v2 against v1, on the scenario bank.

Each test states a claim v2 makes and checks it. Where v1 is the comparison,
v1's actual measured behaviour is asserted too — so these tests document the
defect as well as the fix, and a regression in either direction is visible.

Expected values come from running the two implementations over
``scenarios.py``; the derivation is in the comment above each number.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from wealthos_core.health import compute_health_score as score_v1
from wealthos_core.health_v2 import (
    DRAWDOWN_BREACH_MULTIPLE,
    compute_health_score_v2 as score_v2,
)
from wealthos_core.scenarios import (
    QUALITY_TIERS,
    SCENARIOS,
    UNSCORABLE,
    scenario,
)

SCORABLE = [s for s in SCENARIOS if s.name not in UNSCORABLE]


def _component(result, name):
    return next(c for c in result.components if c.name == name)


def _subscores(result, name):
    return _component(result, name).inputs["subscores"]


# --------------------------------------------------------------------------
# The bank itself
# --------------------------------------------------------------------------

def test_every_scenario_is_in_exactly_one_tier():
    placed = [n for _, members in QUALITY_TIERS for n in members] + list(UNSCORABLE)
    assert sorted(placed) == sorted(s.name for s in SCENARIOS)
    assert len(placed) == len(set(placed)), "a scenario appears in two tiers"


def test_every_scenario_states_what_it_expects():
    # A scenario without a written expectation is an input fixture, not a
    # validation case: there is nothing for the score to be wrong about.
    for item in SCENARIOS:
        assert len(item.expectation) > 40, item.name
        assert len(item.description) > 10, item.name


@pytest.mark.parametrize("item", SCORABLE, ids=lambda s: s.name)
def test_every_scorable_scenario_produces_a_number(item):
    result = score_v2(item.inputs)
    assert not math.isnan(result.total)
    assert result.grade != "Unknown"
    assert 0.0 <= result.total <= 100.0


def test_the_empty_account_is_unscorable_in_both_versions():
    for compute in (score_v1, score_v2):
        result = compute(scenario("empty").inputs)
        assert math.isnan(result.total)
        assert result.grade == "Unknown"
        assert result.as_dict()["total"] is None
        assert len(result.missing_inputs) == 6


# --------------------------------------------------------------------------
# Claim 1: the tiers hold
# --------------------------------------------------------------------------

def test_v2_scores_every_tier_above_the_tier_below_it():
    totals = {s.name: score_v2(s.inputs).total for s in SCORABLE}

    for (upper_name, upper), (lower_name, lower) in zip(QUALITY_TIERS, QUALITY_TIERS[1:]):
        worst_above = min(totals[n] for n in upper)
        best_below = max(totals[n] for n in lower)
        assert worst_above > best_below, (
            f"{upper_name} tier reaches down to {worst_above:.1f} while "
            f"{lower_name} reaches up to {best_below:.1f}"
        )


def test_v2_uses_more_of_the_scale_than_v1():
    """Measured across the bank: v1 spans 72.5 points, v2 spans 81.9.

    Range alone is a weak argument — a score can spread portfolios out by
    being noisier rather than sharper. It is recorded because the direction
    matters alongside the component-level evidence below, not as the case on
    its own.
    """
    v1 = [score_v1(s.inputs).total for s in SCORABLE]
    v2 = [score_v2(s.inputs).total for s in SCORABLE]

    assert max(v1) - min(v1) == pytest.approx(72.5, abs=0.5)
    assert max(v2) - min(v2) == pytest.approx(81.9, abs=0.5)
    assert (max(v2) - min(v2)) > (max(v1) - min(v1))


# --------------------------------------------------------------------------
# Claim 2: the contributions sum to the total (v1 missed by up to 40.7)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item", SCORABLE, ids=lambda s: s.name)
def test_v2_contributions_sum_to_the_total(item):
    result = score_v2(item.inputs)
    parts = sum(c.contribution for c in result.components
                if not math.isnan(c.contribution))
    assert parts == pytest.approx(result.total, abs=1e-9)


def test_v1_contributions_do_not_sum_to_the_total_when_anything_is_missing():
    """The defect, measured, so the fix cannot be quietly reverted.

    thin_history is a new account: holdings known, no price history, no goals,
    no transactions. v1 reports a total of 74.0 built from contributions that
    add to 33.3 — the headline number and the bar chart beneath it disagree by
    40.7 points, because the contributions divide by the raw weight total
    while the total divides by the renormalised one.
    """
    result = score_v1(scenario("thin_history").inputs)
    parts = sum(c.contribution for c in result.components
                if not math.isnan(c.contribution))

    assert result.total == pytest.approx(74.0, abs=0.1)
    assert parts == pytest.approx(33.3, abs=0.1)
    assert abs(result.total - parts) == pytest.approx(40.7, abs=0.1)


def test_v2_reports_the_effective_weight_it_actually_used():
    """With three of six components missing, the rest must carry the score."""
    result = score_v2(scenario("thin_history").inputs)
    assert sorted(result.missing_inputs) == ["behaviour", "goal_alignment", "risk"]

    scored = [c for c in result.components if not math.isnan(c.score)]
    # diversification 20 + concentration 15 + liquidity 10 = 45 raw weight.
    assert sum(c.weight for c in scored) == pytest.approx(45.0)
    # Renormalised: 20/45, 15/45, 10/45 of 100 = 44.44, 33.33, 22.22.
    effective = {c.name: c.inputs["effective_weight"] for c in scored}
    assert effective["diversification"] == pytest.approx(44.4444, abs=1e-3)
    assert effective["concentration"] == pytest.approx(33.3333, abs=1e-3)
    assert effective["liquidity"] == pytest.approx(22.2222, abs=1e-3)
    # The reported figures are rounded to four places for display, so they
    # sum to 99.9999. The contributions are computed from the unrounded
    # weights, which is why those sum exactly — see the test above.
    assert sum(effective.values()) == pytest.approx(100.0, abs=1e-3)

    # A missing component contributes nothing and says its weight was zero.
    for name in result.missing_inputs:
        component = _component(result, name)
        assert component.contribution == 0.0
        assert component.inputs["effective_weight"] == 0.0


# --------------------------------------------------------------------------
# Claim 3: diversification and concentration no longer measure the same thing
# --------------------------------------------------------------------------

def _dispersion_pair():
    """Two portfolios of identical breadth, differing only in weight spread."""
    base = scenario("textbook_balanced").inputs
    even = replace(base, hhi_normalized=0.04, top_1_weight=0.08, top_5_weight=0.34)
    uneven = replace(base, hhi_normalized=0.45, top_1_weight=0.44, top_5_weight=0.88)
    return even, uneven


def test_v2_diversification_ignores_weight_dispersion_entirely():
    """It must not move at all: breadth and independence are unchanged.

    Holdings, sectors, asset classes and correlation are identical across the
    pair. Anything diversification does here is concentration's job.
    """
    even, uneven = _dispersion_pair()

    before = _component(score_v2(even), "diversification").score
    after = _component(score_v2(uneven), "diversification").score
    assert before == pytest.approx(after, abs=1e-9)

    # Concentration, meanwhile, must react strongly: 98.33 -> 41.00.
    c_before = _component(score_v2(even), "concentration").score
    c_after = _component(score_v2(uneven), "concentration").score
    assert c_before - c_after == pytest.approx(57.33, abs=0.1)


def test_v1_diversification_double_counted_weight_dispersion():
    """v1 moved 13.67 points on a change concentration already captured.

    v1's diversification averaged an `evenness` sub-score computed from
    hhi_normalized — the same statistic its concentration component
    summarises — so weight dispersion drove two components that the UI
    presents as independent.
    """
    even, uneven = _dispersion_pair()

    before = _component(score_v1(even), "diversification").score
    after = _component(score_v1(uneven), "diversification").score
    assert before - after == pytest.approx(13.67, abs=0.05)

    assert "evenness" in _subscores(score_v1(even), "diversification")
    assert "evenness" not in _subscores(score_v2(even), "diversification")
    assert "evenness" in _subscores(score_v2(even), "concentration")


# --------------------------------------------------------------------------
# Claim 4: liquidity discriminates
# --------------------------------------------------------------------------

def test_v2_liquidity_separates_a_buffered_portfolio_from_an_unbuffered_one():
    """Measured: v1 moved 1.6 points on this pair, v2 moves 6.8.

    textbook_balanced holds 18% in cash and debt; diversified_no_buffer holds
    none and is otherwise the same portfolio. Having no buffer means meeting
    an unexpected need by selling growth assets, possibly after a fall — a
    material difference that v1's liquidity component could barely express.
    """
    buffered = scenario("textbook_balanced").inputs
    unbuffered = scenario("diversified_no_buffer").inputs

    v1_gap = score_v1(buffered).total - score_v1(unbuffered).total
    v2_gap = score_v2(buffered).total - score_v2(unbuffered).total

    assert v1_gap == pytest.approx(1.6, abs=0.2)
    assert v2_gap == pytest.approx(6.8, abs=0.2)
    assert v2_gap > 4 * v1_gap


def test_v2_liquidity_spans_a_usable_range_across_the_bank():
    """v1: 9.0 points of range, sd 2.7. v2: 54.5 points, sd 24.1.

    At weight 10, v1's liquidity could move the total by under one point, so
    the component was effectively decorative.
    """
    def spread(compute):
        values = [_component(compute(s.inputs), "liquidity").score for s in SCORABLE]
        values = [v for v in values if not math.isnan(v)]
        return max(values) - min(values), float(np.std(values))

    v1_range, v1_sd = spread(score_v1)
    v2_range, v2_sd = spread(score_v2)

    assert v1_range == pytest.approx(9.0, abs=0.5)
    assert v2_range == pytest.approx(54.5, abs=0.5)
    assert v2_sd > 5 * v1_sd


def test_liquidity_still_reports_the_honest_flat_rating_alongside_the_buffer():
    """The fix adds a measure; it does not re-scale the old one.

    v1's comment explains why stretching a 0.70-1.00 range across 0-100 would
    be dishonest, and that reasoning is preserved: the rating sub-score is
    still the raw blend times 100.
    """
    result = score_v2(scenario("concentrated_equity").inputs)  # 100% equity
    subscores = _subscores(result, "liquidity")
    assert subscores["rating"] == pytest.approx(70.0)   # all equity = 0.70
    assert subscores["buffer"] == pytest.approx(0.0)    # nothing in cash/debt


# --------------------------------------------------------------------------
# Claim 5: the drawdown score stops punishing the stated tolerance
# --------------------------------------------------------------------------

def test_a_drawdown_exactly_at_tolerance_scores_full_marks_in_v2():
    """A tolerance is a constraint, not a target. Staying inside it is success.

    A conservative investor tolerates a 12% drawdown. v1 scored a realised
    12% drawdown at 50/100 — penalising the investor for the outcome they
    themselves nominated as acceptable.
    """
    at_tolerance = replace(
        scenario("textbook_balanced").inputs,
        risk_tolerance="conservative",
        annualized_volatility=0.07,   # inside the 4%-10% conservative band
        max_drawdown=-0.12,           # exactly the conservative tolerance
    )

    assert _subscores(score_v1(at_tolerance), "risk")["drawdown"] == pytest.approx(50.0)
    assert _subscores(score_v2(at_tolerance), "risk")["drawdown"] == pytest.approx(100.0)


def test_a_drawdown_at_twice_tolerance_scores_zero():
    breached = replace(
        scenario("textbook_balanced").inputs,
        risk_tolerance="conservative",
        annualized_volatility=0.07,
        max_drawdown=-0.12 * DRAWDOWN_BREACH_MULTIPLE,
    )
    assert _subscores(score_v2(breached), "risk")["drawdown"] == pytest.approx(0.0)


def test_the_drawdown_score_decays_linearly_between_tolerance_and_breach():
    # Conservative tolerance 0.12, breach at 0.24. Halfway is 0.18, so 50.0.
    halfway = replace(
        scenario("textbook_balanced").inputs,
        risk_tolerance="conservative",
        annualized_volatility=0.07, max_drawdown=-0.18,
    )
    assert _subscores(score_v2(halfway), "risk")["drawdown"] == pytest.approx(50.0)


def test_overshooting_risk_is_penalised_harder_than_undershooting():
    """The asymmetry is deliberate and must survive the rework.

    Both scenarios are the textbook portfolio with only the tolerance and the
    two risk measures changed, so the gap is attributable to risk alone.
    """
    too_hot = score_v2(scenario("risk_mismatch_too_hot").inputs)
    too_cold = score_v2(scenario("risk_mismatch_too_cold").inputs)

    assert too_cold.total > too_hot.total
    assert _component(too_hot, "risk").score < _component(too_cold, "risk").score

    # The portfolio itself is unchanged, so these must not move.
    for name in ("diversification", "concentration", "liquidity", "behaviour"):
        assert _component(too_hot, name).score == pytest.approx(
            _component(too_cold, name).score
        ), f"{name} moved, so this pair no longer isolates risk"


# --------------------------------------------------------------------------
# Claim 6: the holdings curve implements the rationale v1 only described
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_holdings,expected", [
    (1, 0.0),      # knot
    (8, 50.0),     # knot: single-name risk stops dominating
    (25, 100.0),   # knot: marginal benefit of one more name is negligible
    (4, 21.4286),  # 1 + 3/7 of the way from 1 to 8 -> 3/7 * 50
    (16, 73.5294),  # 8/17 of the way from 8 to 25 -> 50 + 8/17 * 50
    (40, 100.0),   # beyond the plateau, still full marks
])
def test_the_holdings_curve_passes_through_its_stated_knots(n_holdings, expected):
    inputs = replace(scenario("textbook_balanced").inputs, n_holdings=n_holdings)
    assert _subscores(score_v2(inputs), "diversification")["holdings"] == pytest.approx(
        expected, abs=1e-3
    )


def test_v1_awarded_full_marks_at_twenty_holdings_not_twenty_five():
    """v1's formula and v1's comment disagreed; the comment lost.

    `_ramp(n, 1.0, 20.0)` reaches 100 at 20 holdings and gives a four-stock
    portfolio 15.8 — neither the 8 nor the 25 its comment described.
    """
    base = scenario("textbook_balanced").inputs
    at_20 = replace(base, n_holdings=20)
    at_4 = replace(base, n_holdings=4)

    assert _subscores(score_v1(at_20), "diversification")["holdings"] == pytest.approx(100.0)
    assert _subscores(score_v1(at_4), "diversification")["holdings"] == pytest.approx(
        15.7895, abs=1e-3
    )
    # v2 reserves full marks for 25 and is kinder to the small portfolio,
    # because the steep part of the curve is where the evidence puts it.
    assert _subscores(score_v2(at_20), "diversification")["holdings"] == pytest.approx(
        85.2941, abs=1e-3
    )
    assert _subscores(score_v2(at_4), "diversification")["holdings"] == pytest.approx(
        21.4286, abs=1e-3
    )


# --------------------------------------------------------------------------
# Claim 7: the narrative cannot contradict the score
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item", SCORABLE, ids=lambda s: s.name)
@pytest.mark.parametrize("component", ["diversification", "concentration", "behaviour"])
def test_a_reassuring_narrative_never_appears_under_a_weak_score(item, component):
    """v2 derives each reason from the sub-scores, so this holds by construction.

    The three components checked are the ones whose v1 prose used literals
    independent of their ramps.
    """
    result = score_v2(item.inputs)
    entry = _component(result, component)
    if math.isnan(entry.score):
        return

    reassuring = ("well distributed", "Steady behaviour",
                  "move largely independently", "are reasonable")
    if entry.score < 75.0:
        assert not any(phrase in entry.reason for phrase in reassuring), (
            f"{component} scored {entry.score:.1f} but reads: {entry.reason!r}"
        )


def test_v1_could_call_a_failing_concentration_reasonable():
    """The concrete contradiction, so the fix is anchored to a real case.

    v1's concentration prose triggered on top_1 > 0.30 and sector > 0.45,
    while its ramps turned at 0.50/0.10 and 0.70/0.25. A portfolio just under
    both prose thresholds therefore scored badly and was described as fine.
    """
    awkward = replace(
        scenario("textbook_balanced").inputs,
        top_1_weight=0.29,        # under the 0.30 prose threshold
        top_5_weight=0.95,        # but the top five are nearly everything
        max_sector_weight=0.44,   # under the 0.45 prose threshold
        hhi_normalized=0.30,
    )

    v1_entry = _component(score_v1(awkward), "concentration")
    assert v1_entry.score < 60.0
    assert "reasonable" in v1_entry.reason        # the contradiction

    v2_entry = _component(score_v2(awkward), "concentration")
    assert v2_entry.score < 60.0
    assert "reasonable" not in v2_entry.reason
    assert "well distributed" not in v2_entry.reason


# --------------------------------------------------------------------------
# Structural guarantees
# --------------------------------------------------------------------------

@pytest.mark.parametrize("item", SCENARIOS, ids=lambda s: s.name)
def test_v2_payloads_are_strict_json(item):
    import json
    json.dumps(score_v2(item.inputs).as_dict(), allow_nan=False)


@pytest.mark.parametrize("item", SCENARIOS, ids=lambda s: s.name)
def test_v2_never_invents_a_measurement_v1_did_not_have(item):
    """v2 may score more components than v1 only where it added a measure.

    Liquidity is the one component whose inputs changed, and it draws on
    asset_class_weights, which v1 also had. So the two versions must agree
    exactly on which components are unmeasurable.
    """
    assert sorted(score_v2(item.inputs).missing_inputs) == sorted(
        score_v1(item.inputs).missing_inputs
    )


@pytest.mark.parametrize("item", SCORABLE, ids=lambda s: s.name)
def test_no_component_score_leaves_the_zero_to_hundred_range(item):
    for component in score_v2(item.inputs).components:
        if not math.isnan(component.score):
            assert 0.0 <= component.score <= 100.0, component.name


# --------------------------------------------------------------------------
# Claim 8: sensitivity. Saturation is only a defect when it means a
# component *cannot* discriminate — not when a constraint is simply met.
# --------------------------------------------------------------------------

from wealthos_core.health import DRAWDOWN_TOLERANCE, sensitivity_analysis  # noqa: E402


def test_v2_has_no_saturated_component():
    """The real test of saturation, and the one v1 fails.

    Counting saturated *input nudges* is the wrong measure: v2 has more of
    them than v1 (34.5% against 30.2%), entirely because its drawdown score
    is deliberately flat inside the investor's tolerance. The question that
    matters is whether a component can distinguish portfolios at all. v1's
    liquidity cannot: nine points of range at weight 10 moves the total by
    under one point, so the component is decorative.
    """
    def ranges(compute):
        acc: dict[str, list[float]] = {}
        for item in SCORABLE:
            for component in compute(item.inputs).components:
                if not math.isnan(component.score):
                    acc.setdefault(component.name, []).append(component.score)
        return {k: max(v) - min(v) for k, v in acc.items()}

    v1_ranges = ranges(score_v1)
    v2_ranges = ranges(score_v2)

    assert v1_ranges["liquidity"] == pytest.approx(9.0, abs=0.5)
    assert [k for k, r in v1_ranges.items() if r < 10.0] == ["liquidity"]

    assert v2_ranges["liquidity"] == pytest.approx(54.5, abs=0.5)
    assert not [k for k, r in v2_ranges.items() if r < 10.0], (
        f"v2 components that cannot discriminate: "
        f"{[k for k, r in v2_ranges.items() if r < 10.0]}"
    )


@pytest.mark.parametrize("item", SCORABLE, ids=lambda s: s.name)
def test_drawdown_is_insensitive_only_where_that_is_the_intent(item):
    """Flat inside tolerance and flat past the breach; responsive between.

    Both plateaus are deliberate. Nudging an 18% drawdown to 19% when the
    investor tolerates 25% *should* change nothing — the constraint is still
    met. Nudging 58% to 59% when the breach point is 50% should also change
    nothing — it is already a total failure of the constraint. Only the band
    between tolerance and breach carries information, and that band is where
    the score must respond.
    """
    drawdown = item.inputs.max_drawdown
    if math.isnan(drawdown):
        pytest.skip("no drawdown measured for this scenario")

    tolerance = DRAWDOWN_TOLERANCE[item.inputs.risk_tolerance]
    breach = tolerance * DRAWDOWN_BREACH_MULTIPLE
    magnitude = abs(drawdown)
    on_a_plateau = magnitude <= tolerance or magnitude >= breach

    entries = {
        r["input"]: r
        for r in sensitivity_analysis(item.inputs, compute=score_v2)
    }
    if "max_drawdown" not in entries:
        pytest.skip("drawdown not perturbed for this scenario")

    assert entries["max_drawdown"]["saturated"] is on_a_plateau, (
        f"drawdown {magnitude:.2f} against tolerance {tolerance:.2f} and "
        f"breach {breach:.2f}: expected saturated={on_a_plateau}"
    )


def test_sensitivity_analysis_runs_against_either_methodology():
    """One implementation, two scorers. A second copy would drift from this one."""
    inputs = scenario("textbook_balanced").inputs

    v1_report = sensitivity_analysis(inputs)
    v2_report = sensitivity_analysis(inputs, compute=score_v2)

    assert v1_report and v2_report
    assert {r["input"] for r in v1_report} == {r["input"] for r in v2_report}
    # Default must stay v1, so existing callers are unaffected.
    assert sensitivity_analysis(inputs, compute=score_v1) == v1_report


def test_the_inputs_that_move_the_score_are_reported_in_order():
    report = sensitivity_analysis(
        scenario("concentrated_equity").inputs, compute=score_v2
    )
    swings = [r["swing"] for r in report]
    assert swings == sorted(swings, reverse=True)
    assert any(r["swing"] > 0 for r in report), "nothing moved the score at all"
