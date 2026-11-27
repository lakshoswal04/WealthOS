"""Paper trading: place and cancel orders, read the account."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.services import paper_trading_service as paper

router = APIRouter(prefix="/paper", tags=["paper trading"])


class OrderIn(BaseModel):
    instrument: Literal["equity", "option"]
    symbol: str = Field(min_length=1, max_length=32, description="Stock, or the index for options")
    side: Literal["buy", "sell"]
    quantity: int | None = Field(default=None, gt=0, le=1_000_000)
    lots: int | None = Field(default=None, gt=0, le=500)
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = Field(default=None, gt=0)
    product: Literal["delivery", "intraday"] | None = None
    option_type: Literal["CE", "PE"] | None = None
    strike: float | None = Field(default=None, gt=0)
    expiry: str | None = None
    tag: str = Field(default="manual", max_length=48, pattern=r"^[a-z0-9:_-]+$")


class AutopilotPreview(BaseModel):
    amount: float = Field(gt=0, le=100_000_000)


class AutopilotLeg(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0, le=1_000_000)


class AutopilotExecute(BaseModel):
    basket: list[AutopilotLeg] = Field(min_length=1, max_length=15)
    amount: float | None = Field(default=None, gt=0, le=100_000_000)


@router.get("/portfolio")
def portfolio(user: CurrentUser, db: DbSession) -> dict:
    """Cash, holdings, positions and P&L. Fills any resting limit orders first."""
    return paper.portfolio(db, user)


@router.get("/orders")
def orders(user: CurrentUser, db: DbSession, limit: int = Query(200, ge=1, le=500)) -> dict:
    paper.process_open_orders(db, user)
    rows = paper.orders(db, user, limit)
    return {"orders": rows, "total": len(rows)}


@router.post("/orders", status_code=status.HTTP_201_CREATED)
def place(payload: OrderIn, user: CurrentUser, db: DbSession) -> dict:
    """Place a paper order. A rejected order is recorded and returned with its reason."""
    try:
        order = paper.place_order(db, user, **payload.model_dump())
    except paper.OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return paper.order_dict(order)


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: int, user: CurrentUser, db: DbSession) -> dict:
    try:
        order = paper.cancel_order(db, user, order_id)
    except paper.OrderRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return paper.order_dict(order)


@router.post("/reset")
def reset(user: CurrentUser, db: DbSession) -> dict:
    """Clear every order and position and restore the starting cash."""
    acct = paper.reset(db, user)
    return {"cash": float(acct.cash), "starting_cash": float(acct.starting_cash)}


@router.post("/autopilot/preview")
def autopilot_preview(payload: AutopilotPreview, user: CurrentUser, db: DbSession) -> dict:
    try:
        return paper.autopilot_preview(db, user, payload.amount)
    except paper.OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/autopilot", status_code=status.HTTP_201_CREATED)
def autopilot(payload: AutopilotExecute, user: CurrentUser, db: DbSession) -> dict:
    try:
        placed = paper.autopilot_execute(db, user, [leg.model_dump() for leg in payload.basket], payload.amount)
    except paper.OrderRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"orders": [paper.order_dict(o) for o in placed]}
