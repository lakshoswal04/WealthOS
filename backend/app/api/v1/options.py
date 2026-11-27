"""Index option chains, open interest and futures, from the user's Upstox session.

Without a session every endpoint answers 409 with code ``upstox_required``
and the reason; there is no modelled fallback.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentFeed, CurrentUser
from app.services import options_service as opt

router = APIRouter(prefix="/options", tags=["options"])


def _guard(call):
    try:
        return call()
    except (opt.UnknownUnderlying, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/expiries/{underlying}")
def expiries(underlying: str, user: CurrentUser) -> dict:
    """Listed expiries, from the public Upstox instrument list (no login needed)."""
    return _guard(lambda: {"underlying": underlying.upper(), "expiries": opt.list_expiries(underlying),
                           "lot_size": opt.lot_size(underlying)})


@router.get("/chain/{underlying}")
def chain(underlying: str, user: CurrentUser, feed: CurrentFeed, expiry: str | None = None,
          strikes: int = Query(15, ge=3, le=60)) -> dict:
    return _guard(lambda: opt.chain(feed, underlying, expiry, strikes))


@router.get("/summary/{underlying}")
def summary(underlying: str, user: CurrentUser, feed: CurrentFeed, expiry: str | None = None) -> dict:
    return _guard(lambda: opt.summary(feed, underlying, expiry))


@router.get("/multi-strike/{underlying}")
def multi_strike(underlying: str, user: CurrentUser, feed: CurrentFeed,
                 strikes: str = Query(..., max_length=200), expiry: str | None = None) -> dict:
    try:
        wanted = [float(s) for s in strikes.split(",") if s.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="strikes must be numbers") from None
    return _guard(lambda: opt.multi_strike_oi(feed, underlying, wanted, expiry))


@router.get("/crossovers/{underlying}")
def crossovers(underlying: str, user: CurrentUser, feed: CurrentFeed, expiry: str | None = None) -> dict:
    return _guard(lambda: opt.oi_crossovers(feed, underlying, expiry))


@router.get("/unusual")
def unusual(user: CurrentUser, feed: CurrentFeed, limit: int = Query(15, ge=1, le=50)) -> dict:
    return _guard(lambda: opt.unusual_activity(feed, limit))


@router.get("/candles/{underlying}")
def option_candles(underlying: str, user: CurrentUser, feed: CurrentFeed, strike: float = Query(..., gt=0),
                   option_type: Literal["CE", "PE"] = "CE", expiry: str | None = None,
                   interval: Literal["1m", "5m", "15m"] = "1m", range: Literal["1D", "5D"] = "1D") -> dict:
    return _guard(lambda: opt.option_candles(feed, underlying, expiry, strike, option_type, interval, range))


@router.get("/top")
def top(user: CurrentUser, feed: CurrentFeed, segment: Literal["options", "futures"] = "options",
        kind: Literal["gainers", "losers", "movers"] = "gainers",
        limit: int = Query(10, ge=1, le=50)) -> dict:
    rows = opt.top_options(feed, kind, limit) if segment == "options" else opt.top_futures(feed, kind, limit)
    return {"segment": segment, "kind": kind, "contracts": rows, "source": "live", "note": opt.DATA_NOTE}


@router.get("/heatmap")
def heatmap(user: CurrentUser, feed: CurrentFeed) -> dict:
    return opt.fno_heatmap(feed)
