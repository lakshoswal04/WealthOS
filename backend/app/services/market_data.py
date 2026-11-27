"""Per-user market data: Upstox when the user has connected it.

`feed_for(db, user)` returns a `Feed`. With a valid Upstox session it serves
real-time quotes, the real option chain (OI, Greeks, IV), option and futures
candles, and margin. Without one, `connected` is False and `reason` says why
-- equities and indices then fall back to Yahoo's delayed prices, and every
option or futures surface shows that reason instead of a number.

Caches are keyed by user, so one user's broker data is never served to
another.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd

from app.integrations.upstox.client import TokenInvalid, UpstoxClient, UpstoxError
from app.integrations.upstox.instruments import Contract, master

REASONS = {
    "no_credentials": "Connect your Upstox account (Settings → Broker APIs) to see live option chains, OI and futures.",
    "not_connected": "Log in to Upstox (Settings → Broker APIs) to see live option chains, OI and futures.",
    "expired": "Your Upstox session has expired (sessions end at 03:30 IST daily). Log in to Upstox again.",
}


class OptionsUnavailable(RuntimeError):
    """Option or futures data was asked for without a working Upstox session."""

    def __init__(self, reason: str, state: str):
        super().__init__(reason)
        self.state = state


_cache: dict[tuple, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: tuple, ttl: float, load: Callable[[], Any]) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = load()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache(user_id: int | None = None) -> None:
    with _lock:
        for k in [k for k in _cache if user_id is None or k[0] == user_id]:
            _cache.pop(k, None)


UPSTOX_INTERVALS = {"1m": ("minutes", 1), "5m": ("minutes", 5), "15m": ("minutes", 15),
                    "1h": ("hours", 1), "1D": ("days", 1)}


def candles_to_frame(candles: list[list], with_oi: bool = False) -> pd.DataFrame:
    """Upstox candle arrays -> OHLCV(+OI) frame indexed by IST timestamp, oldest first."""
    cols = ["time", "open", "high", "low", "close", "volume", "oi"]
    if not candles:
        return pd.DataFrame(columns=cols[1:] if with_oi else cols[1:6])
    frame = pd.DataFrame([c[:7] + [0] * (7 - len(c[:7])) for c in candles], columns=cols)
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame.set_index("time").sort_index()
    return frame if with_oi else frame.drop(columns=["oi"])


@dataclass
class Feed:
    user_id: int
    state: str                                   # connected | expired | not_connected | no_credentials
    token: str | None = None
    on_expired: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def connected(self) -> bool:
        return self.state == "connected" and self.token is not None

    @property
    def reason(self) -> str | None:
        return None if self.connected else REASONS.get(self.state, REASONS["not_connected"])

    def require(self) -> UpstoxClient:
        if not self.connected:
            raise OptionsUnavailable(self.reason, self.state)
        return UpstoxClient(self.token)

    def _call(self, fn: Callable[[UpstoxClient], Any]) -> Any:
        client = self.require()
        try:
            return fn(client)
        except TokenInvalid:
            self.state, self.token = "expired", None
            if self.on_expired:
                self.on_expired()
            clear_cache(self.user_id)
            raise OptionsUnavailable(REASONS["expired"], "expired") from None

    # ---- quotes ----------------------------------------------------------

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Raw Upstox quotes for symbols (equities and indices), keyed by symbol."""
        keys = {master.key_for(s): s for s in symbols}
        keys.pop(None, None)
        if not keys:
            return {}
        cache_key = (self.user_id, "quotes", tuple(sorted(keys)))
        raw = _cached(cache_key, 5.0, lambda: self._call(lambda c: c.quotes(list(keys))))
        return {keys[k]: v for k, v in raw.items() if k in keys}

    def contract_quotes(self, contracts: list[Contract]) -> dict[str, dict]:
        if not contracts:
            return {}
        keys = sorted({c.instrument_key for c in contracts})
        return _cached((self.user_id, "cquotes", tuple(keys)), 5.0,
                       lambda: self._call(lambda c: c.quotes(keys)))

    # ---- options ----------------------------------------------------------

    def option_chain(self, underlying: str, expiry: date) -> list[dict]:
        from app.integrations.upstox.instruments import INDEX_KEYS

        key = INDEX_KEYS[underlying]
        return _cached((self.user_id, "chain", underlying, expiry.isoformat()), 10.0,
                       lambda: self._call(lambda c: c.option_chain(key, expiry.isoformat())))

    # ---- candles ------------------------------------------------------------

    def candles(self, instrument_key: str, interval: str, days: int, with_oi: bool = False) -> pd.DataFrame:
        """Bars covering the last `days` sessions, today's included."""
        unit, n = UPSTOX_INTERVALS[interval]

        def load() -> pd.DataFrame:
            today = datetime.now().date()
            frames = []
            if unit != "days":
                frames.append(candles_to_frame(self._call(lambda c: c.intraday_candles(instrument_key, unit, n)), True))
            if days > 1 or unit == "days" or frames[0].empty:
                span = max(days * 2, 7) if days <= 7 else int(days * 1.45) + 5
                # Upstox serves at most a month of 1-15 minute bars and a
                # quarter of longer intraday bars per request.
                if unit == "minutes" and n <= 15:
                    span = min(span, 28)
                elif unit in ("minutes", "hours"):
                    span = min(span, 88)
                start = today - timedelta(days=span)
                hist = self._call(lambda c: c.historical_candles(
                    instrument_key, unit, n, (today - timedelta(days=1)).isoformat(), start.isoformat()))
                frames.insert(0, candles_to_frame(hist, True))
            frame = pd.concat([f for f in frames if not f.empty]) if any(not f.empty for f in frames) else frames[0]
            frame = frame[~frame.index.duplicated(keep="last")].sort_index()
            if unit != "days" and not frame.empty:
                keep = sorted(set(frame.index.date))[-days:]
                frame = frame[pd.Index(frame.index.date).isin(keep)]
            return frame

        ttl = 600.0 if unit == "days" else 20.0
        frame = _cached((self.user_id, "candles", instrument_key, interval, days), ttl, load)
        return frame if with_oi else frame.drop(columns=["oi"], errors="ignore")

    # ---- margin ----------------------------------------------------------------

    def margin(self, instrument_key: str, quantity: int, side: str, product: str = "D") -> float:
        body = [{"instrument_key": instrument_key, "quantity": int(quantity),
                 "transaction_type": side.upper(), "product": product}]
        data = self._call(lambda c: c.margin(body))
        return float(data.get("final_margin") or data.get("required_margin") or 0.0)


def feed_for(db, user) -> Feed:
    from app.services import broker_service

    token, state = broker_service.access_token(db, user)

    def expired() -> None:
        try:
            broker_service.mark_expired(db, user)
        except Exception:
            pass

    return Feed(user_id=user.id, state=state, token=token, on_expired=expired)


def offline_feed(user_id: int = 0, state: str = "not_connected") -> Feed:
    return Feed(user_id=user_id, state=state)


__all__ = ["Feed", "OptionsUnavailable", "feed_for", "offline_feed", "candles_to_frame",
           "UpstoxError", "REASONS"]
