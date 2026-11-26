"""Every payload the platform serialises must be valid, strict JSON.

The analytics library returns NaN rather than raising when an input is too
thin to measure. That convention is deliberate, but NaN is not a JSON value,
and each serialiser in the stack handles it differently: ``json.dumps``
writes a bare ``NaN`` token, Starlette's ``JSONResponse`` raises, and
pydantic writes ``null``. These tests fix the boundary so the three agree.

Expected values are derived in the comment above each assertion.
"""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from wealthos_core.goals import project_goal
from wealthos_core.health import HealthInputs, compute_health_score
from wealthos_core.jsonsafe import json_safe, round_or_none


def _strict(payload: object) -> str:
    """Serialise, refusing the non-standard NaN/Infinity tokens json allows."""
    return json.dumps(payload, allow_nan=False)


# --------------------------------------------------------------------------
# The helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_safe_rejects_every_non_finite_float(value):
    assert json_safe(value) is None


@pytest.mark.parametrize("value", [0.0, -0.0, 1.5, -2.25, 1e308, 0, -7])
def test_json_safe_passes_finite_numbers_through_unchanged(value):
    # 0.0 in particular: a falsy-but-valid measurement. An `or` guard would
    # discard it, which is the bug this helper exists to prevent.
    assert json_safe(value) == value


@pytest.mark.parametrize("value", ["text", None, True, False, [1], {"a": 1}])
def test_json_safe_leaves_non_numeric_values_alone(value):
    # bools are ints in Python; coercing True to 1.0 would corrupt a payload.
    assert json_safe(value) is value


def test_round_or_none_rounds_a_real_number():
    # 93.10462 to one decimal is 93.1.
    assert round_or_none(93.10462, 1) == 93.1


def test_round_or_none_returns_none_for_nan():
    # round(nan, 1) is nan, not an error, so plain round() is no protection.
    assert math.isnan(round(float("nan"), 1))
    assert round_or_none(float("nan"), 1) is None


def test_round_or_none_returns_none_for_infinity():
    assert round_or_none(float("inf"), 2) is None


def test_round_or_none_preserves_none():
    assert round_or_none(None, 2) is None


# --------------------------------------------------------------------------
# HealthScore.as_dict — the payload behind GET /api/v1/health-score
# --------------------------------------------------------------------------

def test_unscorable_portfolio_serialises_as_strict_json():
    """An account with nothing in it is the worst case: every field is NaN."""
    payload = compute_health_score(HealthInputs()).as_dict()

    assert payload["total"] is None
    assert payload["grade"] == "Unknown"
    assert [c["score"] for c in payload["components"]] == [None] * 6
    # `contribution` was already safe: every scorer sets it to a literal 0.0
    # when its score is NaN, rather than deriving it from the NaN. Whether a
    # missing component *should* read 0.0 — indistinguishable from one that
    # genuinely scored nothing — is a separate question, left to the
    # Health Score rework.
    assert [c["contribution"] for c in payload["components"]] == [0.0] * 6

    _strict(payload)  # raises ValueError if any NaN survived


def test_scored_portfolio_still_reports_numbers():
    """The null-for-NaN rule must not blank out a real score."""
    payload = compute_health_score(
        HealthInputs(asset_class_weights={"equity": 0.6, "debt": 0.4}, n_holdings=12)
    ).as_dict()

    assert isinstance(payload["total"], float)
    assert payload["grade"] != "Unknown"
    _strict(payload)


def test_partially_scorable_portfolio_nulls_only_the_missing_components():
    """Mixed case: some components measurable, some not."""
    payload = compute_health_score(
        HealthInputs(asset_class_weights={"equity": 1.0}, n_holdings=4)
    ).as_dict()

    by_name = {c["name"]: c for c in payload["components"]}
    scored = [n for n, c in by_name.items() if c["score"] is not None]
    nulled = [n for n, c in by_name.items() if c["score"] is None]

    assert scored, "nothing scored, so this is not the mixed case"
    assert nulled == payload["missing_inputs"]
    _strict(payload)


# --------------------------------------------------------------------------
# GoalProjection.as_dict
# --------------------------------------------------------------------------

def test_goal_with_a_non_positive_target_serialises_as_strict_json():
    """project_goal leaves funding_ratio NaN when the target is not positive.

    The API rejects such a goal at the schema (`target_amount: Field(gt=0)`),
    so this guards direct library callers — the ML pipelines write their
    reports with json.dumps, which would emit a bare NaN token.
    """
    payload = project_goal(
        goal_id=1, name="Zero target", target_amount=0.0, current_amount=1000.0,
        monthly_contribution=100.0, target_date=date(2030, 1, 1),
        expected_annual_return=0.10, as_of=date(2026, 1, 1),
    ).as_dict()

    assert payload["funding_ratio"] is None
    _strict(payload)


def test_ordinary_goal_reports_its_real_funding_ratio():
    payload = project_goal(
        goal_id=1, name="House", target_amount=1_000_000.0,
        current_amount=200_000.0, monthly_contribution=10_000.0,
        target_date=date(2031, 1, 1), expected_annual_return=0.10,
        as_of=date(2026, 1, 1),
    ).as_dict()

    assert isinstance(payload["funding_ratio"], float)
    assert payload["funding_ratio"] > 0
    _strict(payload)
