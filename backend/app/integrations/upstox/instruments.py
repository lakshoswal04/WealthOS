"""The Upstox instrument master: real instrument keys, expiries and lot sizes.

A public file (no login needed), refreshed by Upstox around 06:00 IST daily.
It is cached on disk per day, so the API downloads it at most once a day.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings

log = logging.getLogger("wealthos.upstox.instruments")
IST = ZoneInfo("Asia/Kolkata")

MASTER_URLS = {
    "NSE": "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "BSE": "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz",
}

INDEX_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
    "INDIAVIX": "NSE_INDEX|India VIX",
}
OPTION_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")


class InstrumentsUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Contract:
    instrument_key: str
    underlying: str
    instrument_type: str      # CE | PE | FUT
    expiry: date
    strike: float
    lot_size: int
    trading_symbol: str


def _expiry(value) -> date:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=IST).date()
    return date.fromisoformat(str(value)[:10])


class Master:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: date | None = None
        self.equity_keys: dict[str, str] = {}
        self.contracts: dict[tuple, Contract] = {}          # (und, expiry, strike, type)
        self.by_key: dict[str, Contract] = {}
        self.expiries: dict[str, list[date]] = {}
        self.futures: dict[str, list[Contract]] = {}       # underlying -> by expiry
        self.strikes: dict[tuple, list[float]] = {}         # (und, expiry) -> sorted

    @property
    def _dir(self) -> Path:
        return settings.data_dir / "external" / "upstox"

    def _load_raw(self, exchange: str, today: date) -> list[dict]:
        path = self._dir / f"{exchange}-{today.isoformat()}.json.gz"
        if not path.exists():
            if not settings.live_market_enabled:
                raise InstrumentsUnavailable("Live data is disabled, so the instrument master is not fetched.")
            try:
                response = httpx.get(MASTER_URLS[exchange], timeout=30.0, follow_redirects=True)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise InstrumentsUnavailable(f"The Upstox instrument list could not be downloaded ({exc}).") from exc
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            for old in self._dir.glob(f"{exchange}-*.json.gz"):
                if old != path:
                    old.unlink(missing_ok=True)
        with gzip.open(path) as fh:
            return json.load(fh)

    def load_records(self, records: list[dict]) -> None:
        """Index raw master records (also how tests install a fixture)."""
        equity, contracts, by_key, futures = {}, {}, {}, {}
        for r in records:
            seg, itype = r.get("segment"), r.get("instrument_type")
            if seg == "NSE_EQ" and itype == "EQ":
                equity[r["trading_symbol"]] = r["instrument_key"]
            elif itype in ("CE", "PE", "FUT") and seg in ("NSE_FO", "BSE_FO"):
                und = r.get("underlying_symbol")
                if seg == "BSE_FO" and und != "SENSEX":
                    continue
                c = Contract(r["instrument_key"], und, itype, _expiry(r["expiry"]),
                             float(r.get("strike_price") or 0), int(r.get("lot_size") or 1),
                             r.get("trading_symbol", ""))
                by_key[c.instrument_key] = c
                if itype == "FUT":
                    futures.setdefault(und, []).append(c)
                else:
                    contracts[(und, c.expiry, c.strike, itype)] = c
        expiries: dict[str, set] = {}
        strikes: dict[tuple, set] = {}
        for (und, exp, strike, _), _c in contracts.items():
            expiries.setdefault(und, set()).add(exp)
            strikes.setdefault((und, exp), set()).add(strike)
        with self._lock:
            self.equity_keys, self.contracts, self.by_key = equity, contracts, by_key
            self.futures = {k: sorted(v, key=lambda c: c.expiry) for k, v in futures.items()}
            self.expiries = {k: sorted(v) for k, v in expiries.items()}
            self.strikes = {k: sorted(v) for k, v in strikes.items()}

    def ensure(self) -> None:
        today = datetime.now(IST).date()
        if self._day == today and self.by_key:
            return
        with self._lock:
            if self._day == today and self.by_key:
                return
        records = self._load_raw("NSE", today) + self._load_raw("BSE", today)
        self.load_records(records)
        self._day = today
        log.info("instrument master loaded: %d contracts, %d equities", len(self.by_key), len(self.equity_keys))

    # ---- lookups -------------------------------------------------------

    def key_for(self, symbol: str) -> str | None:
        self.ensure()
        symbol = symbol.upper()
        return INDEX_KEYS.get(symbol) or self.equity_keys.get(symbol)

    def expiries_for(self, underlying: str, today: date | None = None) -> list[date]:
        self.ensure()
        today = today or datetime.now(IST).date()
        return [d for d in self.expiries.get(underlying, []) if d >= today]

    def lot_size(self, underlying: str) -> int | None:
        self.ensure()
        for (und, *_), c in self.contracts.items():
            if und == underlying:
                return c.lot_size
        return None

    def contract(self, underlying: str, expiry: date, strike: float, option_type: str) -> Contract | None:
        self.ensure()
        return self.contracts.get((underlying, expiry, float(strike), option_type))

    def strikes_for(self, underlying: str, expiry: date) -> list[float]:
        self.ensure()
        return self.strikes.get((underlying, expiry), [])

    def near_future(self, underlying: str, today: date | None = None) -> Contract | None:
        self.ensure()
        today = today or datetime.now(IST).date()
        live = [c for c in self.futures.get(underlying, []) if c.expiry >= today]
        return live[0] if live else None


master = Master()
