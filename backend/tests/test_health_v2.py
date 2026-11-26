"""The health-score endpoint with two methodologies, and allocation drift."""

from __future__ import annotations

import json
import math

import pytest


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
# Both methodologies, always
# --------------------------------------------------------------------------

def test_both_versions_are_returned_whichever_is_selected(client, funded):
    """A changed score with the old one hidden is a score nobody can check."""
    body = client.get("/api/v1/health-score", headers=funded).json()

    assert set(body["versions"]) == {"v1", "v2"}
    for version in ("v1", "v2"):
        entry = body["versions"][version]
        assert isinstance(entry["total"], float)
        assert entry["grade"]
        assert len(entry["components"]) == 6
        assert entry["methodology"]


def test_v1_is_the_default_so_existing_clients_are_unaffected(client, funded):
    body = client.get("/api/v1/health-score", headers=funded).json()

    assert body["methodology_version"] == "v1"
    assert body["total"] == body["versions"]["v1"]["total"]
    assert body["grade"] == body["versions"]["v1"]["grade"]


def test_the_methodology_flag_swaps_the_headline_only(client, funded):
    v1 = client.get("/api/v1/health-score?methodology=v1", headers=funded).json()
    v2 = client.get("/api/v1/health-score?methodology=v2", headers=funded).json()

    assert v2["methodology_version"] == "v2"
    assert v2["total"] == v2["versions"]["v2"]["total"]

    # The `versions` block is identical either way: the flag chooses which
    # version is promoted, never which ones are computed.
    assert v1["versions"] == v2["versions"]


def test_an_unknown_methodology_is_rejected_at_the_boundary(client, funded):
    response = client.get("/api/v1/health-score?methodology=v3", headers=funded)
    assert response.status_code == 422


def test_the_comparison_block_states_what_differs(client, funded):
    comparison = client.get("/api/v1/health-score", headers=funded).json()["version_comparison"]

    assert comparison["v1_total"] is not None
    assert comparison["v2_total"] is not None
    assert comparison["difference"] == pytest.approx(
        round(comparison["v2_total"] - comparison["v1_total"], 2), abs=0.011
    )
    assert "re-weighting" in comparison["note"]


def test_the_weights_are_identical_between_versions(client, funded):
    """The claim the comparison rests on: only measurements changed."""
    body = client.get("/api/v1/health-score", headers=funded).json()

    v1_weights = {c["name"]: c["weight"] for c in body["versions"]["v1"]["components"]}
    v2_weights = {c["name"]: c["weight"] for c in body["versions"]["v2"]["components"]}
    assert v1_weights == v2_weights
    assert sum(v1_weights.values()) == pytest.approx(100.0)


def test_v2_contributions_sum_to_its_total_over_the_api(client, funded):
    body = client.get("/api/v1/health-score?methodology=v2", headers=funded).json()

    parts = sum(c["contribution"] for c in body["components"]
                if c["contribution"] is not None)
    assert parts == pytest.approx(body["total"], abs=0.05)


def test_both_versions_serialise_as_strict_json_for_an_empty_portfolio(client, auth):
    body = client.get("/api/v1/health-score", headers=auth).json()

    assert body["total"] is None
    assert body["versions"]["v1"]["total"] is None
    assert body["versions"]["v2"]["total"] is None
    assert body["version_comparison"]["difference"] is None
    json.dumps(body, allow_nan=False)


def test_sensitivity_still_works_alongside_both_versions(client, funded):
    body = client.get("/api/v1/health-score?sensitivity=true", headers=funded).json()

    assert body["sensitivity"], "sensitivity requested but not returned"
    for entry in body["sensitivity"]:
        assert {"input", "swing", "direction", "saturated"} <= set(entry)


# --------------------------------------------------------------------------
# allocation_drift: hardcoded NaN until Phase 2
# --------------------------------------------------------------------------

def test_allocation_drift_is_measured_and_its_source_named(client, funded):
    """Behaviour used to score on two of three sub-scores, always.

    `allocation_drift` was `float("nan")` with a comment deferring it to a
    phase that had not happened, so the third sub-score never existed.
    """
    body = client.get("/api/v1/health-score", headers=funded).json()
    behaviour = body["context"]["behaviour"]

    assert "allocation_drift" in behaviour
    assert "allocation_drift_source" in behaviour
    assert behaviour["allocation_drift_source"] in {
        "transactions", "price_drift", "unavailable",
    }


def test_the_drift_source_is_reported_honestly(client, funded):
    """Price-driven drift and investor-driven drift are different quantities.

    `monthly_history` reconstructs the path with today's quantities held
    constant, so it can only see drift caused by prices moving. Labelling
    that as observed behaviour would be a fabrication; the label is the
    whole point.
    """
    behaviour = client.get("/api/v1/health-score", headers=funded).json()["context"]["behaviour"]

    source = behaviour["allocation_drift_source"]
    drift = behaviour["allocation_drift"]

    if source == "unavailable":
        assert drift is None or math.isnan(drift)
    else:
        assert drift is not None and drift >= 0.0


def test_an_empty_account_reports_drift_unavailable_rather_than_zero(client, auth):
    behaviour = client.get("/api/v1/health-score", headers=auth).json()["context"]["behaviour"]

    assert behaviour["allocation_drift_source"] == "unavailable"
    assert behaviour["n_transactions"] == 0


def test_drift_is_a_non_negative_annualised_fraction(client, funded):
    """It is a share of the portfolio reallocated per year, so it cannot be negative.

    The L1 distance is halved so that moving 10% from equity to debt reads as
    0.10 rather than 0.20 -- the intuitive answer to "how much moved".
    """
    behaviour = client.get("/api/v1/health-score", headers=funded).json()["context"]["behaviour"]
    drift = behaviour["allocation_drift"]

    if drift is not None and not math.isnan(drift):
        assert drift >= 0.0
        assert drift < 24.0, "a drift above 2400%/yr means the halving or annualisation is wrong"
