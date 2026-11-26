"""Goals and Health Score endpoints."""

from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture
def funded(client, auth):
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000),
        ("INFY", 15, 1400), ("GOLDBEES", 500, 50), ("DEBT", 400, 50),
    ]:
        client.post("/api/v1/portfolio/holdings", headers=auth,
                    json={"symbol": symbol, "quantity": quantity, "average_price": price})
    return auth


def _goal(**overrides) -> dict:
    payload = {
        "name": "Retirement", "goal_type": "retirement",
        "target_amount": 10_000_000, "target_date": "2046-01-01",
        "monthly_contribution": 30_000, "priority": 1,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Goals CRUD
# --------------------------------------------------------------------------

def test_goal_can_be_created_and_listed(client, auth):
    created = client.post("/api/v1/goals", headers=auth, json=_goal())
    assert created.status_code == 201
    assert created.json()["name"] == "Retirement"

    listed = client.get("/api/v1/goals", headers=auth).json()
    assert len(listed) == 1


def test_a_goal_in_the_past_is_rejected(client, auth):
    response = client.post("/api/v1/goals", headers=auth,
                           json=_goal(target_date="2020-01-01"))
    assert response.status_code == 422


def test_invalid_goal_values_are_rejected(client, auth):
    assert client.post("/api/v1/goals", headers=auth,
                       json=_goal(target_amount=-100)).status_code == 422
    assert client.post("/api/v1/goals", headers=auth,
                       json=_goal(goal_type="yacht")).status_code == 422
    assert client.post("/api/v1/goals", headers=auth,
                       json=_goal(priority=99)).status_code == 422


def test_goal_progress_fraction_is_capped_at_one(client, auth):
    created = client.post("/api/v1/goals", headers=auth, json=_goal(
        target_amount=100_000, current_amount=250_000
    )).json()
    assert created["progress_fraction"] == pytest.approx(1.0)


def test_goal_can_be_updated_and_deleted(client, auth):
    goal_id = client.post("/api/v1/goals", headers=auth, json=_goal()).json()["id"]

    updated = client.patch(f"/api/v1/goals/{goal_id}", headers=auth,
                           json={"monthly_contribution": 50_000, "status": "achieved"})
    assert updated.status_code == 200
    assert updated.json()["monthly_contribution"] == pytest.approx(50_000)
    assert updated.json()["status"] == "achieved"

    assert client.delete(f"/api/v1/goals/{goal_id}", headers=auth).status_code == 204
    assert client.get("/api/v1/goals", headers=auth).json() == []


def test_goals_are_private_to_their_owner(client, auth, second_user):
    goal_id = client.post("/api/v1/goals", headers=auth, json=_goal()).json()["id"]
    other = second_user["headers"]

    assert client.get("/api/v1/goals", headers=other).json() == []
    assert client.get(f"/api/v1/goals/{goal_id}", headers=other).status_code == 404
    assert client.patch(f"/api/v1/goals/{goal_id}", headers=other,
                        json={"target_amount": 1}).status_code == 404
    assert client.delete(f"/api/v1/goals/{goal_id}", headers=other).status_code == 404
    assert client.get(f"/api/v1/goals/{goal_id}/forecast",
                      headers=other).status_code == 404


# --------------------------------------------------------------------------
# Forecast
# --------------------------------------------------------------------------

def test_forecast_returns_a_scenario_band_not_a_single_number(client, funded):
    goal_id = client.post("/api/v1/goals", headers=funded, json=_goal()).json()["id"]
    body = client.get(f"/api/v1/goals/{goal_id}/forecast", headers=funded).json()

    scenarios = body["scenarios"]
    assert set(scenarios) == {"pessimistic", "expected", "optimistic"}
    assert (
        scenarios["pessimistic"]["projected_value"]
        < scenarios["expected"]["projected_value"]
        < scenarios["optimistic"]["projected_value"]
    )


def test_forecast_discloses_where_its_return_estimate_came_from(client, funded):
    goal_id = client.post("/api/v1/goals", headers=funded, json=_goal()).json()["id"]
    assumptions = client.get(f"/api/v1/goals/{goal_id}/forecast",
                             headers=funded).json()["assumptions"]

    assert "return_estimate" in assumptions
    assert assumptions["return_estimate"]["source"]
    assert "not a prediction" in assumptions["note"]
    # The MVP measures every goal against the whole portfolio; that has to be
    # stated rather than left for the user to infer.
    assert assumptions["current_amount_source"]


def test_forecast_caps_an_implausible_historical_return(client, funded):
    goal_id = client.post("/api/v1/goals", headers=funded, json=_goal()).json()["id"]
    estimate = client.get(f"/api/v1/goals/{goal_id}/forecast",
                          headers=funded).json()["assumptions"]["return_estimate"]

    # Whatever the sample period happened to deliver, the rate projected over
    # decades stays inside a defensible band.
    assert 0.02 <= estimate["expected_annual_return"] <= 0.18


def test_forecast_includes_a_plottable_path(client, funded):
    goal_id = client.post("/api/v1/goals", headers=funded, json=_goal()).json()["id"]
    path = client.get(f"/api/v1/goals/{goal_id}/forecast", headers=funded).json()["path"]

    assert len(path["months"]) == len(path["projected_value"])
    assert path["projected_value"][-1] > path["projected_value"][0]


def test_forecast_works_without_any_portfolio(client, auth):
    # A brand-new user with a goal and no holdings still gets a projection,
    # falling back to a stated default return.
    goal_id = client.post("/api/v1/goals", headers=auth, json=_goal()).json()["id"]
    body = client.get(f"/api/v1/goals/{goal_id}/forecast", headers=auth).json()

    assert body["assumptions"]["return_estimate"]["source"] == "default assumption"
    assert body["projected_value"] > 0


# --------------------------------------------------------------------------
# Health Score
# --------------------------------------------------------------------------

def test_health_score_is_fully_decomposed(client, funded):
    body = client.get("/api/v1/health-score", headers=funded).json()

    assert 0 <= body["total"] <= 100
    assert body["grade"]
    assert len(body["components"]) == 6
    for component in body["components"]:
        assert component["reason"]
        assert "weight" in component and "inputs" in component


def test_health_score_total_matches_its_components(client, funded):
    body = client.get("/api/v1/health-score", headers=funded).json()
    scored = [c for c in body["components"] if c["score"] is not None]

    expected = sum(c["score"] * c["weight"] for c in scored) / sum(c["weight"] for c in scored)
    assert body["total"] == pytest.approx(expected, abs=0.05)


def test_health_score_names_the_components_it_could_not_measure(client, funded):
    # No goals are set here, so goal alignment must be reported as missing
    # rather than silently scored.
    body = client.get("/api/v1/health-score", headers=funded).json()
    assert "goal_alignment" in body["missing_inputs"]


def test_adding_a_goal_makes_the_goal_component_scoreable(client, funded):
    before = client.get("/api/v1/health-score", headers=funded).json()
    assert "goal_alignment" in before["missing_inputs"]

    client.post("/api/v1/goals", headers=funded, json=_goal())

    after = client.get("/api/v1/health-score", headers=funded).json()
    assert "goal_alignment" not in after["missing_inputs"]


def test_health_score_sensitivity_is_available_on_request(client, funded):
    plain = client.get("/api/v1/health-score", headers=funded).json()
    assert "sensitivity" not in plain

    detailed = client.get("/api/v1/health-score?sensitivity=true", headers=funded).json()
    assert detailed["sensitivity"]
    swings = [r["swing"] for r in detailed["sensitivity"]]
    assert swings == sorted(swings, reverse=True)


def test_a_concentrated_portfolio_scores_worse_than_a_diversified_one(client, auth, second_user):
    # One user holds a single stock; the other spreads across five assets.
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "RELIANCE", "quantity": 100, "average_price": 1000})

    other = second_user["headers"]
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000),
        ("INFY", 15, 1400), ("GOLDBEES", 500, 50), ("DEBT", 400, 50),
    ]:
        client.post("/api/v1/portfolio/holdings", headers=other,
                    json={"symbol": symbol, "quantity": quantity, "average_price": price})

    concentrated = client.get("/api/v1/health-score", headers=auth).json()["total"]
    diversified = client.get("/api/v1/health-score", headers=other).json()["total"]

    assert diversified > concentrated


def test_empty_portfolio_is_not_graded_poor(client, auth):
    # An account with nothing in it has no data to judge, which is different
    # from having a bad portfolio.
    body = client.get("/api/v1/health-score", headers=auth).json()
    # Both assertions hold, and they say different things: "Unknown" is the
    # grade, null is the total. The `or` that used to join them meant either
    # could regress unnoticed.
    assert body["grade"] == "Unknown"
    assert body["total"] is None
    assert "diversification" in body["missing_inputs"]


def test_health_score_requires_authentication(client):
    assert client.get("/api/v1/health-score").status_code == 401
    assert client.get("/api/v1/goals").status_code == 401
