"""The Portfolio Health Score, version 2.

v1 lives on in ``health.py`` and both are computed on every request, so this
module has to justify itself against a working predecessor rather than
replace it by assertion. Six defects in v1 motivated it. Each is named below
with what changed and why, because a score nobody can interrogate is worth
less than a score that is slightly wrong.

**1. The holdings ramp disagreed with its own documentation.**
v1 scored holdings on ``_ramp(n, 1.0, 20.0)`` under a comment reading "below
8 holdings a portfolio carries substantial single-name risk; past about 25
the marginal benefit of one more name is small". Neither 8 nor 25 appears in
the formula. A linear 1-to-20 ramp gives a four-stock portfolio 15.8/100 and
awards full marks at 20. v2 implements the prose: 0 at one holding, 50 at
eight, 100 at twenty-five. The curve now says what the comment says.

**2. The drawdown multiplier punished the investor's own stated tolerance.**
v1 used ``_ramp(abs(dd), tolerated * 2, 0.0)``, so a conservative investor
whose portfolio fell exactly 12% — their declared limit — scored 50/100, and
one that never fell at all scored 100 only by never moving. The ``* 2`` was
the most arbitrary literal in the file. A drawdown tolerance is a constraint,
not a target: staying inside it is success, not a near miss. v2 awards full
marks at or inside the tolerance and decays to zero at twice it. Twice the
stated limit is a complete breach of the constraint, which is a defensible
reading of that multiplier; "your stated limit is half marks" was not.

**3. Liquidity could not discriminate.**
v1's liquidity score was the asset-class liquidity blend read directly onto
0-100. Because every asset in this universe is exchange-traded, the blend
spans 0.70 (all equity) to 1.00 (all cash), so the component varied by three
points out of a hundred at weight 10. v1's comment defends not re-scaling
that range, and it is right to: stretching a real 30-point spread across 100
manufactures precision. The error was the measure, not the scaling. v2 keeps
the blend and adds a second sub-score that genuinely varies — the share held
in cash and debt against a 10% buffer — so the component measures something
portfolios actually differ on. The weight stays at 10 because it now buys ten
real points rather than three.

**4. Diversification and concentration measured the same thing.**
v1's diversification included an ``evenness`` sub-score computed from
``hhi_normalized`` — the identical statistic its concentration component
summarises. Weight dispersion therefore drove roughly 23 of 100 points
through two components that looked independent. ``docs/EXPLAINER.md`` already
conceded the overlap. v2 splits them cleanly: diversification measures
breadth and independence (how many things, how unlike each other),
concentration measures weight dispersion (how unevenly distributed). HHI
moves to concentration, where it belongs, and nothing is counted twice.

**5. The narrative disagreed with the score.**
v1's reason strings tested their own thresholds — concentration's prose
triggered at 0.30 and 0.45 while its ramps turned at 0.50/0.10 and
0.70/0.25; behaviour's prose used 1.0 and 0.5 against ramps of 2.0 and 0.15.
A user could read "position sizes are reasonable" beneath a mediocre score.
v2 selects every narrative from the sub-scores themselves, so text and number
cannot drift apart: the disagreement is structurally impossible rather than
merely fixed.

**6. The contributions did not sum to the total.**
v1 computed each contribution as ``score / 100 * weight`` using raw weights,
while the total divided by the *renormalised* denominator. With a component
missing — no goals, say — the parts added to less than the whole, so the
decomposition the UI draws did not explain the number above it. v2
contributes against effective weights (raw weight renormalised over what
could be measured) and reports both, so the bars sum to the score and the
renormalisation is visible instead of implicit.

Weights are deliberately unchanged from v1. Fixing a measure is a better
answer than re-weighting around a broken one, and leaving them fixed means
any v1-to-v2 difference is attributable to the measurement changes above
rather than to tuning. ``scenarios.py`` and ``sensitivity_analysis`` are the
evidence that the components now discriminate; see
``tests/test_health_scenarios.py``.
"""

from __future__ import annotations

import numpy as np

from .constants import ASSET_CLASS_LIQUIDITY
from .health import (
    COMPONENT_WEIGHTS,
    DRAWDOWN_TOLERANCE,
    DEFAULT_VOLATILITY_BAND,
    RISK_TOLERANCE_VOLATILITY_BANDS,
    ComponentScore,
    HealthInputs,
    HealthScore,
    _band_score,
    _clean,
    _grade,
    _mean_available,
    _ramp,
)

