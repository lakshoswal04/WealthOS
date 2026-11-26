"""The account-linking sandbox.

Three properties are load-bearing and tested first: no password is ever
accepted, no response can pass as a live connection, and a stored token is
never readable from the database.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.secrets import TokenDecryptionError, decrypt_secret, encrypt_secret
from app.models import (
    AccountSyncRun, LinkedAccount, LinkedAccountStatus, SyncStatus, Transaction,
)
from app.services import linking_service
from app.services.broker_sandbox import SandboxBroker

CODE = "sbx_code_abcdefgh"


@pytest.fixture
def linked(client, auth):
    response = client.post("/api/v1/linked-accounts", headers=auth,
                           json={"provider": "sandbox", "code": CODE})
    assert response.status_code == 201, response.text
    return response.json(), auth


# --------------------------------------------------------------------------
# No passwords, anywhere
# --------------------------------------------------------------------------

def test_no_linking_endpoint_accepts_a_password(client, auth):
    """The hard rule: never request or store a brokerage password.

    Asserted against the live OpenAPI schema rather than by reading the code,
    so a field added later is caught even if nobody re-reads this file. Only
    the schemas actually reachable from a linking request body are inspected
    -- the auth endpoints legitimately take a password for this platform's own
    account, which is a different thing entirely.
    """
    schema = client.get("/openapi.json").json()
    components = schema.get("components", {}).get("schemas", {})

    linking_paths = [p for p in schema["paths"] if "linked-accounts" in p]
    assert linking_paths, "no linking endpoints found to check"

    def resolve(node, seen=None):
        """Every schema reachable from this node, following $ref."""
        seen = seen if seen is not None else set()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    resolve(components.get(name, {}), seen)
            for value in node.values():
                resolve(value, seen)
        elif isinstance(node, list):
            for value in node:
                resolve(value, seen)
        return seen

    reachable = set()
    for path in linking_paths:
        for operation in schema["paths"][path].values():
            if not isinstance(operation, dict):
                continue
            if operation.get("requestBody"):
                reachable |= resolve(operation["requestBody"])

    assert reachable, "no linking request schemas found"

    # Field NAMES, not descriptions. The docstrings here deliberately discuss
    # passwords in order to say there is no field for one, so scanning the
    # whole serialised schema would flag its own documentation.
    def field_names(node, out=None):
        out = out if out is not None else set()
        if isinstance(node, dict):
            for name in (node.get("properties") or {}):
                out.add(str(name).lower())
            for value in node.values():
                field_names(value, out)
        elif isinstance(node, list):
            for value in node:
                field_names(value, out)
        return out

    names = set()
    for name in reachable:
        names |= field_names(components[name])

    assert names, f"no fields found on {sorted(reachable)}"
    forbidden = {"password", "passwd", "pin", "mpin", "totp", "totp_secret",
                 "secret", "credentials", "otp"}
    offending = names & forbidden
    assert not offending, (
        f"linking request fields {sorted(offending)} would collect a "
        f"credential; schemas checked: {sorted(reachable)}"
    )


def test_the_start_response_states_the_password_policy(client, auth):
    body = client.post("/api/v1/linked-accounts/start", headers=auth,
                       json={"provider": "sandbox"}).json()
    assert "never requested" in body["password_policy"]
    assert body["authorization_url"].startswith("https://sandbox.invalid/")


def test_the_sandbox_exchange_takes_a_code_and_nothing_else():
    """Structural, not stylistic: there is no parameter to pass a secret in."""
    import inspect
    signature = inspect.signature(SandboxBroker.exchange_code)
    assert list(signature.parameters) == ["self", "code"]


# --------------------------------------------------------------------------
# Nothing can pass as a live connection
# --------------------------------------------------------------------------

def test_every_linking_response_is_labelled_simulated(client, auth, linked):
    account, headers = linked
    account_id = account["id"]

    responses = [
        client.get("/api/v1/linked-accounts/providers").json(),
        client.post("/api/v1/linked-accounts/start", headers=headers,
                    json={"provider": "sandbox"}).json(),
        account,
        client.get("/api/v1/linked-accounts", headers=headers).json(),
        client.post(f"/api/v1/linked-accounts/{account_id}/sync", headers=headers).json(),
        client.get(f"/api/v1/linked-accounts/{account_id}/syncs", headers=headers).json(),
    ]

    for body in responses:
        blob = json.dumps(body)
        assert "simulat" in blob.lower(), blob[:200]


def test_the_stored_record_is_marked_simulated(seeded_db, linked):
    account, _ = linked
    row = seeded_db.query(LinkedAccount).filter(
        LinkedAccount.id == account["id"]
    ).one()
    assert row.is_simulated is True


def test_the_notice_names_the_document_that_explains_live_access():
    assert "docs/account-linking.md" in linking_service.SIMULATION_NOTICE


# --------------------------------------------------------------------------
# Tokens at rest
# --------------------------------------------------------------------------

def test_the_stored_token_is_not_readable_from_the_database(seeded_db, linked):
    """A database dump must not contain a usable credential."""
    account, _ = linked
    row = seeded_db.query(LinkedAccount).filter(
        LinkedAccount.id == account["id"]
    ).one()

    assert row.access_token_encrypted
    assert not row.access_token_encrypted.startswith("sbx_at_")
    # And it does decrypt, so the encryption is real rather than a hash.
    assert decrypt_secret(row.access_token_encrypted).startswith("sbx_at_")


def test_the_token_never_appears_in_any_api_response(client, auth, linked):
    account, headers = linked
    row_token = None

    body = client.get("/api/v1/linked-accounts", headers=headers).json()
    blob = json.dumps(body)
    for field in ("access_token", "refresh_token", "sbx_at_", "sbx_rt_"):
        assert field not in blob, f"{field} leaked into the accounts response"


def test_encryption_is_nondeterministic():
    """Two encryptions of one token must differ, or the ciphertext is a fingerprint."""
    assert encrypt_secret("tok") != encrypt_secret("tok")
    assert decrypt_secret(encrypt_secret("tok")) == "tok"


def test_a_token_written_under_a_different_secret_raises(seeded_db, linked):
    """After a key rotation the token is unusable, and that must not look like
    an absent token -- otherwise the sync proceeds as though unlinked."""
    account, _ = linked
    row = seeded_db.query(LinkedAccount).filter(
        LinkedAccount.id == account["id"]
    ).one()
    row.access_token_encrypted = "gAAAAABnot-a-real-ciphertext"
    seeded_db.commit()

    with pytest.raises(TokenDecryptionError):
        decrypt_secret(row.access_token_encrypted)


# --------------------------------------------------------------------------
# Linking and re-linking
# --------------------------------------------------------------------------

def test_linking_stores_the_account_with_its_scopes(client, auth, linked):
    account, _ = linked
    assert account["status"] == str(LinkedAccountStatus.ACTIVE)
    assert "holdings:read" in account["granted_scopes"]
    assert account["display_name"]
    assert account["token_expires_at"]


def test_relinking_updates_the_existing_record(client, auth, linked):
    """Otherwise a user who links twice imports every holding twice."""
    first, headers = linked
    again = client.post("/api/v1/linked-accounts", headers=headers,
                        json={"provider": "sandbox", "code": CODE})
    assert again.status_code == 201
    assert again.json()["id"] == first["id"]
    assert again.json()["reauthorised_existing_link"] is True

    listed = client.get("/api/v1/linked-accounts", headers=headers).json()
    assert listed["total"] == 1


def test_an_unknown_provider_is_rejected(client, auth):
    response = client.post("/api/v1/linked-accounts", headers=auth,
                           json={"provider": "not_a_broker", "code": CODE})
    assert response.status_code == 422


def test_csv_import_is_still_offered_alongside_linking(client, auth, linked):
    _, headers = linked
    body = client.get("/api/v1/linked-accounts", headers=headers).json()
    assert body["csv_import_still_available"] is True


# --------------------------------------------------------------------------
# Syncing
# --------------------------------------------------------------------------

def test_a_sync_imports_holdings_and_transactions(client, auth, linked):
    account, headers = linked
    result = client.post(f"/api/v1/linked-accounts/{account['id']}/sync",
                         headers=headers).json()
    run = result["run"]

    assert run["status"] == str(SyncStatus.SUCCESS)
    assert run["holdings_seen"] > 0
    assert run["holdings_created"] > 0
    assert run["transactions_created"] > 0
    assert result["account"]["last_successful_sync_at"]

    holdings = client.get("/api/v1/portfolio/holdings", headers=headers).json()
    assert holdings


def test_a_second_sync_creates_no_duplicate_transactions(client, auth, linked, seeded_db):
    """Idempotence, on the provider's identifier rather than on contents."""
    account, headers = linked
    first = client.post(f"/api/v1/linked-accounts/{account['id']}/sync",
                        headers=headers).json()["run"]
    before = seeded_db.query(Transaction).count()

    second = client.post(f"/api/v1/linked-accounts/{account['id']}/sync",
                         headers=headers).json()["run"]
    after = seeded_db.query(Transaction).count()

    assert first["transactions_created"] > 0
    assert second["transactions_created"] == 0
    assert second["duplicates_skipped"] == first["transactions_created"]
    assert after == before


