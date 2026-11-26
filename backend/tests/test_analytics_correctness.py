"""Phase 1 fixes to the service layer, each pinned against its defect.

Every test here names the wrong behaviour it prevents, so a regression reads
as a specific mistake rather than an unexplained failure.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from wealthos_core import BENCHMARK_SYMBOL, MIN_OBSERVATIONS_FOR_RISK
from app.ml_runtime.features import _finite
from app.services.health_service import _or_nan


@pytest.fixture
def funded(client, auth):
    """A diversified portfolio across three asset classes."""
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000),
        ("INFY", 15, 1400), ("GOLDBEES", 500, 50), ("DEBT", 400, 50),
    ]:
        response = client.post("/api/v1/portfolio/holdings", headers=auth,
                               json={"symbol": symbol, "quantity": quantity,
                                     "average_price": price})
        assert response.status_code == 201
    return auth


# --------------------------------------------------------------------------
# A correlation of exactly 0.0 is a measurement, not a missing value
# --------------------------------------------------------------------------

def test_zero_correlation_survives_as_a_measurement():
    """`x or float("nan")` discarded 0.0, because 0.0 is falsy.

    Mean pairwise correlation of 0.0 means the holdings move independently —
    the best possible result for the diversification component. The old
    expression replaced it with NaN, so the one portfolio that most deserved
    credit for diversification had that term dropped as unmeasurable.
    """
    assert _or_nan(0.0) == 0.0
    assert not math.isnan(_or_nan(0.0))


def test_absent_correlation_is_still_nan():
    # None genuinely means "fewer than two priced holdings, nothing to
    # correlate", which must stay distinguishable from a measured zero.
    assert math.isnan(_or_nan(None))


@pytest.mark.parametrize("value", [-1.0, -0.42, 0.0, 0.37, 1.0])
def test_every_valid_correlation_passes_through_unchanged(value):
    assert _or_nan(value) == value


def test_the_old_expression_is_the_bug_being_prevented():
    """Demonstrates the defect directly, so the fix cannot be reverted quietly."""
    assert math.isnan(0.0 or float("nan"))      # the old code path
    assert _or_nan(0.0) == 0.0                   # the new one


# --------------------------------------------------------------------------
# `x or 0.0` does not substitute for NaN, because NaN is truthy
# --------------------------------------------------------------------------

def test_nan_feature_falls_back_to_zero():
    """A one-row history makes Series.std() NaN at ddof=1, so this is reachable."""
    single_snapshot = pd.Series([0.6])
    assert math.isnan(single_snapshot.std())
    assert _finite(single_snapshot.std()) == 0.0


def test_the_old_or_expression_let_nan_through():
    # float('nan') or 0.0 evaluates to nan: NaN is truthy, so the guard that
    # these two feature lines appeared to have was never active.
    assert math.isnan(float("nan") or 0.0)


@pytest.mark.parametrize("value", [0.0, 0.0312, -0.5, 12.0])
def test_finite_values_are_untouched(value):
    assert _finite(value) == value


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_values_become_the_default(value):
    assert _finite(value) == 0.0
    assert _finite(value, default=-1.0) == -1.0


def test_no_feature_vector_contains_a_non_finite_value():
    """The guarantee that matters: nothing non-finite reaches a model.

    A NaN in the feature vector does not raise — scikit-learn's K-Means and
    the autoencoder both propagate it — so the cluster assignment silently
    becomes meaningless rather than failing. A single-month history is the
    realistic trigger: a new user with one snapshot.
    """
    from app.ml_runtime.features import behavioural_profile

    one_month = pd.DataFrame({
        "equity_allocation": [0.6], "etf_allocation": [0.2],
        "gold_allocation": [0.1], "debt_allocation": [0.1],
        "cash_allocation": [0.0], "turnover": [0.3], "n_trades": [2.0],
        "volatility": [np.nan], "max_drawdown": [-0.2], "hhi": [0.3],
        "top_holding_weight": [0.4], "n_holdings": [8.0],
        "net_contribution": [5000.0], "total_value": [100000.0],
    })

    profile = behavioural_profile(one_month, user=None)
    assert profile, "expected a feature vector for a one-row history"

    offenders = {k: v for k, v in profile.items()
                 if isinstance(v, float) and not math.isfinite(v)}
    assert not offenders, f"non-finite features reaching the model: {offenders}"

    # The two that used to be NaN here, specifically.
    assert profile["allocation_volatility"] == 0.0   # std of one row
    assert profile["portfolio_volatility"] == 0.0    # mean of an all-NaN column


# --------------------------------------------------------------------------
# The benchmark symbol, end to end
# --------------------------------------------------------------------------

def test_risk_service_uses_the_shared_benchmark_constant():
    from app.services import risk_service

    # Imported, not redefined: the module-level name must be the same object
    # the library exports.
    assert risk_service.BENCHMARK_SYMBOL is BENCHMARK_SYMBOL


def test_the_benchmark_asset_exists_in_the_test_fixture(seeded_db):
    """If the constant and the seeded symbol disagree, beta is silently NaN."""
    from app.models import Asset

    found = seeded_db.query(Asset).filter(Asset.symbol == BENCHMARK_SYMBOL).one_or_none()
    assert found is not None, (
        f"no asset with symbol {BENCHMARK_SYMBOL!r}; the benchmark lookup "
        "would return an empty series and beta/alpha would be NaN"
    )


def test_analytics_reports_the_benchmark_and_its_reliability(client, funded):
    body = client.get("/api/v1/portfolio/analytics", headers=funded).json()
    assumptions = body["assumptions"]

    assert assumptions["benchmark"] == BENCHMARK_SYMBOL
    assert assumptions["benchmark_name"] == "NIFTY 50"
    assert assumptions["minimum_observations"] == MIN_OBSERVATIONS_FOR_RISK
    assert assumptions["window_reliability"] in {"provisional", "full"}

    # A window at or above a full trading year must not be called provisional.
    if assumptions["observations"] >= 252:
        assert assumptions["window_reliability"] == "full"
    else:
        assert assumptions["window_reliability"] == "provisional"


# --------------------------------------------------------------------------
# Strict JSON across the whole API surface
# --------------------------------------------------------------------------

def test_health_score_response_is_strict_json_for_an_empty_portfolio(client, auth):
    """The response pydantic rescues today, and would 500 without it.

    Starlette's JSONResponse sets allow_nan=False. The route is annotated
    `-> dict`, so FastAPI serialises through pydantic, which writes null for
    NaN. That is the only reason an empty portfolio does not return a 500 —
    an accident of the annotation, not a decision. With the NaN removed at
    the source, the response no longer depends on it.
    """
    response = client.get("/api/v1/health-score", headers=auth)
    assert response.status_code == 200

    payload = response.json()
    assert payload["total"] is None
    assert payload["grade"] == "Unknown"

    json.dumps(payload, allow_nan=False)  # raises if a NaN survived