__all__ = [
    "compute_health_score_v2",
    "COMPONENT_WEIGHTS_V2",
    "HOLDINGS_CURVE",
    "CASH_BUFFER_TARGET",
    "DRAWDOWN_BREACH_MULTIPLE",
]

# Unchanged from v1, deliberately. See the module docstring.
COMPONENT_WEIGHTS_V2 = dict(COMPONENT_WEIGHTS)

# (holdings, score) knots implementing the rationale v1 only described.
# 8 is where single-name risk stops dominating; 25 is where the marginal
# benefit of one more holding becomes negligible. Both numbers come from v1's
# own comment — v2's contribution is putting them in the formula.
HOLDINGS_CURVE: tuple[tuple[float, float], ...] = ((1.0, 0.0), (8.0, 50.0), (25.0, 100.0))

# Share of the portfolio in cash and debt that counts as a full buffer. Ten
# percent is a stated assumption, not a derived optimum: it is the round
# figure between the three-to-six months of expenses commonly advised and
# what a long-horizon investment portfolio can hold without materially
# dragging on return. It is reported with the score so a reader can disagree
# with it.
CASH_BUFFER_TARGET: float = 0.10

# A realised drawdown at this multiple of the stated tolerance scores zero:
# the constraint has not been stretched, it has been broken.
DRAWDOWN_BREACH_MULTIPLE: float = 2.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _curve_score(value: float, knots: tuple[tuple[float, float], ...]) -> float:
    """Piecewise-linear interpolation through ``(input, score)`` knots.

    A single ``_ramp`` can only express "bad here, good there". A curve can
    express a threshold *and* a plateau, which is what the holdings rationale
    actually claims and what a straight ramp could not represent.
    """
    if value is None or np.isnan(value):
        return float("nan")
    xs = [k[0] for k in knots]
    ys = [k[1] for k in knots]
    return float(np.interp(float(value), xs, ys))


def _drawdown_score(drawdown: float, tolerated: float) -> float:
    """Full marks inside the stated tolerance, zero at a multiple of it."""
    if drawdown is None or np.isnan(drawdown):
        return float("nan")
    magnitude = abs(float(drawdown))
    if magnitude <= tolerated:
        return 100.0
    breach = tolerated * DRAWDOWN_BREACH_MULTIPLE
    return _ramp(magnitude, breach, tolerated)


def _describe(subscores: dict[str, float], phrases: dict[str, str],
              fallback: str) -> str:
    """Narrate the weakest measured sub-score.

    Deriving the text from the scores is the whole point: v1 chose its
    wording with independent literals, so prose and number could and did
    disagree. Here the sentence is a function of the thing it describes.
    """
    measured = {k: v for k, v in subscores.items() if not np.isnan(v)}
    if not measured:
        return fallback
    weakest = min(measured, key=lambda k: measured[k])
    if measured[weakest] >= 75.0:
        return phrases["strong"]
    return phrases.get(weakest, phrases["strong"])


def _component(name: str, score: float, inputs: dict, reason: str) -> ComponentScore:
    """Build a ComponentScore. Contribution is filled in by the aggregator.

    v1 computed contribution here, against the raw weight, which is why the
    contributions did not sum to the total. It cannot be known until we know
    which components were measurable, so it is no longer computed here.
    """
    return ComponentScore(
        name=name,
        score=score,
        weight=COMPONENT_WEIGHTS_V2[name],
        contribution=float("nan"),
        inputs=inputs,
        reason=reason,
    )


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

