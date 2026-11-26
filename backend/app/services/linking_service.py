"""Linking a (simulated) brokerage account and synchronising from it.

The integration layer is the real work here, and none of it needs a live
broker: authorisation, encrypted token storage, refresh on expiry,
incremental sync, duplicate suppression, and the handling of expiry, rate
limits, outages and partial responses. `broker_sandbox` stands in for the
provider; swapping it for a real client is a change of one dependency.

Three decisions worth stating.

**No passwords, ever.** The flow takes an authorisation code and exchanges
it for a token. There is no code path that accepts a brokerage password,
and no column to put one in.

**Partial responses never overwrite.** A broker returning half a portfolio
is the dangerous case: treating it as the truth would delete real holdings.
A partial sync updates what it saw and leaves everything else alone, and
records itself as `PARTIAL` so the user is not told it worked.

**Duplicates are suppressed on the provider's own identifier**, not on
(date, amount). Two genuine trades in the same stock on the same day at the
same price are two trades, and matching on their contents would silently
merge them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.secrets import (
    TokenDecryptionError, decrypt_secret, encrypt_secret,
)
from app.models import (
    Asset, AssetStatus, LinkedAccount, LinkedAccountStatus, AccountSyncRun,
    SyncStatus, Transaction, TransactionType, User,
)
from app.services import portfolio_service
from app.services.broker_sandbox import (
    SUPPORTED_PROVIDERS, BrokerError, ProviderUnavailable, RateLimited,
    SandboxBroker, ScopeNotGranted, TokenExpired,
)

__all__ = [
    "SIMULATION_NOTICE",
    "begin_link",
    "complete_link",
    "list_accounts",
    "sync_account",
    "disconnect",
    "sync_history",
]

# Repeated on every record and every response. The UI must never be able to
# present a sandbox link as a live brokerage connection, and the only way to
# guarantee that is for the notice to travel with the data.
SIMULATION_NOTICE = (
    "This is a simulated brokerage connection. No real account is linked and "
    "no live brokerage API is contacted; holdings and transactions are "
    "generated deterministically for demonstration. See "
    "docs/account-linking.md for what live access requires."
)

# A token inside this window of expiry is refreshed before use rather than
# after a failure, so an expiry mid-sync does not surface as an error.
REFRESH_MARGIN = timedelta(minutes=10)


def _broker(account: LinkedAccount | None = None, **overrides) -> SandboxBroker:
    if account is not None:
        return SandboxBroker(
            account_reference=account.account_reference,
            provider=account.provider,
            granted_scopes=tuple(account.granted_scopes or ()),
            **overrides,
        )
    return SandboxBroker(**overrides)


def _serialise(account: LinkedAccount) -> dict:
    return {
        "id": account.id,
        "provider": account.provider,
        "account_reference": account.account_reference,
        "display_name": account.display_name,
        "status": str(account.status),
        "granted_scopes": account.granted_scopes or [],
        "is_simulated": account.is_simulated,
        "token_expires_at": (
            account.token_expires_at.isoformat() if account.token_expires_at else None
        ),
        "last_successful_sync_at": (
            account.last_successful_sync_at.isoformat()
            if account.last_successful_sync_at else None
        ),
        "last_sync_error": account.last_sync_error,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "simulation_notice": SIMULATION_NOTICE,
    }


def _serialise_run(run: AccountSyncRun) -> dict:
    return {
        "id": run.id,
        "status": str(run.status),
        "trigger": run.trigger,
        "holdings_seen": run.holdings_seen,
        "holdings_created": run.holdings_created,
        "holdings_updated": run.holdings_updated,
        "transactions_seen": run.transactions_seen,
        "transactions_created": run.transactions_created,
        "duplicates_skipped": run.duplicates_skipped,
        "error_kind": run.error_kind,
        "error_message": run.error_message,
        "details": run.details,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------

def begin_link(provider: str, redirect_uri: str, state: str) -> dict:
    """Where the user would authorise, and what they would be granting.

    Returns a URL rather than following it. Nothing is contacted.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unknown provider {provider!r}; expected one of {SUPPORTED_PROVIDERS}"
        )
    broker = _broker(provider=provider) if provider != "sandbox" else _broker()
    broker.provider = provider
    return {
        "provider": provider,
        "authorization_url": broker.authorization_url(redirect_uri, state),
        "scopes_requested": list(broker.granted_scopes),
        "is_simulated": True,
        "simulation_notice": SIMULATION_NOTICE,
        "password_policy": (
            "Your brokerage password is never requested and could not be "
            "stored: the flow exchanges a short-lived authorisation code for "
            "a token, and there is no field for a password anywhere in it."
        ),
    }


