"""The account menu: preferences, notifications, AI memory, broker APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from urllib.parse import quote_plus

from fastapi.responses import RedirectResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import Memory
from app.services import account_service as acct
from app.services import broker_service

router = APIRouter(prefix="/me", tags=["account"])


def _guard(call):
    try:
        return call()
    except acct.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


class SettingsPatch(BaseModel):
    preferences: dict[str, Any] | None = None
    notifications: dict[str, bool] | None = None


class MemoryIn(BaseModel):
    section: str = Field(min_length=1, max_length=24)
    text: str = Field(min_length=1, max_length=280)


class MemorySwitch(BaseModel):
    paused: bool


@router.get("/prompt-book")
def prompt_book(user: CurrentUser, lang: str = "en") -> dict:
    from app.content.prompt_book import book

    return book(lang)


@router.get("/settings")
def get_settings(user: CurrentUser, db: DbSession) -> dict:
    return acct.settings_dict(acct.settings_row(db, user))


@router.patch("/settings")
def patch_settings(payload: SettingsPatch, user: CurrentUser, db: DbSession) -> dict:
    return _guard(lambda: acct.update_settings(db, user, payload.preferences, payload.notifications))


@router.get("/memory")
def get_memory(user: CurrentUser, db: DbSession) -> dict:
    return {"paused": acct.settings_row(db, user).memory_paused, "sections": acct.MEMORY_SECTIONS,
            "memories": [acct.memory_dict(m) for m in acct.memories(db, user)]}


@router.post("/memory", status_code=status.HTTP_201_CREATED)
def add_memory(payload: MemoryIn, user: CurrentUser, db: DbSession) -> dict:
    return acct.memory_dict(_guard(lambda: acct.add_memory(db, user, payload.section, payload.text)))


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: int, user: CurrentUser, db: DbSession) -> None:
    row = db.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    db.delete(row)
    db.commit()


@router.put("/memory/state")
def memory_state(payload: MemorySwitch, user: CurrentUser, db: DbSession) -> dict:
    row = acct.settings_row(db, user)
    row.memory_paused = payload.paused
    db.commit()
    return {"paused": row.memory_paused}


# --------------------------------------------------------------------------
# Brokers (Upstox): app credentials, OAuth login, holdings sync
# --------------------------------------------------------------------------

class UpstoxAppIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=256)
    api_secret: str = Field(min_length=1, max_length=256)


def _broker_guard(call):
    try:
        return call()
    except broker_service.BrokerSetupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/brokers")
def list_brokers(user: CurrentUser, db: DbSession) -> dict:
    return {"brokers": broker_service.brokers(db, user),
            "note": "Your API key and secret are encrypted at rest and never shown again. Upstox's "
                    "daily access token reads market data and holdings only; orders stay on paper."}


@router.put("/brokers/upstox")
def save_upstox(payload: UpstoxAppIn, user: CurrentUser, db: DbSession) -> dict:
    return _broker_guard(lambda: broker_service.save_app_credentials(db, user, payload.api_key, payload.api_secret))


@router.post("/brokers/upstox/login")
def upstox_login(user: CurrentUser, db: DbSession) -> dict:
    """The Upstox authorise URL for this user; the browser goes there next."""
    return _broker_guard(lambda: broker_service.begin_login(db, user))


@router.post("/brokers/upstox/sync")
def upstox_sync(user: CurrentUser, db: DbSession) -> dict:
    """Import real Upstox holdings into Portfolio → Analysis."""
    return _broker_guard(lambda: broker_service.sync_holdings(db, user))


@router.delete("/brokers/upstox")
def upstox_disconnect(user: CurrentUser, db: DbSession, forget: bool = False) -> dict:
    return broker_service.disconnect(db, user, forget_credentials=forget)


# --------------------------------------------------------------------------
# Account
# --------------------------------------------------------------------------

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AccountDelete(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.post("/password")
def change_password(payload: PasswordChange, user: CurrentUser, db: DbSession) -> dict:
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=403, detail="The current password is wrong.")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"changed": True}


@router.post("/delete")
def delete_account(payload: AccountDelete, user: CurrentUser, db: DbSession) -> dict:
    """Delete the account and everything it owns (cascades). Irreversible."""
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="The password is wrong.")
    db.delete(user)
    db.commit()
    return {"deleted": True}


# --------------------------------------------------------------------------
# The Upstox redirect target (public: the signed `state` authenticates it)
# --------------------------------------------------------------------------

callback_router = APIRouter(tags=["account"])


@callback_router.get("/brokers/upstox/callback")
def upstox_callback(db: DbSession, code: str | None = None, state: str | None = None,
                    error: str | None = None) -> RedirectResponse:
    target = settings.frontend_url.rstrip("/") + "/settings/brokers"
    if error or not code or not state:
        message = error or "Upstox did not return a login code."
        return RedirectResponse(f"{target}?upstox=error&message={quote_plus(message)}", status_code=303)
    try:
        broker_service.complete_login(db, state, code)
    except broker_service.BrokerSetupError as exc:
        return RedirectResponse(f"{target}?upstox=error&message={quote_plus(str(exc))}", status_code=303)
    return RedirectResponse(f"{target}?upstox=connected", status_code=303)
