"""Swing-model signals, the risk-profiled swing plan and the forward test."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.services import advisor_service, forward_test_service, paper_trading_service as paper
from app.services import signals_service

router = APIRouter(prefix="/signals", tags=["signals"])
advisor_router = APIRouter(prefix="/advisor", tags=["signals"])


def _tolerance(user) -> str | None:
    rt = getattr(user, "risk_tolerance", None)
    return getattr(rt, "value", rt)


@router.get("")
def signals(user: CurrentUser, limit: int = Query(20, ge=1, le=60)) -> dict:
    return signals_service.signals(_tolerance(user), limit)


@router.get("/regime")
def regime(user: CurrentUser) -> dict:
    return signals_service.regime()


@router.get("/leaderboard")
def leaderboard(user: CurrentUser, db: DbSession) -> dict:
    return forward_test_service.leaderboard(db)


@router.get("/{symbol}")
def signal_for(symbol: str, user: CurrentUser) -> dict:
    return signals_service.signal_for(symbol, _tolerance(user))


class PlanRequest(BaseModel):
    amount: float = Field(gt=0, le=1e9)


class PlanLeg(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: int = Field(ge=0, le=1_000_000)


class PlanExecute(BaseModel):
    positions: list[PlanLeg] = Field(min_length=1, max_length=advisor_service.MAX_LEGS)


@advisor_router.post("/swing-plan")
def swing_plan(payload: PlanRequest, user: CurrentUser, db: DbSession) -> dict:
    try:
        return advisor_service.swing_plan(db, user, payload.amount)
    except paper.OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@advisor_router.post("/swing-plan/execute", status_code=status.HTTP_201_CREATED)
def swing_plan_execute(payload: PlanExecute, user: CurrentUser, db: DbSession) -> dict:
    placed = advisor_service.execute(db, user, [leg.model_dump() for leg in payload.positions])
    return {"orders": [paper.order_dict(o) for o in placed]}