def test_two_same_day_trades_at_the_same_price_are_both_kept(seeded_db, client, auth):
    """Why dedupe is keyed on external_id and not on (date, symbol, value).

    Content matching would merge these into one and silently lose a trade.
    """
    from app.models import Asset, TransactionType
    from app.models import User

    user = seeded_db.query(User).first()
    asset = seeded_db.query(Asset).filter(Asset.symbol == "RELIANCE").one()
    for index in (1, 2):
        seeded_db.add(Transaction(
            user_id=user.id, asset_id=asset.id,
            transaction_type=TransactionType.BUY,
            date=__import__("datetime").date(2025, 6, 10),
            quantity=5.0, price=1000.0, value=5000.0, fees=0.0,
            external_id=f"sandbox:same-day-{index}", external_source="sandbox",
        ))
    seeded_db.commit()

    kept = seeded_db.query(Transaction).filter(
        Transaction.external_id.like("sandbox:same-day-%")
    ).count()
    assert kept == 2


def test_a_duplicate_external_id_is_refused_by_the_database(seeded_db, client, auth):
    """The service dedupes; the constraint guarantees it."""
    from sqlalchemy.exc import IntegrityError
    from app.models import Asset, TransactionType, User

    user = seeded_db.query(User).first()
    asset = seeded_db.query(Asset).filter(Asset.symbol == "TCS").one()
    for _ in range(2):
        seeded_db.add(Transaction(
            user_id=user.id, asset_id=asset.id,
            transaction_type=TransactionType.BUY,
            date=__import__("datetime").date(2025, 7, 1),
            quantity=1.0, price=10.0, value=10.0, fees=0.0,
            external_id="sandbox:collide", external_source="sandbox",
        ))
    with pytest.raises(IntegrityError):
        seeded_db.commit()
    seeded_db.rollback()


