"""Connecting Upstox: credentials, the OAuth state, token storage, holdings sync."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from app.core.config import settings
from app.models import BrokerCredential, Holding, LinkedAccount, User


def _save_app(client, auth):
    r = client.put("/api/v1/me/brokers/upstox", headers=auth,
                   json={"api_key": "my-upstox-api-key-1234", "api_secret": "my-upstox-secret-5678"})
    assert r.status_code == 200, r.text
    return r.json()


def _login_state(client, auth) -> str:
    r = client.post("/api/v1/me/brokers/upstox/login", headers=auth)
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["authorization_url"])
    q = parse_qs(url.query)
    assert url.netloc == "api.upstox.com" and q["client_id"] == ["my-upstox-api-key-1234"]
    assert q["redirect_uri"] == [settings.upstox_redirect_uri]
    return q["state"][0]


def _callback(client, state, code="good-code"):
    return client.get(f"/api/v1/brokers/upstox/callback?code={code}&state={state}", follow_redirects=False)


def test_credentials_are_encrypted_and_never_echoed(client, auth, market, seeded_db):
    body = _save_app(client, auth)
    assert body["credentials_saved"] and body["api_key_hint"] == "1234" and body["state"] == "not_connected"
    row = seeded_db.query(BrokerCredential).one()
    assert "my-upstox" not in row.api_key_encrypted and "my-upstox" not in (row.api_secret_encrypted or "")
    listing = client.get("/api/v1/me/brokers", headers=auth).text
    assert "my-upstox-api-key" not in listing and "my-upstox-secret" not in listing


def test_login_needs_saved_credentials(client, auth, market):
    r = client.post("/api/v1/me/brokers/upstox/login", headers=auth)
    assert r.status_code == 422 and "API key" in r.json()["detail"]


def test_a_valid_login_stores_a_real_token(client, auth, market, seeded_db):
    _save_app(client, auth)
    r = _callback(client, _login_state(client, auth))
    assert r.status_code == 303 and r.headers["location"].endswith("/settings/brokers?upstox=connected")
    account = seeded_db.query(LinkedAccount).filter_by(provider="upstox").one()
    assert account.is_simulated is False and "good-token" not in account.access_token_encrypted
    assert account.token_expires_at > datetime.now(timezone.utc)
    status = client.get("/api/v1/me/brokers", headers=auth).json()["brokers"]
    assert next(b for b in status if b["broker"] == "upstox")["state"] == "connected"


def test_a_state_cannot_be_replayed(client, auth, market):
    _save_app(client, auth)
    state = _login_state(client, auth)
    assert "connected" in _callback(client, state).headers["location"]
    again = _callback(client, state)
    assert "upstox=error" in again.headers["location"]


def test_tampered_and_foreign_states_are_refused(client, auth, second_user, market, seeded_db):
    _save_app(client, auth)
    state = _login_state(client, auth)
    assert "upstox=error" in _callback(client, state[:-3] + "abc").headers["location"]

    claims = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                        audience="wealthos:upstox-login")
    other = seeded_db.query(User).filter_by(email="other@example.com").one()
    forged = jwt.encode({**claims, "sub": str(other.id)}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    assert "upstox=error" in _callback(client, forged).headers["location"]   # other user has no pending nonce


def test_an_expired_state_is_refused(client, auth, market, seeded_db):
    _save_app(client, auth)
    state = _login_state(client, auth)
    row = seeded_db.query(BrokerCredential).one()
    row.oauth_nonce_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    seeded_db.commit()
    assert "upstox=error" in _callback(client, state).headers["location"]


def test_upstox_refusing_the_code_is_reported(client, auth, market):
    _save_app(client, auth)
    r = _callback(client, _login_state(client, auth), code="bad-code")
    assert "upstox=error" in r.headers["location"] and "refused" in r.headers["location"]


def test_holdings_sync_imports_real_holdings_and_counts_the_rest(client, auth, market, seeded_db):
    _save_app(client, auth)
    _callback(client, _login_state(client, auth))
    body = client.post("/api/v1/me/brokers/upstox/sync", headers=auth).json()
    run = body["run"]
    assert run["status"] == "success" and run["holdings_seen"] == 2
    assert run["details"]["is_simulated"] is False and run["details"]["unknown_symbols_skipped"] == 1
    assert body["simulation_notice"] is None
    user = seeded_db.query(User).filter_by(email="investor@example.com").one()
    held = seeded_db.query(Holding).filter_by(user_id=user.id).all()
    assert [(h.asset.symbol, float(h.quantity)) for h in held] == [("RELIANCE", 5.0)]


def test_disconnect_drops_the_token(client, auth, market, seeded_db):
    _save_app(client, auth)
    _callback(client, _login_state(client, auth))
    body = client.delete("/api/v1/me/brokers/upstox", headers=auth).json()
    assert body["state"] == "not_connected"
    assert seeded_db.query(LinkedAccount).filter_by(provider="upstox").one().access_token_encrypted is None


def test_unsupported_brokers_say_so(client, auth, market):
    brokers = {b["broker"]: b for b in client.get("/api/v1/me/brokers", headers=auth).json()["brokers"]}
    assert brokers["upstox"]["supported"] is True
    assert all(not brokers[b]["supported"] and brokers[b]["reason"] for b in ("zerodha", "groww", "dhan"))


def test_the_sandbox_broker_is_off_unless_enabled(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "broker_sandbox_enabled", False)
    r = client.post("/api/v1/linked-accounts/start", headers=auth, json={"provider": "sandbox"})
    assert r.status_code == 404
    assert client.get("/api/v1/linked-accounts/providers").json()["providers"] == []


def test_password_change_and_account_deletion_need_the_password(client, auth, seeded_db):
    assert client.post("/api/v1/me/password", headers=auth, json={
        "current_password": "wrong-password", "new_password": "another-strong-one"}).status_code == 403
    assert client.post("/api/v1/me/password", headers=auth, json={
        "current_password": "a-strong-test-password", "new_password": "another-strong-one"}).json()["changed"]
    assert client.post("/api/v1/me/delete", headers=auth, json={"password": "nope"}).status_code == 403
    assert client.post("/api/v1/me/delete", headers=auth, json={"password": "another-strong-one"}).json()["deleted"]
    assert seeded_db.query(User).filter_by(email="investor@example.com").count() == 0


def test_the_cleanup_script_is_a_dry_run_by_default(seeded_db, capsys, registered_user):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_test_accounts.py"
    spec = importlib.util.spec_from_file_location("cleanup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    users, _ = module.plan(seeded_db)
    assert [u.email for u in users] == ["investor@example.com"]
    assert module.main([]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert seeded_db.query(User).count() == 1


def test_research_tools_report_unavailable_offline(client, auth, market):
    for path in ("/api/v1/markets/news", "/api/v1/markets/commodities", "/api/v1/markets/calendar"):
        r = client.get(path, headers=auth)
        assert r.status_code == 503 and r.json()["code"] == "market_data_unavailable", path
