"""The decision-support engine.

Two properties matter more than any individual rule. An alert must never read
as investment advice, and it must never state a number the platform did not
measure. Both are enforced in code and asserted here.
"""

from __future__ import annotations

import json

import pytest

from app.models import Alert, AlertSeverity, AlertType, ModelOutput
from app.services import alert_service


@pytest.fixture
def concentrated(client, auth):
    """One position dominating the portfolio, which must trip a rule."""
    assert client.post("/api/v1/portfolio/holdings", headers=auth,
                       json={"symbol": "RELIANCE", "quantity": 100,
                             "average_price": 1000}).status_code == 201
    assert client.post("/api/v1/portfolio/holdings", headers=auth,
                       json={"symbol": "DEBT", "quantity": 100,
                             "average_price": 50}).status_code == 201
    return auth


@pytest.fixture
def diversified(client, auth):
    for symbol, quantity, price in [
        ("RELIANCE", 20, 1000), ("TCS", 10, 3000), ("INFY", 15, 1400),
        ("GOLDBEES", 500, 50), ("DEBT", 400, 50),
    ]:
        client.post("/api/v1/portfolio/holdings", headers=auth,
                    json={"symbol": symbol, "quantity": quantity,
                          "average_price": price})
    return auth


# --------------------------------------------------------------------------
# The stance: measurements, never advice
# --------------------------------------------------------------------------

def test_no_generated_alert_reads_as_investment_advice(client, concentrated):
    """The constraint the Alert docstring already stated, now enforced.

    "Your largest holding is 38% of the portfolio" is a measurement.
    "Reduce your largest holding" is investment advice, and this platform is
    not licensed to give it. The difference is not cosmetic.
    """
    body = client.post("/api/v1/alerts/generate", headers=concentrated).json()
    assert body["generated_count"] > 0, "no rule fired, so nothing was tested"

    for alert in body["generated"]:
        text = f"{alert['title']} {alert['message']}".lower()
        for phrase in alert_service.FORBIDDEN_PHRASES:
            assert phrase not in text, (
                f"{alert['alert_type']} alert contains {phrase!r}: {text!r}"
            )


def test_a_rule_that_reads_as_advice_is_refused(client, concentrated, monkeypatch):
    """The gate has to actually reject, not merely exist."""
    def advisory_rule(evidence):
        return alert_service.Candidate(
            alert_type=AlertType.CONCENTRATION,
            severity=AlertSeverity.WARNING,
            title="Act now",
            message="You should sell some of this position immediately.",
            metric_value=0.5, threshold=0.35,
        )

    monkeypatch.setattr(alert_service, "RULES", (advisory_rule,))
    body = client.post("/api/v1/alerts/generate", headers=concentrated).json()

    assert body["generated_count"] == 0
    assert body["rejected"], "the advisory rule was not rejected"
    assert body["rejected"][0]["reason"] == "reads as investment advice"
    assert "you should" in body["rejected"][0]["phrases"]


def test_a_rule_citing_an_unmeasured_figure_is_refused(client, concentrated, monkeypatch):
    """The same groundedness check that verifies Copilot answers.

    A rule that invents a number is a rule that fabricates, and the platform
    reports measurements. 47.3% appears in no measurement.
    """
    def fabricating_rule(evidence):
        return alert_service.Candidate(
            alert_type=AlertType.DRAWDOWN,
            severity=AlertSeverity.WARNING,
            title="Unusual movement",
            message="The portfolio returned 47.3% over the period.",
            metric_value=None, threshold=None,
        )

    monkeypatch.setattr(alert_service, "RULES", (fabricating_rule,))
    body = client.post("/api/v1/alerts/generate", headers=concentrated).json()

    assert body["generated_count"] == 0
    assert body["rejected"][0]["reason"] == (
        "cites figures the measurements do not contain"
    )
    assert 47.3 in body["rejected"][0]["unverified_numbers"]


def test_the_stance_is_stated_in_the_response(client, diversified):
    body = client.post("/api/v1/alerts/generate", headers=diversified).json()
    assert "not a regulated advisory service" in body["stance"]


# --------------------------------------------------------------------------
# The rules
# --------------------------------------------------------------------------

def test_a_dominant_position_is_flagged_with_its_evidence(client, concentrated):
    body = client.post("/api/v1/alerts/generate", headers=concentrated).json()
    found = [a for a in body["generated"]
             if a["alert_type"] == str(AlertType.CONCENTRATION)]
    assert found, [a["alert_type"] for a in body["generated"]]

    alert = found[0]
    assert alert["metric_value"] > alert["threshold"]
    assert alert["details"]["largest_holding"]
    assert alert["details"]["measured_by"] == "risk_service.concentration"
    # The evidence must carry the groundedness verdict that let it through.
    assert alert["details"]["groundedness"]["is_grounded"] is True