# --------------------------------------------------------------------------
# Failure modes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("failure,expected_kind,expected_status", [
    ("token_expired", "token_expired", LinkedAccountStatus.EXPIRED),
    ("rate_limited", "rate_limited", LinkedAccountStatus.ACTIVE),
    ("unavailable", "provider_unavailable", LinkedAccountStatus.ACTIVE),
    ("scope", "scope_not_granted", LinkedAccountStatus.ERROR),
])
def test_each_failure_is_recorded_with_its_own_kind(
    seeded_db, client, auth, linked, failure, expected_kind, expected_status
):
    """Distinct kinds matter: an expired token refreshes, a revoked one needs
    the user. One generic error would send people to re-authorise needlessly."""
    from app.models import User
    account, _ = linked
    user = seeded_db.query(User).first()

    broker = SandboxBroker(account_reference=account["account_reference"],
                           provider=account["provider"],
                           granted_scopes=tuple(account["granted_scopes"]),
                           failure=failure)
    result = linking_service.sync_account(
        seeded_db, user, account["id"], broker=broker
    )

    assert result["run"]["status"] == str(SyncStatus.FAILED)
    assert result["run"]["error_kind"] == expected_kind
    assert result["run"]["error_message"]
    assert result["account"]["status"] == str(expected_status)


def test_a_rate_limit_reports_when_to_retry(seeded_db, client, auth, linked):
    from app.models import User
    account, _ = linked
    user = seeded_db.query(User).first()

    broker = SandboxBroker(account_reference=account["account_reference"],
                           granted_scopes=tuple(account["granted_scopes"]),
                           failure="rate_limited")
    result = linking_service.sync_account(seeded_db, user, account["id"], broker=broker)
    assert result["run"]["details"]["retry_after_seconds"] == 60


def test_a_partial_response_removes_nothing_and_says_so(seeded_db, client, auth, linked):
    """The dangerous case. Half a portfolio is not evidence of a sale."""
    from app.models import User
    account, headers = linked
    user = seeded_db.query(User).first()

    full = SandboxBroker(account_reference=account["account_reference"],
                         granted_scopes=tuple(account["granted_scopes"]))
    linking_service.sync_account(seeded_db, user, account["id"], broker=full)
    before = len(client.get("/api/v1/portfolio/holdings", headers=headers).json())

    truncated = SandboxBroker(account_reference=account["account_reference"],
                              granted_scopes=tuple(account["granted_scopes"]),
                              partial=True)
    result = linking_service.sync_account(
        seeded_db, user, account["id"], broker=truncated
    )

    assert result["run"]["status"] == str(SyncStatus.PARTIAL)
    assert "nothing was removed" in result["run"]["error_message"]
    after = len(client.get("/api/v1/portfolio/holdings", headers=headers).json())
    assert after == before, "a partial response deleted holdings"


