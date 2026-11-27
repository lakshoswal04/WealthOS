"""News, calendar, corporate actions, commodities, pairs and strategy tools."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentFeed, CurrentUser
from app.services import research_service as research

router = APIRouter(tags=["research tools"])


def _guard(call):
    try:
        return call()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/markets/news")
def news(user: CurrentUser, symbol: str | None = None, limit: int = Query(40, ge=1, le=100)) -> dict:
    return _guard(lambda: research.news(symbol, limit))


@router.get("/markets/calendar")
def calendar(user: CurrentUser, days: int = Query(60, ge=1, le=180)) -> dict:
    return research.calendar(days)


@router.get("/markets/events/{symbol}")
def events(symbol: str, user: CurrentUser) -> dict:
    return _guard(lambda: research.stock_events(symbol))


@router.get("/markets/commodities")
def commodities(user: CurrentUser) -> dict:
    return research.commodities()


@router.get("/tools/pairs")
def pair(user: CurrentUser, a: str = Query(..., max_length=20), b: str = Query(..., max_length=20),
         lookback: int = Query(250, ge=90, le=500)) -> dict:
    return _guard(lambda: research.pair(a, b, lookback))


@router.get("/tools/pairs/screen")
def pair_screen(user: CurrentUser, min_correlation: float = Query(0.7, ge=0.3, le=0.99),
                min_abs_z: float = Query(1.5, ge=0.5, le=4)) -> dict:
    return research.pair_screen(min_correlation, min_abs_z)


class Leg(BaseModel):
    option_type: Literal["CE", "PE"]
    strike: float = Field(gt=0)
    action: Literal["buy", "sell"]
    lots: int = Field(default=1, ge=1, le=50)


class PayoffIn(BaseModel):
    underlying: str = Field(max_length=16)
    expiry: str | None = None
    legs: list[Leg] = Field(min_length=1, max_length=6)


@router.post("/tools/strategy/payoff")
def payoff(payload: PayoffIn, user: CurrentUser, feed: CurrentFeed) -> dict:
    return _guard(lambda: research.payoff(feed, payload.underlying, payload.expiry,
                                          [leg.model_dump() for leg in payload.legs]))


@router.get("/tools/strategy/wizard")
def wizard(user: CurrentUser, feed: CurrentFeed, underlying: str = "NIFTY",
           view: Literal["bullish", "bearish", "neutral", "volatile"] = "bullish",
           expiry: str | None = None) -> dict:
    return _guard(lambda: research.wizard(feed, underlying, view, expiry))
