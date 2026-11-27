"""Keep the analytics price table (``market_prices``) current.

The seeded table stops on the day the pipeline last ran, so portfolio
values, risk, health and insights drift out of date. After every session
close this appends each asset's new daily closes.

New levels are **chained by returns** onto the last stored level:
``level_t = level_last * (yahoo_t / yahoo_last)``. Appending Yahoo's adjusted
closes directly would break the series at every dividend, because Yahoo
re-adjusts its history while the stored series keeps the old adjustment.
Chaining also continues the documented splices: NIFTY50 continues on
``^NSEI`` and DEBT on ``GILT5YBEES.NS``. CASH is a modelled 5.5% a year
accrual (its ``price_source`` says so) and keeps accruing at that rate.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Asset, MarketPrice
from app.services import live_market_service as live

log = logging.getLogger("wealthos.prices")

SPECIAL_TICKERS = {"NIFTY50": "^NSEI", "DEBT": "GILT5YBEES.NS"}
CASH_RATE = 0.055

Fetcher = Callable[[list[str], date], pd.DataFrame]
_lock = threading.Lock()


def _reference_tickers() -> dict[str, str]:
    path = settings.reference_dir / "universe.csv"
    if not path.exists():
        return {}
    ref = pd.read_csv(path)
    return {r.symbol: r.yahoo_symbol for r in ref.itertuples() if isinstance(r.yahoo_symbol, str) and r.yahoo_symbol}


def ticker_for(asset: Asset, reference: dict[str, str]) -> str | None:
    if asset.symbol in SPECIAL_TICKERS:
        return SPECIAL_TICKERS[asset.symbol]
    if asset.asset_class == "cash":
        return None
    return reference.get(asset.symbol) or f"{asset.symbol}.NS"


def yahoo_closes(tickers: list[str], start: date) -> pd.DataFrame:
    """Adjusted daily closes, dates x tickers."""
    import yfinance as yf

    raw = yf.download(tickers, start=start.isoformat(), interval="1d", auto_adjust=True,
                      progress=False, threads=True, group_by="ticker")
    out = {}
    for t in tickers:
        if t in raw.columns.get_level_values(0):
            s = raw[t]["Close"].dropna()
            if not s.empty:
                out[t] = s
    frame = pd.DataFrame(out)
    if not frame.empty:
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame


def last_complete_session() -> date:
    """The latest session whose daily bar is final (16:00 IST rule)."""
    return live.last_close_time().date()


def refresh(db: Session, fetch: Fetcher = yahoo_closes, until: date | None = None) -> dict:
    """Append new closes for every asset; returns counts per outcome."""
    with _lock:
        until = until or last_complete_session()
        assets = db.execute(select(Asset)).scalars().all()
        last = dict(db.execute(select(MarketPrice.asset_id, func.max(MarketPrice.date))
                               .group_by(MarketPrice.asset_id)).all())
        reference = _reference_tickers()
        stale = [a for a in assets if a.id in last and last[a.id] < until]
        if not stale:
            return {"added": 0, "assets_updated": 0, "up_to": str(until)}

        tickers = sorted({t for a in stale if (t := ticker_for(a, reference))})
        start = min(last[a.id] for a in stale) - timedelta(days=10)
        closes = fetch(tickers, start) if tickers else pd.DataFrame()

        added, updated, missing = 0, 0, []
        for asset in stale:
            anchor_date = last[asset.id]
            anchor_level = db.scalar(select(MarketPrice.close).where(MarketPrice.asset_id == asset.id,
                                                                     MarketPrice.date == anchor_date))
            if anchor_level is None:
                continue
            rows: list[tuple[date, float]] = []
            if asset.asset_class == "cash" and asset.symbol not in SPECIAL_TICKERS:
                d = anchor_date
                for day in pd.bdate_range(anchor_date + timedelta(days=1), until):
                    days = (day.date() - d).days
                    anchor_level *= (1 + CASH_RATE) ** (days / 365.0)
                    d = day.date()
                    rows.append((d, float(anchor_level)))
            else:
                t = ticker_for(asset, reference)
                if t is None or t not in closes:
                    missing.append(asset.symbol)
                    continue
                series = closes[t].dropna()
                base = series.loc[:pd.Timestamp(anchor_date)]
                if base.empty:
                    missing.append(asset.symbol)
                    continue
                base_value = float(base.iloc[-1])
                for day, value in series.loc[pd.Timestamp(anchor_date) + pd.Timedelta(days=1):pd.Timestamp(until)].items():
                    rows.append((day.date(), float(anchor_level) * float(value) / base_value))
            for d, level in rows:
                db.add(MarketPrice(asset_id=asset.id, date=d, close=round(level, 6)))
            if rows:
                added += len(rows)
                updated += 1
        db.commit()
        if added:
            from app.services.market_service import market_cache

            market_cache.load(db, force=True)
        log.info("price refresh: %d rows for %d assets up to %s; no data for %s", added, updated, until, missing)
        return {"added": added, "assets_updated": updated, "up_to": str(until), "missing": missing}