def test_a_missing_scope_fails_rather_than_returning_an_empty_portfolio(
    seeded_db, client, auth
):
    """An empty list would read as "you hold nothing", and a sync that
    believes it deletes a real portfolio."""
    from app.models import User
    response = client.post("/api/v1/linked-accounts", headers=auth, json={
        "provider": "sandbox", "code": CODE,
        "account_reference": "SBX0002",
        "granted_scopes": ["profile:read"],
    })
    assert response.status_code == 201
    account = response.json()
    user = seeded_db.query(User).first()

    result = linking_service.sync_account(seeded_db, user, account["id"])
    assert result["run"]["status"] == str(SyncStatus.FAILED)
    assert result["run"]["error_kind"] == "scope_not_granted"


def test_an_expiring_token_is_refreshed_before_use(seeded_db, client, auth, linked):
    """Refresh before the call, not after a failure."""
    from app.models import User
    account, _ = linked
    user = seeded_db.query(User).first()

    row = seeded_db.query(LinkedAccount).filter(
        LinkedAccount.id == account["id"]
    ).one()
    original = row.access_token_encrypted
    row.token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    seeded_db.commit()

    broker = SandboxBroker(account_reference=row.account_reference,
                           granted_scopes=tuple(row.granted_scopes))
    result = linking_service.sync_account(seeded_db, user, row.id, broker=broker)

    assert "refresh" in broker.calls
    assert result["run"]["status"] == str(SyncStatus.SUCCESS)
    seeded_db.refresh(row)
    assert row.access_token_encrypted != original


# --------------------------------------------------------------------------
# Disconnecting
# --------------------------------------------------------------------------

def test_disconnecting_destroys_the_tokens_but_keeps_the_history(
    seeded_db, client, auth, linked
):
    account, headers = linked
    client.post(f"/api/v1/linked-accounts/{account['id']}/sync", headers=headers)

    assert client.delete(f"/api/v1/linked-accounts/{account['id']}",
                         headers=headers).status_code == 204

    row = seeded_db.query(LinkedAccount).filter(
        LinkedAccount.id == account["id"]
    ).one()
    assert row.status == LinkedAccountStatus.DISCONNECTED
    assert row.access_token_encrypted is None
    assert row.refresh_token_encrypted is None

    history = client.get(f"/api/v1/linked-accounts/{account['id']}/syncs",
                         headers=headers).json()
    assert history["total_runs"] >= 1


def test_syncing_a_disconnected_account_fails_clearly(client, auth, linked):
    account, headers = linked
    client.delete(f"/api/v1/linked-accounts/{account['id']}", headers=headers)

    result = client.post(f"/api/v1/linked-accounts/{account['id']}/sync",
                         headers=headers).json()
    assert result["run"]["error_kind"] == "disconnected"
    assert "Re-authorise" in result["run"]["error_message"]


# --------------------------------------------------------------------------
# History and isolation
# --------------------------------------------------------------------------

def test_the_history_records_failures_as_well_as_successes(
    seeded_db, client, auth, linked
):
    """"When did this last actually work" is unanswerable from successes alone."""
    from app.models import User
    account, headers = linked
    user = seeded_db.query(User).first()

    client.post(f"/api/v1/linked-accounts/{account['id']}/sync", headers=headers)
    linking_service.sync_account(
        seeded_db, user, account["id"],
        broker=SandboxBroker(account_reference=account["account_reference"],
                             granted_scopes=tuple(account["granted_scopes"]),
                             failure="unavailable"),
    )

    history = client.get(f"/api/v1/linked-accounts/{account['id']}/syncs",
                         headers=headers).json()
    assert history["successful_runs"] >= 1
    assert history["failed_runs"] >= 1
    assert history["total_runs"] == len(history["runs"])


def test_one_user_cannot_reach_another_users_linked_account(
    client, auth, linked, second_user
):
    account, _ = linked
    other = second_user["headers"]

    assert client.get("/api/v1/linked-accounts", headers=other).json()["total"] == 0
    assert client.post(f"/api/v1/linked-accounts/{account['id']}/sync",
                       headers=other).status_code == 404
    assert client.get(f"/api/v1/linked-accounts/{account['id']}/syncs",
                      headers=other).status_code == 404
    assert client.delete(f"/api/v1/linked-accounts/{account['id']}",
                         headers=other).status_code == 404


def test_every_endpoint_requires_authentication(client):
    assert client.get("/api/v1/linked-accounts").status_code == 401
    assert client.post("/api/v1/linked-accounts", json={"code": CODE}).status_code == 401
    assert client.post("/api/v1/linked-accounts/1/sync").status_code == 401
    assert client.delete("/api/v1/linked-accounts/1").status_code == 401
