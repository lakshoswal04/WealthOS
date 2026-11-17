"""The research reports endpoint and the goal scenario simulator."""

from __future__ import annotations

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


def _goal(client, auth) -> int:
    response = client.post("/api/v1/goals", headers=auth, json={
        "name": "Retirement", "goal_type": "retirement",
        "target_amount": 10_000_000, "target_date": "2046-01-01",
        "monthly_contribution": 30_000,
    })
    assert response.status_code == 201
    return response.json()["id"]


# --------------------------------------------------------------------------
# Research reports
# --------------------------------------------------------------------------

def test_reports_are_public(client):
    # They describe models and market data, both identical for every account,
    # so there is nothing to protect and the landing page can cite them.
    response = client.get("/api/v1/research/reports")
    assert response.status_code == 200
    assert set(response.json()) == {"models", "data"}


def test_reports_expose_no_user_data(client, funded):
    # A report must never carry a portfolio, an email or a holding.
    body = client.get("/api/v1/research/reports").text.lower()
    for leak in ("investor@example.com", "hashed_password", "access_token"):
        assert leak not in body


def test_every_report_says_whether_it_is_available(client):
    body = client.get("/api/v1/research/reports").json()
    for group in body.values():
        for name, report in group.items():
            assert "available" in report, name
            if not report["available"]:
                # An absent report must explain itself rather than appear empty.
                assert report.get("reason"), name


def test_a_single_report_can_be_fetched(client):
    response = client.get("/api/v1/research/reports/clustering")
    assert response.status_code == 200
    assert "available" in response.json()


def test_an_unknown_report_is_rejected_with_the_valid_names(client):
    response = client.get("/api/v1/research/reports/../../etc/passwd")
    assert response.status_code in (404, 400)

    named = client.get("/api/v1/research/reports/not_a_report")
    assert named.status_code == 404
    assert "Available" in named.json()["detail"]


@pytest.mark.parametrize("name", ["clustering", "anomaly_detection", "forecast_12m"])
def test_model_reports_carry_the_fields_the_page_renders(client, name):
    report = client.get(f"/api/v1/research/reports/{name}").json()
    if not report["available"]:
        pytest.skip(f"{name} not generated in this environment")

    expected = {
        "clustering": {"chosen_k", "k_selection", "archetype_recovery", "clusters"},
        "anomaly_detection": {"autoencoder", "isolation_forest", "by_anomaly_type"},
        "forecast_12m": {"results", "best_model", "xgboost_feature_importance"},
    }[name]
    assert expected <= set(report)


# --------------------------------------------------------------------------
# Scenario simulator
# --------------------------------------------------------------------------

def test_simulation_requires_authentication(client):
    assert client.post("/api/v1/goals/1/simulate", json={}).status_code == 401


def test_simulation_opens_on_the_users_actual_position(client, funded):
    goal_id = _goal(client, funded)
    body = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json={}).json()

    # With nothing overridden, the inputs must equal the defaults.
    assert body["inputs"] == body["defaults"] or (
        body["inputs"]["monthly_contribution"] == body["defaults"]["monthly_contribution"]
    )
    assert body["inputs"]["monthly_contribution"] == pytest.approx(30_000)


def test_simulation_returns_an_ordered_fan(client, funded):
    goal_id = _goal(client, funded)
    body = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json={}).json()
    bands = body["monte_carlo"]["percentiles"]

    assert set(bands) == {"p10", "p25", "p50", "p75", "p90"}
    for index in range(0, len(bands["p50"]), 10):
        values = [bands[f"p{p}"][index] for p in (10, 25, 50, 75, 90)]
        assert values == sorted(values)


def test_the_fan_and_the_deterministic_path_share_a_horizon(client, funded):
    goal_id = _goal(client, funded)
    body = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json={}).json()

    assert len(body["deterministic"]["projected_value"]) == len(body["monte_carlo"]["percentiles"]["p50"])


def test_raising_the_contribution_raises_the_chance_of_success(client, funded):
    goal_id = _goal(client, funded)

    low = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded,
                      json={"monthly_contribution": 5_000}).json()
    high = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded,
                       json={"monthly_contribution": 200_000}).json()

    assert high["success_probability"] > low["success_probability"]


def test_a_shorter_horizon_lowers_the_projection(client, funded):
    goal_id = _goal(client, funded)

    short = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded,
                        json={"months": 24}).json()
    long = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded,
                       json={"months": 240}).json()

    assert short["deterministic"]["final_value"] < long["deterministic"]["final_value"]


def test_zero_volatility_collapses_the_fan(client, funded):
    goal_id = _goal(client, funded)
    body = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded,
                       json={"annual_volatility": 0.0}).json()
    finals = body["monte_carlo"]["final_values"]

    assert finals["p10"] == pytest.approx(finals["p90"])


@pytest.mark.parametrize("payload", [
    {"annual_return": 5.0},          # 500% a year
    {"annual_return": -0.9},         # -90% a year
    {"annual_volatility": 3.0},
    {"monthly_contribution": -100},
    {"months": 0},
    {"months": 10_000},
])
def test_absurd_assumptions_are_rejected(client, funded, payload):
    # The sliders exist to explore plausible futures, not to generate
    # arithmetically valid nonsense.
    goal_id = _goal(client, funded)
    response = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json=payload)
    assert response.status_code == 422


def test_simulation_states_its_assumptions_and_disclaims_itself(client, funded):
    goal_id = _goal(client, funded)
    body = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json={}).json()
    assumptions = body["monte_carlo"]["assumptions"]

    assert assumptions["paths_simulated"] > 0
    assert "not a prediction" in assumptions["note"]
    assert body["return_estimate"]["source"]


def test_a_simulation_is_reproducible(client, funded):
    # The same inputs must give the same fan, so a demonstration does not
    # change numbers between runs.
    goal_id = _goal(client, funded)
    first = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json={}).json()
    second = client.post(f"/api/v1/goals/{goal_id}/simulate", headers=funded, json={}).json()

    assert first["monte_carlo"]["final_values"] == second["monte_carlo"]["final_values"]


def test_another_users_goal_cannot_be_simulated(client, funded, second_user):
    goal_id = _goal(client, funded)
    response = client.post(f"/api/v1/goals/{goal_id}/simulate",
                           headers=second_user["headers"], json={})
    assert response.status_code == 404