def _score_diversification(data: HealthInputs) -> ComponentScore:
    """Breadth and independence. Weight dispersion belongs to concentration."""
    if not data.n_holdings:
        return _component(
            "diversification", float("nan"), {"n_holdings": 0},
            "The portfolio holds nothing, so diversification cannot be assessed.",
        )

    holdings = _curve_score(float(data.n_holdings), HOLDINGS_CURVE)
    sectors = _ramp(float(data.n_sectors), 1.0, 8.0)
    classes = _ramp(float(data.n_asset_classes), 1.0, 4.0)
    independence = _ramp(data.average_pairwise_correlation, 0.9, 0.2)

    subscores = {"holdings": holdings, "sectors": sectors,
                 "asset_classes": classes, "independence": independence}
    score = _mean_available(list(subscores.values()))

    reason = _describe(subscores, {
        "strong": (
            f"Spread across {data.n_holdings} holdings in {data.n_sectors} sectors "
            f"and {data.n_asset_classes} asset classes, with holdings that move "
            "largely independently."
        ),
        "holdings": (
            f"Only {data.n_holdings} holdings, so a single company's fortunes move "
            "a large share of the portfolio. Single-name risk falls steeply up to "
            "about eight holdings and keeps improving to roughly twenty-five."
        ),
        "sectors": (
            f"The {data.n_holdings} holdings sit in only {data.n_sectors} sectors, "
            "so the portfolio is less diversified than the holding count suggests."
        ),
        "asset_classes": (
            f"Everything is in {data.n_asset_classes} asset "
            f"{'class' if data.n_asset_classes == 1 else 'classes'}, so there is "
            "little to offset a fall in that market."
        ),
        "independence": (
            f"The holdings have an average pairwise correlation of "
            f"{data.average_pairwise_correlation:.2f}: they tend to move together, "
            "so the holding count overstates the real diversification."
        ),
    }, "Not enough holdings data to assess diversification.")

    return _component("diversification", score, {
        "n_holdings": data.n_holdings,
        "n_sectors": data.n_sectors,
        "n_asset_classes": data.n_asset_classes,
        "average_pairwise_correlation": _clean(data.average_pairwise_correlation),
        "subscores": {k: _clean(v) for k, v in subscores.items()},
        "holdings_curve": [list(k) for k in HOLDINGS_CURVE],
    }, reason)


def _score_risk(data: HealthInputs) -> ComponentScore:
    tolerance = (data.risk_tolerance or "moderate").lower()
    low, high = RISK_TOLERANCE_VOLATILITY_BANDS.get(tolerance, DEFAULT_VOLATILITY_BAND)
    tolerated = DRAWDOWN_TOLERANCE.get(tolerance, 0.25)

    volatility = _band_score(data.annualized_volatility, low, high)
    drawdown = _drawdown_score(data.max_drawdown, tolerated)

    subscores = {"volatility": volatility, "drawdown": drawdown}
    score = _mean_available(list(subscores.values()))

    vol = data.annualized_volatility
    if np.isnan(vol) and np.isnan(drawdown):
        reason = "Not enough price history to measure portfolio risk."
    elif not np.isnan(vol) and vol > high:
        reason = (
            f"Volatility of {vol:.1%} is above the {low:.0%}-{high:.0%} range "
            f"typical of a {tolerance} profile, so the portfolio carries more "
            "risk than the stated tolerance implies."
        )
    elif not np.isnan(vol) and vol < low:
        reason = (
            f"Volatility of {vol:.1%} is below the {low:.0%}-{high:.0%} range "
            f"for a {tolerance} profile. The portfolio is calmer than the stated "
            "tolerance allows for, which may limit long-term growth."
        )
    elif not np.isnan(drawdown) and drawdown < 100.0:
        reason = (
            f"Volatility sits inside the {low:.0%}-{high:.0%} range for a "
            f"{tolerance} profile, but the worst drawdown of "
            f"{abs(data.max_drawdown):.1%} exceeds the {tolerated:.0%} that "
            "profile tolerates."
        )
    else:
        reason = (
            f"Volatility of {vol:.1%} sits within the {low:.0%}-{high:.0%} range "
            f"expected for a {tolerance} profile, and the worst drawdown of "
            f"{abs(data.max_drawdown):.1%} is inside the {tolerated:.0%} it tolerates."
        )

    return _component("risk", score, {
        "annualized_volatility": _clean(data.annualized_volatility),
        "max_drawdown": _clean(data.max_drawdown),
        "risk_tolerance": tolerance,
        "target_volatility_band": [low, high],
        "tolerated_drawdown": tolerated,
        "drawdown_breach_at": tolerated * DRAWDOWN_BREACH_MULTIPLE,
        "subscores": {k: _clean(v) for k, v in subscores.items()},
    }, reason)


