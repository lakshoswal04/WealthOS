"""Analytics, risk and concentration endpoints."""

from __future__ import annotations

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
# Analytics
# --------------------------------------------------------------------------

def test_analytics_reports_every_headline_metric(client, funded):
    body = client.get("/api/v1/portfolio/analytics", headers=funded).json()
    summary = body["summary"]

    for field in ("annualized_return", "annualized_volatility", "sharpe_ratio",
                  "sortino_ratio", "max_drawdown", "var_95", "cvar_95", "beta", "alpha"):
        assert field in summary, field
    assert summary["observations"] > 0


def test_analytics_states_its_assumptions(client, funded):
    # A Sharpe ratio is meaningless without the risk-free rate that produced
    # it, so the assumptions travel with the numbers.
    assumptions = client.get("/api/v1/portfolio/analytics", headers=funded).json()["assumptions"]

    assert assumptions["risk_free_rate"] == pytest.approx(0.06)
    assert assumptions["benchmark"] == "NIFTY50"
    assert "current weights held constant" in assumptions["method"]
    assert assumptions["observations"] > 0


def test_analytics_returns_a_plottable_series(client, funded):
    series = client.get("/api/v1/portfolio/analytics", headers=funded).json()["series"]

    assert len(series["dates"]) == len(series["cumulative_return"])
    assert len(series["dates"]) > 0
    assert series["benchmark_cumulative_return"] is not None


def test_empty_portfolio_is_rejected_with_a_clear_reason(client, auth):
    for path in ("/api/v1/portfolio/analytics", "/api/v1/portfolio/risk",
                 "/api/v1/portfolio/concentration"):
        response = client.get(path, headers=auth)
        assert response.status_code == 422, path
        assert "no priced holdings" in response.json()["detail"].lower()


def test_analytics_requires_authentication(client):
    assert client.get("/api/v1/portfolio/analytics").status_code == 401
    assert client.get("/api/v1/portfolio/risk").status_code == 401
    assert client.get("/api/v1/portfolio/concentration").status_code == 401


# --------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------

def test_drawdown_is_never_positive(client, funded):
    drawdown = client.get("/api/v1/portfolio/risk", headers=funded).json()["drawdown"]

    assert drawdown["max_drawdown"] <= 0
    assert all(v <= 1e-9 for v in drawdown["series"]["drawdown"])


def test_drawdown_series_aligns_with_its_dates(client, funded):
    drawdown = client.get("/api/v1/portfolio/risk", headers=funded).json()["drawdown"]
    assert len(drawdown["series"]["dates"]) == len(drawdown["series"]["drawdown"])


def test_correlation_matrix_is_square_and_symmetric(client, funded):
    correlation = client.get("/api/v1/portfolio/risk", headers=funded).json()["correlation"]
    matrix, symbols = correlation["matrix"], correlation["symbols"]

    assert len(matrix) == len(symbols)
    assert all(len(row) == len(symbols) for row in matrix)
    for i in range(len(symbols)):
        assert matrix[i][i] == pytest.approx(1.0, abs=1e-6)
        for j in range(len(symbols)):
            assert matrix[i][j] == pytest.approx(matrix[j][i], abs=1e-6)


def test_risk_return_scatter_covers_every_holding(client, funded):
    scatter = client.get("/api/v1/portfolio/risk", headers=funded).json()["risk_return_scatter"]

    assert {a["symbol"] for a in scatter} == {"RELIANCE", "TCS", "INFY", "GOLDBEES", "DEBT"}
    assert sum(a["weight"] for a in scatter) == pytest.approx(1.0)
    assert all(a["annualized_volatility"] >= 0 for a in scatter)


def test_portfolio_volatility_is_below_the_weighted_average_of_its_parts(client, funded):
    # Imperfectly correlated holdings diversify. If the portfolio's volatility
    # came out at or above the weighted average of the individual volatilities,
    # the covariance structure would be being ignored.
    body = client.get("/api/v1/portfolio/risk", headers=funded).json()
    portfolio_vol = body["summary"]["annualized_volatility"]
    weighted_average = sum(
        a["weight"] * a["annualized_volatility"] for a in body["risk_return_scatter"]
    )
    assert portfolio_vol < weighted_average


# --------------------------------------------------------------------------
# Concentration
# --------------------------------------------------------------------------

def test_concentration_reports_all_three_levels(client, funded):
    body = client.get("/api/v1/portfolio/concentration", headers=funded).json()

    assert body["n_holdings"] == 5
    assert sum(body["weights"].values()) == pytest.approx(1.0)
    assert sum(body["sector_weights"].values()) == pytest.approx(1.0)
    assert sum(body["asset_class_weights"].values()) == pytest.approx(1.0)
    assert set(body["asset_class_weights"]) == {"equity", "gold", "debt"}


def test_effective_holdings_never_exceeds_the_holding_count(client, funded):
    body = client.get("/api/v1/portfolio/concentration", headers=funded).json()
    assert body["effective_holdings"] <= body["n_holdings"] + 1e-9


def test_a_single_holding_portfolio_is_flagged_as_concentrated(client, auth):
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "RELIANCE", "quantity": 100, "average_price": 1000})

    body = client.get("/api/v1/portfolio/concentration", headers=auth).json()

    assert body["hhi"] == pytest.approx(1.0)
    assert body["hhi_normalized"] == pytest.approx(1.0)
    assert body["effective_holdings"] == pytest.approx(1.0)
    assert body["top_1_weight"] == pytest.approx(1.0)
    text = " ".join(body["interpretation"]).lower()
    assert "largest holding" in text or "one asset class" in text


def test_sector_concentration_is_called_out(client, auth):
    # TCS and INFY are both IT in the fixture, so IT dominates.
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "TCS", "quantity": 100, "average_price": 3000})
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "INFY", "quantity": 100, "average_price": 1400})
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "DEBT", "quantity": 10, "average_price": 50})

    body = client.get("/api/v1/portfolio/concentration", headers=auth).json()

    assert body["largest_sector"] == "IT"
    assert body["max_sector_weight"] > 0.9
    assert any("IT" in note for note in body["interpretation"])


def test_concentration_is_scoped_to_the_requesting_user(client, funded, second_user):
    response = client.get("/api/v1/portfolio/concentration",
                          headers=second_user["headers"])
    assert response.status_code == 422  # the other user holds nothing