def complete_link(
    db: Session,
    user: User,
    provider: str,
    code: str,
    account_reference: str = "SBX0001",
    granted_scopes: tuple[str, ...] | None = None,
) -> dict:
    """Exchange the authorisation code and store the link.

    Re-authorising an account that is already linked updates that row rather
    than inserting a second one. Without that, a user who links twice gets
    every holding imported twice.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")

    broker = _broker()
    broker.provider = provider
    broker.account_reference = account_reference
    if granted_scopes is not None:
        broker.granted_scopes = tuple(granted_scopes)

    tokens = broker.exchange_code(code)

    account = db.scalars(
        select(LinkedAccount).where(
            LinkedAccount.user_id == user.id,
            LinkedAccount.provider == provider,
            LinkedAccount.account_reference == tokens["account_reference"],
        )
    ).first()
    reauthorised = account is not None

    if account is None:
        account = LinkedAccount(
            user_id=user.id,
            provider=provider,
            account_reference=tokens["account_reference"],
        )
        db.add(account)

    account.display_name = tokens["display_name"]
    account.status = LinkedAccountStatus.ACTIVE
    account.access_token_encrypted = encrypt_secret(tokens["access_token"])
    account.refresh_token_encrypted = encrypt_secret(tokens["refresh_token"])
    account.token_expires_at = tokens["expires_at"]
    account.granted_scopes = tokens["granted_scopes"]
    account.is_simulated = True
    account.last_sync_error = None

    db.commit()
    db.refresh(account)

    payload = _serialise(account)
    payload["reauthorised_existing_link"] = reauthorised
    return payload


def list_accounts(db: Session, user: User) -> dict:
    rows = db.scalars(
        select(LinkedAccount)
        .where(LinkedAccount.user_id == user.id)
        .order_by(LinkedAccount.created_at.desc())
    ).all()
    return {
        "accounts": [_serialise(a) for a in rows],
        "total": len(rows),
        "all_simulated": all(a.is_simulated for a in rows),
        "simulation_notice": SIMULATION_NOTICE,
        "csv_import_still_available": True,
        "csv_import_note": (
            "CSV import remains a first-class way to load a portfolio and "
            "does not depend on any broker connection."
        ),
    }


def disconnect(db: Session, user: User, account_id: int) -> bool:
    """Unlink an account and destroy its stored tokens.

    The row is kept so the sync history remains readable, but the tokens are
    cleared: a disconnected account must not retain usable credentials.
    """
    account = db.scalars(
        select(LinkedAccount).where(
            LinkedAccount.id == account_id, LinkedAccount.user_id == user.id
        )
    ).first()
    if account is None:
        return False

    account.status = LinkedAccountStatus.DISCONNECTED
    account.access_token_encrypted = None
    account.refresh_token_encrypted = None
    account.token_expires_at = None
    db.commit()
    return True


# --------------------------------------------------------------------------
# Synchronisation
# --------------------------------------------------------------------------

def _usable_token(db: Session, account: LinkedAccount, broker: SandboxBroker) -> str:
    """Decrypt the access token, refreshing first if it is close to expiry.

    Refreshing before use rather than after a failure keeps an expiry from
    surfacing as a sync error the user has to act on.
    """
    if account.access_token_encrypted is None:
        raise TokenExpired("this account has no stored token; re-authorise it")

    expiring = (
        account.token_expires_at is not None
        and account.token_expires_at <= datetime.now(timezone.utc) + REFRESH_MARGIN
    )
    if expiring and account.refresh_token_encrypted:
        refreshed = broker.refresh(decrypt_secret(account.refresh_token_encrypted))
        account.access_token_encrypted = encrypt_secret(refreshed["access_token"])
        account.token_expires_at = refreshed["expires_at"]
        db.flush()

    return decrypt_secret(account.access_token_encrypted)


def sync_account(
    db: Session,
    user: User,
    account_id: int,
    trigger: str = "manual",
    broker: SandboxBroker | None = None,
) -> dict | None:
    """Pull holdings and transactions, and record the attempt either way.

    Every attempt produces an `AccountSyncRun`, including the failures. A
    history that shows only successes cannot answer "when did this last
    actually work", which is the question that matters when a figure looks
    stale.
    """
    account = db.scalars(
        select(LinkedAccount).where(
            LinkedAccount.id == account_id, LinkedAccount.user_id == user.id
        )
    ).first()
    if account is None:
        return None

    run = AccountSyncRun(
        linked_account_id=account.id, status=SyncStatus.FAILED, trigger=trigger
    )
    db.add(run)
    db.flush()

    if account.status == LinkedAccountStatus.DISCONNECTED:
        return _fail(db, account, run, "disconnected",
                     "This account is disconnected. Re-authorise it to sync.")

    client = broker if broker is not None else _broker(account)

    try:
        token = _usable_token(db, account, client)
        holdings_response = client.holdings(token)
        transactions_response = client.transactions(token, since=None)
    except TokenDecryptionError as exc:
        account.status = LinkedAccountStatus.REVOKED
        return _fail(db, account, run, "token_undecryptable", str(exc))
    except TokenExpired as exc:
        account.status = LinkedAccountStatus.EXPIRED
        return _fail(db, account, run, "token_expired", str(exc))
    except ScopeNotGranted as exc:
        account.status = LinkedAccountStatus.ERROR
        return _fail(db, account, run, "scope_not_granted", str(exc))
    except RateLimited as exc:
        return _fail(db, account, run, "rate_limited", str(exc),
                     details={"retry_after_seconds": exc.retry_after_seconds})
    except ProviderUnavailable as exc:
        return _fail(db, account, run, "provider_unavailable", str(exc))
    except BrokerError as exc:
        account.status = LinkedAccountStatus.ERROR
        return _fail(db, account, run, exc.kind, str(exc))

    holdings = holdings_response.get("holdings", [])
    partial = bool(holdings_response.get("partial"))

    known = {
        a.symbol.upper(): a
        for a in db.scalars(
            select(Asset).where(Asset.status == AssetStatus.ACTIVE)
        ).all()
    }

    created = updated = unknown = 0
    for row in holdings:
        asset = known.get(str(row["symbol"]).upper())
        if asset is None:
            unknown += 1
            continue
        _, is_new = portfolio_service.upsert_holding(
            db, user, asset, float(row["quantity"]),
            float(row["average_price"]), None,
        )
        db.flush()
        created += int(is_new)
        updated += int(not is_new)

    tx_rows = transactions_response.get("transactions", [])
    tx_created, duplicates = _store_transactions(db, user, account, tx_rows, known)

    run.status = SyncStatus.PARTIAL if partial else SyncStatus.SUCCESS
    run.holdings_seen = len(holdings)
    run.holdings_created = created
    run.holdings_updated = updated
    run.transactions_seen = len(tx_rows)
    run.transactions_created = tx_created
    run.duplicates_skipped = duplicates
    run.finished_at = datetime.now(timezone.utc)
    run.details = {
        "is_simulated": True,
        "unknown_symbols_skipped": unknown,
        "partial_response": partial,
        "simulation_notice": SIMULATION_NOTICE,
    }
    if partial:
        run.error_kind = "partial_response"
        run.error_message = (
            "The provider returned only part of the portfolio. Holdings it "
            "did return were updated; nothing was removed, because a partial "
            "response is not evidence that a position was closed."
        )

    account.last_successful_sync_at = run.finished_at
    account.last_sync_error = run.error_message
    account.status = LinkedAccountStatus.ACTIVE
    db.commit()
    db.refresh(run)
    db.refresh(account)

    return {
        "account": _serialise(account),
        "run": _serialise_run(run),
        "simulation_notice": SIMULATION_NOTICE,
    }


def _store_transactions(
    db: Session, user: User, account: LinkedAccount,
    rows: list[dict], known: dict[str, Asset],
) -> tuple[int, int]:
    """Insert transactions not already stored, keyed on the provider's id.

    Matching on (date, symbol, value) would merge two genuine same-day trades
    into one, so `Transaction.external_id` holds the provider's own
    identifier and the dedupe is exact. A unique constraint on
    (user_id, external_id) backs it up, so a bug in this query becomes an
    error rather than a duplicated portfolio.
    """
    already = {
        row.external_id
        for row in db.scalars(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.external_id.isnot(None),
            )
        ).all()
    }

    created = duplicates = 0
    for row in rows:
        asset = known.get(str(row["symbol"]).upper())
        if asset is None:
            continue

        external_id = f"{account.provider}:{row['external_id']}"
        if external_id in already:
            duplicates += 1
            continue
        already.add(external_id)

        db.add(Transaction(
            user_id=user.id, asset_id=asset.id,
            transaction_type=(
                TransactionType.BUY if row["side"] == "buy"
                else TransactionType.SELL
            ),
            date=date.fromisoformat(row["date"]),
            quantity=float(row["quantity"]),
            price=float(row["price"]), value=float(row["value"]), fees=0.0,
            external_id=external_id,
            external_source=account.provider,
        ))
        created += 1
    db.flush()
    return created, duplicates


def _fail(
    db: Session, account: LinkedAccount, run: AccountSyncRun,
    kind: str, message: str, details: dict | None = None,
) -> dict:
    run.status = SyncStatus.FAILED
    run.error_kind = kind
    run.error_message = message[:512]
    run.finished_at = datetime.now(timezone.utc)
    run.details = {"is_simulated": True, **(details or {})}
    account.last_sync_error = message[:512]
    db.commit()
    db.refresh(run)
    db.refresh(account)
    return {
        "account": _serialise(account),
        "run": _serialise_run(run),
        "simulation_notice": SIMULATION_NOTICE,
    }


def sync_history(db: Session, user: User, account_id: int, limit: int = 20) -> dict | None:
    account = db.scalars(
        select(LinkedAccount).where(
            LinkedAccount.id == account_id, LinkedAccount.user_id == user.id
        )
    ).first()
    if account is None:
        return None

    runs = db.scalars(
        select(AccountSyncRun)
        .where(AccountSyncRun.linked_account_id == account.id)
        .order_by(AccountSyncRun.started_at.desc())
        .limit(limit)
    ).all()

    successful = [r for r in runs if r.status == SyncStatus.SUCCESS]
    return {
        "account": _serialise(account),
        "runs": [_serialise_run(r) for r in runs],
        "total_runs": len(runs),
        "successful_runs": len(successful),
        "failed_runs": sum(1 for r in runs if r.status == SyncStatus.FAILED),
        "partial_runs": sum(1 for r in runs if r.status == SyncStatus.PARTIAL),
        "simulation_notice": SIMULATION_NOTICE,
    }