def test_severity_rises_with_the_measurement(client, auth):
    """A 30% position and a 60% position must not read the same."""
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "RELIANCE", "quantity": 1000, "average_price": 1000})
    body = client.post("/api/v1/alerts/generate", headers=auth).json()
    found = [a for a in body["generated"]
             if a["alert_type"] == str(AlertType.CONCENTRATION)]
    assert found
    # A single holding is 100% of the portfolio, past every threshold.
    assert found[0]["severity"] == str(AlertSeverity.CRITICAL)
    assert found[0]["metric_value"] == pytest.approx(1.0)


def test_the_concentration_rule_fires_exactly_when_the_threshold_is_passed(
    client, diversified
):
    """Driven by the measurement rather than by a hand-guessed fixture.

    The five-holding fixture reads as 42% in its largest position, because
    equal quantities at unequal prices are not equal weights. Asserting "five
    holdings means no alert" would have been asserting something false about
    the fixture; asserting the rule against the measured weight tests the
    rule.
    """
    measured = client.get("/api/v1/portfolio/concentration",
                          headers=diversified).json()
    top = measured["top_1_weight"]

    body = client.post("/api/v1/alerts/generate", headers=diversified).json()
    fired = str(AlertType.CONCENTRATION) in {
        a["alert_type"] for a in body["generated"]
    }

    floor = alert_service.CONCENTRATION_THRESHOLDS[AlertSeverity.INFO]
    assert fired is (top >= floor), (
        f"largest position {top:.1%} against a {floor:.0%} floor, "
        f"alert fired: {fired}"
    )


def test_an_evenly_weighted_portfolio_raises_no_concentration_alert(client, auth):
    """Built from measured prices so the weights really are even."""
    # Buy a fixed rupee amount of each, which is what makes the weights equal
    # regardless of price. Prices come from the holdings response itself.
    wanted = 100_000.0
    for symbol in ("RELIANCE", "TCS", "INFY", "GOLDBEES", "DEBT"):
        probe = client.post("/api/v1/portfolio/holdings", headers=auth,
                            json={"symbol": symbol, "quantity": 1,
                                  "average_price": 100})
        assert probe.status_code == 201, probe.text
        price = probe.json().get("current_price")
        if not price:
            pytest.skip(f"no price available for {symbol}")
        client.patch(f"/api/v1/portfolio/holdings/{probe.json()['id']}",
                   headers=auth,
                   json={"quantity": wanted / float(price)})

    summary = client.get("/api/v1/portfolio/concentration", headers=auth).json()
    assert summary["top_1_weight"] < 0.25, summary["top_1_weight"]

    body = client.post("/api/v1/alerts/generate", headers=auth).json()
    types = {a["alert_type"] for a in body["generated"]}
    assert str(AlertType.CONCENTRATION) not in types


def test_every_rule_is_run_and_counted(client, diversified):
    body = client.post("/api/v1/alerts/generate", headers=diversified).json()
    assert body["rules_run"] == len(alert_service.RULES) == 6


def test_a_measurement_failure_does_not_silence_the_other_rules(client, auth):
    """An empty portfolio has no price history, but the engine must not crash.

    Each source is gathered separately so one unavailable measurement leaves
    the rest working, and what failed is reported rather than swallowed.
    """
    body = client.post("/api/v1/alerts/generate", headers=auth).json()
    assert body["rules_run"] == 6
    assert isinstance(body["measurement_failures"], dict)
    json.dumps(body, allow_nan=False)


# --------------------------------------------------------------------------
# health_score_drop needs a stored history, which is why model_outputs lives
# --------------------------------------------------------------------------

def test_the_health_score_is_recorded_for_future_comparison(client, diversified, seeded_db):
    """`model_outputs` was a dead table; without it this rule can never fire."""
    client.post("/api/v1/alerts/generate", headers=diversified)

    rows = seeded_db.query(ModelOutput).filter(
        ModelOutput.model_name == alert_service.HEALTH_SCORE_MODEL_NAME
    ).all()
    assert rows, "no health score was recorded"
    assert rows[0].score is not None
    assert rows[0].prediction  # the grade
    assert "components" in rows[0].payload


def test_no_drop_alert_without_a_previous_measurement(client, diversified):
    """There is nothing to have dropped from on a first run."""
    body = client.post("/api/v1/alerts/generate", headers=diversified).json()
    types = {a["alert_type"] for a in body["generated"]}
    assert str(AlertType.HEALTH_SCORE_DROP) not in types


