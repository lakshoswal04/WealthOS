"""Quotes, index strip, movers, candles and instrument search.

Prices come from the user's Upstox session when connected (live), otherwise
from Yahoo (delayed). Nothing is simulated: a symbol no source can price is
reported as unavailable.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentFeed, CurrentUser
from app.services import live_market_service as live

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("/status")
def status(user: CurrentUser, feed: CurrentFeed) -> dict:
    """The NSE session clock, and where this user's prices come from."""
    return {**live.market_status(),
            "price_source": "live" if feed.connected else "delayed",
            "upstox": {"connected": feed.connected, "state": feed.state, "reason": feed.reason}}


@router.get("/indices")
def indices(user: CurrentUser, feed: CurrentFeed) -> dict:
    """The ticker strip: NIFTY, SENSEX, BANKNIFTY, MIDCPNIFTY, FINNIFTY, INDIA VIX."""
    strip = live.index_strip(feed)
    if not strip:
        raise live.MarketDataUnavailable("Index prices are unavailable right now.")
    return {"market": live.market_status(), "indices": strip}


@router.get("/quotes")
def quotes(user: CurrentUser, feed: CurrentFeed,
           symbols: str = Query(..., max_length=2000, description="Comma-separated symbols")) -> dict:
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()][:120]
    got = live.get_quotes(wanted, feed)
    return {"quotes": [q.to_dict() for q in got.values()],
            "unavailable": [s for s in wanted if s not in got]}


@router.get("/quote/{symbol}")
def quote(symbol: str, user: CurrentUser, feed: CurrentFeed) -> dict:
    if live.instrument_info(symbol) is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the tradable universe")
    return live.require_quote(symbol, feed).to_dict()


@router.get("/movers")
def movers(user: CurrentUser, feed: CurrentFeed, kind: Literal["gainers", "losers", "movers"] = "gainers",
           limit: int = Query(10, ge=1, le=50)) -> dict:
    stocks = live.movers(kind, limit, feed)
    if not stocks:
        raise live.MarketDataUnavailable("Stock prices are unavailable right now.")
    return {"kind": kind, "stocks": stocks, "market": live.market_status()}


@router.get("/candles/{symbol}")
def candles(symbol: str, user: CurrentUser, feed: CurrentFeed, interval: str = "1m",
            range: str = "1D") -> dict:
    try:
        return live.get_candles(symbol, interval, range, feed)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the tradable universe") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/search")
def search(user: CurrentUser, q: str = Query("", max_length=40)) -> dict:
    return {"results": live.search(q)}


@router.get("/universe")
def universe(user: CurrentUser) -> dict:
    return {"indices": [live.instrument_info(k) for k in live.INDICES],
            "stocks": live.universe().to_dict(orient="records")}
