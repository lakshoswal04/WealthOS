"""Authentication, authorisation and account isolation."""

from __future__ import annotations


def test_register_returns_a_usable_token(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "new@example.com", "password": "a-strong-test-password",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"

    me = client.get("/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


def test_email_is_normalised_to_lowercase(client):
    client.post("/api/v1/auth/register", json={
        "email": "MiXeD@Example.com", "password": "a-strong-test-password",
    })
    # The same address in a different case must not create a second account.
    duplicate = client.post("/api/v1/auth/register", json={
        "email": "mixed@example.com", "password": "a-strong-test-password",
    })
    assert duplicate.status_code == 409


def test_duplicate_registration_is_rejected(client, registered_user):
    response = client.post("/api/v1/auth/register", json={
        "email": "investor@example.com", "password": "a-strong-test-password",
    })
    assert response.status_code == 409


def test_password_is_never_stored_or_returned(client, registered_user, seeded_db):
    from app.models import User

    user = seeded_db.query(User).filter_by(email="investor@example.com").one()
    assert user.hashed_password != "a-strong-test-password"
    assert user.hashed_password.startswith("$2b$")

    body = client.get("/api/v1/auth/me", headers=registered_user["headers"]).json()
    assert "password" not in body
    assert "hashed_password" not in body


def test_short_password_is_rejected(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "weak@example.com", "password": "short",
    })
    assert response.status_code == 422


def test_password_beyond_bcrypt_limit_is_rejected(client):
    # bcrypt truncates at 72 bytes. Accepting a longer password would let a
    # 72-byte prefix authenticate, so it is refused instead.
    response = client.post("/api/v1/auth/register", json={
        "email": "long@example.com", "password": "x" * 100,
    })
    assert response.status_code == 422


def test_login_succeeds_with_correct_credentials(client, registered_user):
    response = client.post("/api/v1/auth/login", json={
        "email": "investor@example.com", "password": "a-strong-test-password",
    })
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_does_not_reveal_whether_an_account_exists(client, registered_user):
    # Identical status and message for both cases, so the endpoint cannot be
    # used to enumerate registered addresses.
    wrong_password = client.post("/api/v1/auth/login", json={
        "email": "investor@example.com", "password": "wrong-password",
    })
    unknown_email = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "wrong-password",
    })

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


def test_protected_endpoints_require_a_token(client):
    for method, path in [
        ("get", "/api/v1/auth/me"),
        ("get", "/api/v1/portfolio"),
        ("get", "/api/v1/portfolio/holdings"),
        ("get", "/api/v1/portfolio/transactions"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_malformed_and_tampered_tokens_are_rejected(client, registered_user):
    good = registered_user["token"]
    for token in ["garbage", good[:-4] + "aaaa", "", good + "x"]:
        response = client.get("/api/v1/auth/me",
                              headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, token


def test_token_signed_with_another_key_is_rejected(client):
    # Proves the signature is actually verified, not just decoded.
    import jwt

    forged = jwt.encode({"sub": "1", "type": "access"}, "a-different-secret",
                        algorithm="HS256")
    response = client.get("/api/v1/auth/me",
                          headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_profile_can_be_updated(client, auth):
    response = client.patch("/api/v1/auth/me", headers=auth,
                            json={"risk_tolerance": "aggressive", "age": 41})
    assert response.status_code == 200
    assert response.json()["risk_tolerance"] == "aggressive"
    assert response.json()["age"] == 41


def test_profile_rejects_out_of_range_values(client, auth):
    assert client.patch("/api/v1/auth/me", headers=auth,
                        json={"age": 5}).status_code == 422
    assert client.patch("/api/v1/auth/me", headers=auth,
                        json={"annual_income": -1}).status_code == 422
    assert client.patch("/api/v1/auth/me", headers=auth,
                        json={"risk_tolerance": "reckless"}).status_code == 422