def test_a_recorded_fall_in_the_health_score_is_flagged(client, diversified, seeded_db):
    """Plant a high prior score, then check the drop is detected and quantified."""
    from app.models import User
    user = seeded_db.query(User).first()
    current = client.get("/api/v1/health-score?methodology=v2",
                         headers=diversified).json()["total"]

    seeded_db.add(ModelOutput(
        user_id=user.id, model_name=alert_service.HEALTH_SCORE_MODEL_NAME,
        model_version="v2", as_of_date=__import__("datetime").date.today(),
        score=float(current) + 25.0, prediction="Excellent", payload={},
    ))
    seeded_db.commit()

    body = client.post("/api/v1/alerts/generate", headers=diversified).json()
    found = [a for a in body["generated"]
             if a["alert_type"] == str(AlertType.HEALTH_SCORE_DROP)]
    assert found, [a["alert_type"] for a in body["generated"]]

    alert = found[0]
    assert alert["severity"] == str(AlertSeverity.CRITICAL)   # 25 points > 20
    assert alert["details"]["drop"] == pytest.approx(25.0, abs=0.2)
    assert alert["details"]["previous_score"] == pytest.approx(current + 25.0, abs=0.2)


# --------------------------------------------------------------------------
# Deduplication, listing, reading, dismissing
# --------------------------------------------------------------------------

def test_repeated_generation_does_not_stack_duplicates(client, concentrated):
    """Forty copies of one finding communicate less than one copy."""
    first = client.post("/api/v1/alerts/generate", headers=concentrated).json()
    assert first["generated_count"] > 0

    second = client.post("/api/v1/alerts/generate", headers=concentrated).json()
    assert second["generated_count"] == 0
    assert str(AlertType.CONCENTRATION) in second["suppressed_as_already_open"]

    listed = client.get("/api/v1/alerts", headers=concentrated).json()
    types = [a["alert_type"] for a in listed["alerts"]]
    assert len(types) == len(set(types)), types


def test_alerts_are_listed_newest_first_with_a_severity_breakdown(client, concentrated):
    client.post("/api/v1/alerts/generate", headers=concentrated)
    body = client.get("/api/v1/alerts", headers=concentrated).json()

    assert body["total"] >= 1
    assert body["unread"] == body["total"]
    assert sum(body["by_severity"].values()) == body["total"]
    stamps = [a["created_at"] for a in body["alerts"]]
    assert stamps == sorted(stamps, reverse=True)


def test_marking_one_read_changes_only_that_one(client, concentrated):
    client.post("/api/v1/alerts/generate", headers=concentrated)
    listed = client.get("/api/v1/alerts", headers=concentrated).json()
    target = listed["alerts"][0]["id"]

    marked = client.post(f"/api/v1/alerts/{target}/read", headers=concentrated)
    assert marked.status_code == 200
    assert marked.json()["is_read"] is True

    after = client.get("/api/v1/alerts", headers=concentrated).json()
    assert after["unread"] == listed["unread"] - 1

    unread_only = client.get("/api/v1/alerts?include_read=false",
                             headers=concentrated).json()
    assert target not in [a["id"] for a in unread_only["alerts"]]


def test_dismissing_removes_the_alert(client, concentrated):
    client.post("/api/v1/alerts/generate", headers=concentrated)
    listed = client.get("/api/v1/alerts", headers=concentrated).json()
    target = listed["alerts"][0]["id"]

    assert client.delete(f"/api/v1/alerts/{target}",
                         headers=concentrated).status_code == 204
    after = client.get("/api/v1/alerts", headers=concentrated).json()
    assert target not in [a["id"] for a in after["alerts"]]


def test_a_missing_alert_is_a_404_not_a_500(client, concentrated):
    assert client.post("/api/v1/alerts/999999/read",
                       headers=concentrated).status_code == 404
    assert client.delete("/api/v1/alerts/999999",
                         headers=concentrated).status_code == 404


# --------------------------------------------------------------------------
# Isolation between users
# --------------------------------------------------------------------------

def test_one_user_cannot_see_or_touch_another_users_alerts(
    client, concentrated, second_user
):
    client.post("/api/v1/alerts/generate", headers=concentrated)
    mine = client.get("/api/v1/alerts", headers=concentrated).json()
    assert mine["total"] >= 1
    target = mine["alerts"][0]["id"]

    other = second_user["headers"]
    assert client.get("/api/v1/alerts", headers=other).json()["total"] == 0
    # And the id is not reachable by guessing it.
    assert client.post(f"/api/v1/alerts/{target}/read", headers=other).status_code == 404
    assert client.delete(f"/api/v1/alerts/{target}", headers=other).status_code == 404


def test_every_endpoint_requires_authentication(client):
    assert client.get("/api/v1/alerts").status_code == 401
    assert client.post("/api/v1/alerts/generate").status_code == 401
    assert client.post("/api/v1/alerts/1/read").status_code == 401
    assert client.delete("/api/v1/alerts/1").status_code == 401
