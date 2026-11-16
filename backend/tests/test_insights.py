"""Model-backed insight endpoints and their degradation behaviour."""

from __future__ import annotations

import pytest

from app.ml_runtime.registry import registry


@pytest.fixture
def funded(client, auth):
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000),
        ("INFY", 15, 1400), ("GOLDBEES", 500, 50), ("DEBT", 400, 50),
    ]:
        client.post("/api/v1/portfolio/holdings", headers=auth,
                    json={"symbol": symbol, "quantity": quantity, "average_price": price})
    return auth


def _models_present() -> bool:
    return registry.status()["all_loaded"]


models_required = pytest.mark.skipif(
    not _models_present(), reason="trained model artifacts are not present"
)


# --------------------------------------------------------------------------
# Availability and graceful degradation
# --------------------------------------------------------------------------

def test_model_status_reports_what_is_loaded(client):
    status = client.get("/api/v1/models/status").json()
    assert "available" in status and "all_loaded" in status
    assert set(status["available"]) == {
        "investor_clustering", "anomaly_autoencoder", "forecast_12m"
    }


def test_insight_endpoints_require_authentication(client):
    for path in ("/api/v1/investor-profile", "/api/v1/anomalies", "/api/v1/forecast"):
        assert client.get(path).status_code == 401, path


def test_insights_return_a_reason_rather_than_failing_on_an_empty_portfolio(client, auth):
    # A user with nothing should get an explanation, not a 500. Every one of
    # these answers 200 with available=false.
    for path in ("/api/v1/investor-profile", "/api/v1/anomalies", "/api/v1/forecast"):
        response = client.get(path, headers=auth)
        assert response.status_code == 200, path
        body = response.json()
        assert body["available"] is False
        assert body.get("reason")


# --------------------------------------------------------------------------
# Investor profile
# --------------------------------------------------------------------------

@models_required
def test_investor_profile_assigns_a_named_cluster(client, funded):
    body = client.get("/api/v1/investor-profile", headers=funded).json()
    assert body["available"] is True
    assert isinstance(body["cluster"], int)
    assert body["cluster_name"]
    assert 0.0 <= body["match_confidence"] <= 1.0


@models_required
def test_investor_profile_states_how_behaviour_was_reconstructed(client, funded):
    # Behaviour is inferred by valuing today's holdings backward, which is not
    # a replay of what was actually held. That has to be said.
    body = client.get("/api/v1/investor-profile", headers=funded).json()
    assert "caveat" in body
    assert "reconstructed" in body["caveat"].lower()


@models_required
def test_investor_profile_is_private_to_its_owner(client, funded, second_user):
    other = client.get("/api/v1/investor-profile", headers=second_user["headers"]).json()
    assert other["available"] is False


# --------------------------------------------------------------------------
# Anomalies
# --------------------------------------------------------------------------

@models_required
def test_anomaly_scan_returns_a_timeline(client, funded):
    body = client.get("/api/v1/anomalies", headers=funded).json()
    assert body["available"] is True
    assert body["months_examined"] > 0
    assert isinstance(body["anomalies"], list)
    assert len(body["timeline"]) > 0
    for point in body["timeline"]:
        assert {"date", "score", "is_anomaly"} <= set(point)


@models_required
def test_each_detected_anomaly_explains_itself(client, funded):
    body = client.get("/api/v1/anomalies", headers=funded).json()
    for anomaly in body["anomalies"]:
        assert anomaly["score"] >= anomaly["threshold"]
        assert anomaly["severity"] in {"info", "warning", "critical"}
        # Saying a month was unusual is not useful without saying why.
        assert anomaly["contributing_features"]


@models_required
def test_anomaly_limit_is_respected(client, funded):
    body = client.get("/api/v1/anomalies?limit=5", headers=funded).json()
    assert len(body["timeline"]) <= 5


# --------------------------------------------------------------------------
# Forecast
# --------------------------------------------------------------------------

@models_required
def test_forecast_projects_from_an_explicit_baseline(client, funded):
    body = client.get("/api/v1/forecast?horizon=12", headers=funded).json()
    assert body["available"] is True
    assert body["baseline_value"] > 0
    assert body["projected_value"] > 0
    assert body["horizon_months"] == 12
    assert body["models_used"]


@models_required
def test_forecast_reports_how_far_apart_the_models_are(client, funded):
    # Averaging disagreeing models into one confident number hides the
    # uncertainty, so the spread travels with the point estimate.
    body = client.get("/api/v1/forecast", headers=funded).json()
    spread = body["projection_range"]

    assert spread["low"] <= body["projected_value"] <= spread["high"]
    assert spread["log_growth_spread"] >= 0
    assert spread["agreement"]


@models_required
def test_forecast_never_presents_itself_as_a_prediction(client, funded):
    assumptions = client.get("/api/v1/forecast", headers=funded).json()["assumptions"]
    assert "not a prediction" in assumptions["note"]
    assert assumptions["baseline"]


@models_required
def test_unsupported_horizon_falls_back_to_twelve_months(client, funded):
    body = client.get("/api/v1/forecast?horizon=7", headers=funded).json()
    assert body["horizon_months"] == 12
