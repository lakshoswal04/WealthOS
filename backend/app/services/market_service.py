"""Access to market prices.

The full price panel is about 232,000 rows, which is small enough to hold in
memory as a wide DataFrame. Doing so turns every analytics request into a
slice of an in-process frame instead of a database round trip, which is what
keeps the risk endpoints inside the sub-second budget the PRD sets.
"""

from __future__ import annotations

import threading
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, MarketPrice


class MarketDataCache:
    """Process-wide cache of the adjusted price panel.

    Market prices are reference data: identical for every user and updated
    only by the data pipeline, so a shared cache cannot leak anything
    between accounts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._panel: pd.DataFrame | None = None
        self._assets: pd.DataFrame | None = None

    def load(self, db: Session, force: bool = False) -> None:
        """Read prices and asset metadata into memory."""
        with self._lock:
            if self._panel is not None and not force:
                return

            rows = db.execute(
                select(Asset.symbol, MarketPrice.date, MarketPrice.close)
                .join(MarketPrice, MarketPrice.asset_id == Asset.id)
                .order_by(MarketPrice.date)
            ).all()

            frame = pd.DataFrame(rows, columns=["symbol", "date", "close"])
            if frame.empty:
                self._panel = pd.DataFrame()
            else:
                frame["date"] = pd.to_datetime(frame["date"])
                self._panel = frame.pivot(index="date", columns="symbol", values="close").sort_index()

            assets = db.execute(
                select(
                    Asset.symbol, Asset.name, Asset.asset_class,
                    Asset.sector, Asset.status, Asset.price_source,
                )
            ).all()
            self._assets = pd.DataFrame(
                assets,
                columns=["symbol", "name", "asset_class", "sector", "status", "price_source"],
            ).set_index("symbol")

    @property
    def is_loaded(self) -> bool:
        return self._panel is not None

    def panel(self, db: Session) -> pd.DataFrame:
        """Wide price frame: dates as the index, symbols as columns."""
        self.load(db)
        return self._panel if self._panel is not None else pd.DataFrame()

    def assets(self, db: Session) -> pd.DataFrame:
        self.load(db)
        return self._assets if self._assets is not None else pd.DataFrame()

    def latest_prices(self, db: Session, symbols: list[str] | None = None) -> pd.Series:
        """Most recent available price per symbol.

        Uses the last non-null observation per column rather than the final
        row, so an asset that did not trade on the panel's last date still
        returns its true latest price instead of NaN.
        """
        panel = self.panel(db)
        if panel.empty:
            return pd.Series(dtype="float64")

        columns = [s for s in (symbols or panel.columns) if s in panel.columns]
        if not columns:
            return pd.Series(dtype="float64")
        return panel[columns].ffill().iloc[-1]

    def latest_date(self, db: Session) -> date | None:
        panel = self.panel(db)
        if panel.empty:
            return None
        return panel.index.max().date()

    def price_history(
        self,
        db: Session,
        symbols: list[str],
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Price history for a set of symbols over an optional date range."""
        panel = self.panel(db)
        if panel.empty:
            return pd.DataFrame()

        columns = [s for s in symbols if s in panel.columns]
        if not columns:
            return pd.DataFrame(index=panel.index)

        window = panel[columns]
        if start is not None:
            window = window[window.index >= pd.Timestamp(start)]
        if end is not None:
            window = window[window.index <= pd.Timestamp(end)]
        return window

    def returns(
        self,
        db: Session,
        symbols: list[str],
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Daily simple returns for a set of symbols."""
        history = self.price_history(db, symbols, start, end)
        if history.empty:
            return history
        return history.pct_change().iloc[1:]

    def sector_map(self, db: Session) -> dict[str, str]:
        assets = self.assets(db)
        if assets.empty:
            return {}
        return assets["sector"].fillna("Unknown").to_dict()

    def asset_class_map(self, db: Session) -> dict[str, str]:
        assets = self.assets(db)
        if assets.empty:
            return {}
        return assets["asset_class"].to_dict()

    def invalidate(self) -> None:
        with self._lock:
            self._panel = None
            self._assets = None


market_cache = MarketDataCache()
