"""Adding analysable assets on demand.

The analytics universe began as the 58 assets the models were trained on.
A real broker sync can bring in any NIFTY 100 stock; rather than skip it,
the asset is registered and its real daily closes (from the universe file
written by ml/pipelines/p12_fetch_universe) are loaded, so risk, health and
the rest can include it. Symbols outside the NIFTY 100 are still skipped and
counted in the sync run, never guessed at.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, MarketPrice
from app.services import live_market_service as live
from app.services.market_service import market_cache

log = logging.getLogger("wealthos.market.seed")


def ensure_assets(db: Session, symbols: list[str]) -> list[str]:
    """Register any NIFTY 100 symbols not yet in `assets`. Returns those added."""
    wanted = {s.upper() for s in symbols if s}
    if not wanted:
        return []
    existing = set(db.scalars(select(Asset.symbol).where(Asset.symbol.in_(wanted))))
    missing = wanted - existing
    universe = live.universe().set_index("symbol")
    added = []
    for symbol in sorted(missing):
        if symbol not in universe.index:
            continue
        history = live.daily_store.history(symbol)
        if history is None or history.empty:
            continue
        row = universe.loc[symbol]
        asset = Asset(symbol=symbol, name=str(row["name"]), asset_class="equity",
                      sector=str(row["sector"]), status="active", price_source="yahoo_adj_close",
                      note="Added when a linked broker account held it; two years of daily history.")
        db.add(asset)
        db.flush()
        db.bulk_insert_mappings(MarketPrice, [
            {"asset_id": asset.id, "date": ts.date(), "close": float(close)}
            for ts, close in history["close"].items() if close and close > 0
        ])
        added.append(symbol)
    if added:
        db.commit()
        market_cache.invalidate()
        log.info("registered %d assets from a broker sync: %s", len(added), ", ".join(added))
    return added
