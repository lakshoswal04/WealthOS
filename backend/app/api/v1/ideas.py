"""Rule-based trade ideas and the strategy library."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentFeed, CurrentUser, DbSession
from app.services import ideas_service

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.get("/recommendations")
def recommendations(user: CurrentUser, db: DbSession, feed: CurrentFeed,
                    kind: Literal["intraday", "delivery", "fno", "model"] = "delivery",
                    limit: int = Query(8, ge=1, le=20)) -> dict:
    return ideas_service.recommendations(db, kind, limit, feed)


@router.get("/strategies")
def strategies(user: CurrentUser,
               style: Literal["intraday", "swing", "positional"] | None = None) -> dict:
    return {"strategies": ideas_service.list_strategies(style)}


@router.get("/backtest/{strategy_id}")
def backtest(strategy_id: str, user: CurrentUser, symbol: str | None = None,
             years: float = Query(2.0, ge=0.5, le=2.0)) -> dict:
    try:
        return ideas_service.backtest(strategy_id, symbol, years)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
