"""Linking a simulated brokerage account.

Every response from this router carries `is_simulated: true` and a
`simulation_notice`. That is not decoration. A screen that presented a
sandbox link as a live brokerage connection would be misleading a user about
where their money is, so the notice travels with the data rather than living
only in the UI.

No endpoint here accepts a password. The flow exchanges a short-lived
authorisation code for a token, and there is no field for a password in any
request model.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.services import linking_service
from app.services.broker_sandbox import SUPPORTED_PROVIDERS, SANDBOX_SCOPES

router = APIRouter(tags=["account linking"])


class LinkStartRequest(BaseModel):
    """Where to send the user to authorise.

    Note what is absent: there is no password field, and adding one would be
    a change this docstring is here to make conspicuous.
    """

    provider: str = Field(default="sandbox", description="A simulated provider")
    redirect_uri: str = Field(
        default="http://localhost:3000/accounts/callback",
        description="Where the provider would return the user",
    )


class LinkCompleteRequest(BaseModel):
    provider: str = Field(default="sandbox")
    code: str = Field(min_length=8, description="The authorisation code, not a password")
    account_reference: str = Field(default="SBX0001", max_length=64)
    granted_scopes: list[str] | None = Field(
        default=None,
        description=(
            "Scopes the user granted. Omit for all of them. Granting fewer "
            "makes the corresponding sync fail loudly rather than return an "
            "empty portfolio, which would read as 'you hold nothing'."
        ),
    )


@router.get("/linked-accounts/providers")
def providers() -> dict:
    """The simulated providers, and what live access would require."""
    return {
        "providers": list(SUPPORTED_PROVIDERS),
        "scopes": list(SANDBOX_SCOPES),
        "all_simulated": True,
        "simulation_notice": linking_service.SIMULATION_NOTICE,
        "live_access_requirements": (
            "A live connection needs a registered developer application with "
            "the broker, an approved redirect URI, and in most cases a paid "
            "API subscription. See docs/account-linking.md for the per-broker "
            "detail."
        ),
    }


@router.post("/linked-accounts/start")
def start(payload: LinkStartRequest, user: CurrentUser) -> dict:
    """Begin authorisation. Returns a URL; nothing is contacted."""
    try:
        result = linking_service.begin_link(
            payload.provider, payload.redirect_uri, secrets.token_urlsafe(16)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return result


@router.post("/linked-accounts", status_code=status.HTTP_201_CREATED)
def complete(payload: LinkCompleteRequest, user: CurrentUser, db: DbSession) -> dict:
    """Exchange the authorisation code and store the link.

    Re-authorising an account already linked updates that record rather than
    creating a second one, so a user who links twice does not get every
    holding imported twice.
    """
    try:
        return linking_service.complete_link(
            db, user, payload.provider, payload.code,
            account_reference=payload.account_reference,
            granted_scopes=(
                tuple(payload.granted_scopes)
                if payload.granted_scopes is not None else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/linked-accounts")
def list_linked(user: CurrentUser, db: DbSession) -> dict:
    """Linked accounts, with the last time each one actually synced."""
    return linking_service.list_accounts(db, user)


@router.post("/linked-accounts/{account_id}/sync")
def sync(
    account_id: int,
    user: CurrentUser,
    db: DbSession,
    trigger: str = Query(default="manual", pattern="^(manual|scheduled)$"),
) -> dict:
    """Pull holdings and transactions now.

    Returns the sync run whatever happened, including failures. A partial
    response from the provider updates what it returned and removes nothing,
    and reports itself as `partial` rather than as success.
    """
    result = linking_service.sync_account(db, user, account_id, trigger=trigger)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Linked account not found"
        )
    return result


@router.get("/linked-accounts/{account_id}/syncs")
def history(
    account_id: int,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Every sync attempt for this account, successes and failures alike."""
    result = linking_service.sync_history(db, user, account_id, limit=limit)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Linked account not found"
        )
    return result


@router.delete("/linked-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(account_id: int, user: CurrentUser, db: DbSession) -> None:
    """Unlink an account and destroy its stored tokens.

    The record is kept so the sync history stays readable, but the tokens are
    cleared: a disconnected account must not retain usable credentials.
    """
    if not linking_service.disconnect(db, user, account_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Linked account not found"
        )