def _score_concentration(data: HealthInputs) -> ComponentScore:
    """Weight dispersion, now including the HHI that v1 double-counted."""
    top_1 = _ramp(data.top_1_weight, 0.50, 0.10)
    top_5 = _ramp(data.top_5_weight, 1.00, 0.50)
    sector = _ramp(data.max_sector_weight, 0.70, 0.25)
    evenness = _ramp(data.hhi_normalized, 0.6, 0.0)

    subscores = {"top_1": top_1, "top_5": top_5,
                 "sector": sector, "evenness": evenness}
    score = _mean_available(list(subscores.values()))

    reason = _describe(subscores, {
        "strong": (
            f"Position sizes are well distributed: the largest holding is "
            f"{data.top_1_weight:.1%} and the top five are {data.top_5_weight:.1%}."
        ),
        "top_1": (
            f"The largest position is {data.top_1_weight:.1%} of the portfolio, so "
            "one holding drives much of the outcome."
        ),
        "top_5": (
            f"The top five holdings are {data.top_5_weight:.1%} of the portfolio, so "
            "a small number of positions determine most of its movement."
        ),
        "sector": (
            f"One sector accounts for {data.max_sector_weight:.1%} of the portfolio, "
            "concentrating exposure to events affecting that sector."
        ),
        "evenness": (
            f"The weights are uneven (normalised HHI {data.hhi_normalized:.2f}), so "
            "the portfolio behaves like fewer holdings than it contains."
        ),
    }, "Not enough holdings data to assess concentration.")

    return _component("concentration", score, {
        "top_1_weight": _clean(data.top_1_weight),
        "top_5_weight": _clean(data.top_5_weight),
        "max_sector_weight": _clean(data.max_sector_weight),
        "hhi_normalized": _clean(data.hhi_normalized),
        "subscores": {k: _clean(v) for k, v in subscores.items()},
    }, reason)


def _score_liquidity(data: HealthInputs) -> ComponentScore:
    weights = data.asset_class_weights or {}
    total = sum(weights.values())

    if total <= 0:
        return _component("liquidity", float("nan"),
                          {"asset_class_weights": {}},
                          "No holdings to assess liquidity.")

    shares = {str(k).lower(): v / total for k, v in weights.items()}
    rating = sum(share * ASSET_CLASS_LIQUIDITY.get(name, 0.5)
                 for name, share in shares.items())
    # Reported directly on 0-100, exactly as v1 did, for the reason v1 gives:
    # the achievable range is narrow because the universe is uniformly liquid,
    # and re-scaling it would invent precision.
    rating_score = float(rating * 100.0)

    buffer_share = shares.get("cash", 0.0) + shares.get("debt", 0.0)
    buffer_score = _ramp(buffer_share, 0.0, CASH_BUFFER_TARGET)

    subscores = {"rating": rating_score, "buffer": buffer_score}
    score = _mean_available(list(subscores.values()))

    if buffer_score >= 100.0:
        reason = (
            f"{buffer_share:.1%} sits in cash and debt, at or above the "
            f"{CASH_BUFFER_TARGET:.0%} buffer this score looks for, and the "
            f"weighted liquidity rating is {rating:.2f} where cash is 1.00."
        )
    elif buffer_share <= 0.0:
        reason = (
            "Nothing is held in cash or debt, so meeting an unexpected need "
            "means selling growth assets, possibly after a fall. The holdings "
            "themselves are liquid — the weighted rating is "
            f"{rating:.2f} — but a buffer is what makes that liquidity usable."
        )
    else:
        reason = (
            f"{buffer_share:.1%} sits in cash and debt against the "
            f"{CASH_BUFFER_TARGET:.0%} buffer this score looks for. The holdings "
            f"are liquid in themselves (weighted rating {rating:.2f})."
        )

    return _component("liquidity", score, {
        "asset_class_weights": {k: round(float(v), 4) for k, v in weights.items()},
        "weighted_liquidity": _clean(rating),
        "buffer_share": _clean(buffer_share),
        "buffer_target": CASH_BUFFER_TARGET,
        "subscores": {k: _clean(v) for k, v in subscores.items()},
    }, reason)


