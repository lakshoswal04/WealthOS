"""Autopilot (a model-run paper sleeve), the review of real holdings, and amount planning."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.services import autopilot_service as ap
from app.services import paper_trading_service as paper

router = APIRouter(tags=["autopilot"])


class SettingsUpdate(BaseModel):
    enabled: bool | None = None
    budget: float | None = Field(default=None, gt=0, le=100_000_000)
    cadence_sessions: int | None = None
    avoid_symbols: list[str] | None = Field(default=None, max_length=50)
    avoid_sectors: list[str] | None = Field(default=None, max_length=20)


class AllocateRequest(BaseModel):
    amount: float = Field(gt=0, le=100_000_000)
    sectors: list[str] | None = Field(default=None, max_length=12)
    horizon: Literal["swing", "long_term"] = "swing"


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/autopilot")
def status(user: CurrentUser, db: DbSession) -> dict:
    return ap.status(db, user)


@router.put("/autopilot/settings")
def update(payload: SettingsUpdate, user: CurrentUser, db: DbSession) -> dict:
    try:
        return ap.update_settings(db, user, **payload.model_dump(exclude_none=True))
    except ap.AutopilotError as exc:
        raise _bad(exc) from None


@router.get("/autopilot/preview")
def preview(user: CurrentUser, db: DbSession) -> dict:
    """The orders the next rebalance would place, without placing them."""
    try:
        return ap.plan_trades(db, user)
    except ap.AutopilotError as exc:
        raise _bad(exc) from None


@router.post("/autopilot/run")
def run_now(user: CurrentUser, db: DbSession) -> dict:
    try:
        return ap.rebalance(db, user, mode="manual")
    except (ap.AutopilotError, paper.OrderRejected) as exc:
        raise _bad(exc) from None


@router.post("/autopilot/stop")
def stop(user: CurrentUser, db: DbSession, sell: bool = True) -> dict:
    return ap.stop(db, user, sell=sell)


@router.get("/autopilot/runs")
def runs(user: CurrentUser, db: DbSession, limit: int = Query(20, ge=1, le=100)) -> dict:
    return {"runs": ap.runs(db, user, limit)}


@router.get("/portfolio/review")
def review(user: CurrentUser, db: DbSession) -> dict:
    return ap.review_holdings(db, user)


@router.post("/advisor/allocate")
def allocate(payload: AllocateRequest, user: CurrentUser, db: DbSession) -> dict:
    try:
        return ap.allocate(db, user, payload.amount, payload.sectors, payload.horizon)
    except ap.AutopilotError as exc:
        raise _bad(exc) from None