def _score_goal_alignment(data: HealthInputs) -> ComponentScore:
    """Unchanged from v1 in substance; no defect was found here."""
    if not data.has_goals:
        return _component("goal_alignment", float("nan"), {"has_goals": False},
                          "No goals have been set, so this component cannot be "
                          "scored. Adding a goal lets the platform judge the "
                          "portfolio against what it is actually for.")

    progress = _ramp(data.goal_progress_ratio, 0.4, 1.2)
    funding = _ramp(data.goal_funding_ratio, 0.4, 1.1)
    subscores = {"progress": progress, "funding": funding}
    score = _mean_available(list(subscores.values()))

    if np.isnan(score):
        reason = "Goals are set but there is not enough data to project progress."
    elif not np.isnan(data.goal_funding_ratio) and data.goal_funding_ratio >= 1.0:
        reason = ("On the stated assumptions, the goals are projected to reach "
                  f"{data.goal_funding_ratio:.0%} of their targets.")
    else:
        reason = ("On the stated assumptions, the goals are projected to reach "
                  f"{data.goal_funding_ratio:.0%} of their targets, leaving a "
                  "shortfall. Contributions, target dates and expected returns "
                  "all affect this.")

    return _component("goal_alignment", score, {
        "has_goals": True,
        "goal_progress_ratio": _clean(data.goal_progress_ratio),
        "goal_funding_ratio": _clean(data.goal_funding_ratio),
        "subscores": {k: _clean(v) for k, v in subscores.items()},
    }, reason)


def _score_behaviour(data: HealthInputs) -> ComponentScore:
    turnover = _ramp(data.annual_turnover, 2.0, 0.15)
    consistency = _ramp(data.contribution_consistency, 0.0, 1.0)
    drift = _ramp(data.allocation_drift, 0.60, 0.05)

    subscores = {"turnover": turnover, "consistency": consistency, "drift": drift}
    score = _mean_available(list(subscores.values()))

    reason = _describe(subscores, {
        "strong": (
            f"Steady behaviour: {data.annual_turnover:.0%} annual turnover and "
            f"contributions in {data.contribution_consistency:.0%} of months."
        ),
        "turnover": (
            f"Annual turnover of {data.annual_turnover:.0%} means a large share of "
            "the portfolio is replaced each year, incurring costs that a "
            "long-horizon portfolio rarely recovers."
        ),
        "consistency": (
            f"Contributions were made in {data.contribution_consistency:.0%} of "
            "months. Irregular investing makes goal projections less reliable."
        ),
        "drift": (
            f"The asset allocation moved by {data.allocation_drift:.0%} over a year, "
            "so the portfolio's risk profile is not the one it started with."
        ),
    }, "Not enough transaction history to assess investing behaviour.")

    return _component("behaviour", score, {
        "annual_turnover": _clean(data.annual_turnover),
        "contribution_consistency": _clean(data.contribution_consistency),
        "allocation_drift": _clean(data.allocation_drift),
        "subscores": {k: _clean(v) for k, v in subscores.items()},
    }, reason)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def compute_health_score_v2(data: HealthInputs) -> HealthScore:
    """Score a portfolio, returning the total and its full derivation.

    Contributions are computed here, against effective weights, so that they
    sum to the total. In v1 they were computed per component against raw
    weights while the total used the renormalised denominator, so with any
    component missing the decomposition did not add up to the number it was
    decomposing.
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
        for component in components:
            component.contribution = 0.0
        return HealthScore(
            total=float("nan"), grade="Unknown", components=components,
            summary="Not enough data to score this portfolio.",
            missing_inputs=missing,
        )

    available_weight = sum(c.weight for c in scored)
    total = sum(c.score * c.weight for c in scored) / available_weight

    for component in components:
        if np.isnan(component.score):
            component.contribution = 0.0
            component.inputs["effective_weight"] = 0.0
        else:
            effective = component.weight / available_weight * 100.0
            component.contribution = component.score / 100.0 * effective
            component.inputs["effective_weight"] = round(effective, 4)

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
            f"{', '.join(m.replace('_', ' ') for m in missing)} could not be "
            "measured, and the remaining weights were renormalised."
        )

    return HealthScore(
        total=total, grade=_grade(total), components=components,
        summary=summary, missing_inputs=missing,
    )
