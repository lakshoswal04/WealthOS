"""Quotes and candles for stocks and indices.

Two real sources, nothing invented:

* **Upstox** (``source: "live"``), when the requesting user has connected
  their account -- passed in as a ``feed`` (see ``market_data``).
* **Yahoo Finance** (``source: "delayed"``), about fifteen minutes behind
  NSE, for everyone else.

If neither answers, a symbol is simply absent and callers raise
``MarketDataUnavailable`` with the reason. There is no simulated fallback.

Caching follows stale-while-revalidate: the first request blocks on one
batched download of the whole universe (about two seconds); after that a
stale cache is served immediately while a background thread refreshes it.
A ticker strip polling every few seconds therefore never waits on Yahoo.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.core.config import settings

log = logging.getLogger("wealthos.market.live")

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = (9, 15)
SESSION_MINUTES = 375

# key -> (Yahoo ticker, display name). The order is the ticker strip's order.
INDICES: dict[str, tuple[str, str]] = {
    "NIFTY": ("^NSEI", "NIFTY 50"),
    "SENSEX": ("^BSESN", "SENSEX"),
    "BANKNIFTY": ("^NSEBANK", "NIFTY BANK"),
    "MIDCPNIFTY": ("NIFTY_MID_SELECT.NS", "NIFTY MIDCAP SELECT"),
    "FINNIFTY": ("NIFTY_FIN_SERVICE.NS", "NIFTY FIN SERVICE"),
    "INDIAVIX": ("^INDIAVIX", "INDIA VIX"),
}



class MarketDataUnavailable(RuntimeError):
    """No real source could supply the data asked for."""


# --------------------------------------------------------------------------
# Market clock
# --------------------------------------------------------------------------

def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_day(day: date) -> bool:
    """Weekdays. Exchange holidays are not modelled; Yahoo simply has no bar."""
    return day.weekday() < 5


def last_session_date(now: datetime | None = None) -> date:
    """The most recent day with a session that has at least opened."""
    now = now or now_ist()
    day = now.date()
    opened = (now.hour, now.minute) >= SESSION_OPEN
    if is_trading_day(day) and opened:
        return day
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def minute_of_session(now: datetime | None = None) -> int:
    """Minutes since 09:15 on the latest session, capped at the close."""
    now = now or now_ist()
    if last_session_date(now) != now.date():
        return SESSION_MINUTES
    elapsed = (now.hour - SESSION_OPEN[0]) * 60 + now.minute - SESSION_OPEN[1]
    return int(min(max(elapsed, 0), SESSION_MINUTES))


def market_status(now: datetime | None = None) -> dict:
    now = now or now_ist()
    minute = (now.hour - SESSION_OPEN[0]) * 60 + now.minute - SESSION_OPEN[1]
    is_open = is_trading_day(now.date()) and 0 <= minute < SESSION_MINUTES
    return {
        "is_open": is_open,
        "label": "Market open" if is_open else "Market closed",
        "session_date": str(last_session_date(now)),
        "minute_of_session": minute_of_session(now),
        "as_of": now.isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# Universe
# --------------------------------------------------------------------------

def _reference_path() -> Path:
    return settings.reference_dir / "nifty100.csv"


def _daily_path() -> Path:
    return settings.processed_dir / "universe_daily.parquet"


_universe_cache: pd.DataFrame | None = None


def universe() -> pd.DataFrame:
    """symbol, name, sector for the NIFTY 100 stocks."""
    global _universe_cache
    if _universe_cache is None:
        path = _reference_path()
        _universe_cache = (
            pd.read_csv(path) if path.exists()
            else pd.DataFrame(columns=["symbol", "name", "sector"])
        )
    return _universe_cache


def instrument_info(symbol: str) -> dict | None:
    symbol = symbol.upper()
    if symbol in INDICES:
        return {"symbol": symbol, "name": INDICES[symbol][1], "kind": "index", "sector": "Index"}
    row = universe()[universe()["symbol"] == symbol]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"symbol": symbol, "name": str(r["name"]), "kind": "equity", "sector": str(r["sector"])}


def all_symbols() -> list[str]:
    return list(INDICES) + list(universe()["symbol"])


def yahoo_ticker(symbol: str) -> str:
    return INDICES[symbol][0] if symbol in INDICES else f"{symbol}.NS"


def search(query: str, limit: int = 12) -> list[dict]:
    q = query.strip().upper()
    if not q:
        return []
    out = []
    for sym in all_symbols():
        info = instrument_info(sym)
        if info and (q in sym or q in info["name"].upper()):
            out.append(info)
    out.sort(key=lambda i: (not i["symbol"].startswith(q), i["symbol"]))
    return out[:limit]


# --------------------------------------------------------------------------
# Daily history (the universe parquet written by ml/pipelines/p12)
# --------------------------------------------------------------------------

def last_close_time(now: datetime | None = None) -> datetime:
    """When the most recent session's daily bar became final (16:00 IST).

    Yahoo finalises the NSE daily bar some time after the 15:30 close; 16:00
    leaves a margin. Holidays are not modelled, so a holiday triggers one
    harmless extra refresh.
    """
    now = now or now_ist()
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    day = close if now >= close else close - timedelta(days=1)
    while not is_trading_day(day.date()):
        day -= timedelta(days=1)
    return day


class _DailyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: pd.DataFrame | None = None
        self._mtime: float | None = None
        self._fetching = False
        self._last_attempt = 0.0
        self._complete_last = None

    def frame(self) -> pd.DataFrame | None:
        path = _daily_path()
        if not path.exists():
            self._maybe_fetch_in_background()
            return None
        mtime = path.stat().st_mtime
        if mtime < last_close_time().timestamp():
            # Written before the latest session closed: refresh in the
            # background and serve the file we have meanwhile.
            self._maybe_fetch_in_background()
        with self._lock:
            if self._frame is None or self._mtime != mtime:
                frame = pd.read_parquet(path)
                frame["date"] = pd.to_datetime(frame["date"])
                counts = frame.groupby("date")["symbol"].nunique()
                complete = counts[counts >= max(20, int(counts.max() * 0.8))] if not counts.empty else counts
                self._complete_last = complete.index.max().date() if not complete.empty else None
                self._frame, self._mtime = frame, mtime
            frame = self._frame
        # Yahoo sometimes serves a session's bars late. If the newest session
        # most stocks have is older than the last close, try again (the
        # attempt cooldown keeps this to one download per 15 minutes).
        if self._complete_last is not None and self._complete_last < last_close_time().date():
            self._maybe_fetch_in_background()
        return frame

    def history(self, symbol: str) -> pd.DataFrame | None:
        frame = self.frame()
        if frame is None:
            return None
        one = frame[frame["symbol"] == symbol]
        return None if one.empty else one.set_index("date").sort_index()

    def _maybe_fetch_in_background(self) -> None:
        """A fresh deploy has no universe file; build it rather than stay empty."""
        if not settings.live_market_enabled or self._fetching:
            return
        # One attempt per 15 minutes: a Yahoo outage must not mean a download
        # on every request.
        if time.monotonic() - self._last_attempt < 900:
            return
        self._last_attempt = time.monotonic()
        self._fetching = True

        def run() -> None:
            try:
                frame = download_daily(all_symbols(), period="2y")
                if not frame.empty:
                    _daily_path().parent.mkdir(parents=True, exist_ok=True)
                    frame.to_parquet(_daily_path(), index=False)
                    log.info("built universe daily history: %d rows", len(frame))
            except Exception as exc:  # network trouble must not crash a request
                log.warning("universe daily fetch failed: %s", exc)
            finally:
                self._fetching = False

        threading.Thread(target=run, daemon=True).start()


daily_store = _DailyStore()


def download_daily(symbols: list[str], period: str) -> pd.DataFrame:
    """Daily OHLCV from Yahoo, long format."""
    import yfinance as yf

    tickers = {yahoo_ticker(s): s for s in symbols}
    raw = yf.download(list(tickers), period=period, interval="1d", group_by="ticker",
                      auto_adjust=True, progress=False, threads=True)
    frames = []
    level0 = set(raw.columns.get_level_values(0)) if not raw.empty else set()
    for ticker, symbol in tickers.items():
        if ticker not in level0:
            continue
        one = raw[ticker].dropna(subset=["Close"]).copy()
        if one.empty:
            continue
        one.columns = [c.lower() for c in one.columns]
        one["symbol"] = symbol
        one.index.name = "date"
        frames.append(one.reset_index()[["date", "symbol", "open", "high", "low", "close", "volume"]])
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
    return out


# --------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------

@dataclass
class Quote:
    symbol: str
    name: str
    kind: str
    sector: str | None
    ltp: float
    prev_close: float
    change: float
    change_pct: float
    open: float
    high: float
    low: float
    volume: float
    source: str
    as_of: str

    def to_dict(self) -> dict:
        return asdict(self)


class YahooProvider:
    """Yahoo Finance: delayed NSE/BSE prices. The test suite swaps this out."""

    name = "delayed"

    def fetch_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not settings.live_market_enabled:
            return {}
        import yfinance as yf

        tickers = {yahoo_ticker(s): s for s in symbols}
        raw = yf.download(list(tickers), period="5d", interval="1d", group_by="ticker",
                          auto_adjust=False, progress=False, threads=True)
        now = now_ist()
        out: dict[str, Quote] = {}
        level0 = set(raw.columns.get_level_values(0)) if not raw.empty else set()
        for ticker, symbol in tickers.items():
            if ticker not in level0:
                continue
            bars = raw[ticker].dropna(subset=["Close"])
            if len(bars) < 2:
                continue
            last, prev = bars.iloc[-1], bars.iloc[-2]
            out[symbol] = make_quote(
                symbol, float(last["Close"]), float(prev["Close"]), float(last["Open"]),
                float(last["High"]), float(last["Low"]),
                float(last["Volume"]) if not math.isnan(last["Volume"]) else 0.0, "delayed", now)
        return out

    def fetch_candles(self, symbol: str, interval: str, range_: str, days: int) -> pd.DataFrame | None:
        if not settings.live_market_enabled:
            return None
        import yfinance as yf

        yahoo_interval = INTERVALS[interval][0]
        # Yahoo honours named periods for daily bars; "366d" comes back padded.
        daily_period = {"1D": "5d", "5D": "5d", "1M": "1mo", "3M": "3mo", "1Y": "1y", "5Y": "5y"}[range_]
        period = f"{days}d" if interval != "1D" else daily_period
        hist = yf.Ticker(yahoo_ticker(symbol)).history(period=period, interval=yahoo_interval, auto_adjust=False)
        if hist.empty:
            return None
        hist = hist.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        if interval != "1D":
            hist.index = hist.index.tz_convert(IST)
            keep = sorted(set(hist.index.date))[-days:]
            hist = hist[np.isin(hist.index.date, keep)]
        return hist


def make_quote(symbol: str, ltp: float, prev_close: float, open_: float, high: float, low: float,
               volume: float, source: str, now: datetime) -> Quote:
    info = instrument_info(symbol) or {"name": symbol, "kind": "equity", "sector": None}
    return Quote(
        symbol=symbol, name=info["name"], kind=info["kind"], sector=info.get("sector"),
        ltp=round(ltp, 2), prev_close=round(prev_close, 2), change=round(ltp - prev_close, 2),
        change_pct=round((ltp / prev_close - 1) * 100, 2) if prev_close else 0.0,
        open=round(open_, 2), high=round(high, 2), low=round(low, 2), volume=volume,
        source=source, as_of=now.isoformat(timespec="seconds"),
    )


provider = YahooProvider()


class _QuoteBook:
    """One cached snapshot of every Yahoo quote, refreshed as a batch."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._quotes: dict[str, Quote] = {}
        self._fetched_at = 0.0
        self._refreshing = False
        self._failures = 0

    def _fetch_live(self) -> dict[str, Quote]:
        return provider.fetch_quotes(all_symbols())

    def _refresh(self) -> None:
        try:
            fresh = self._fetch_live()
            if not fresh:
                raise RuntimeError("the price provider returned no quotes")
            with self._lock:
                self._quotes.update(fresh)
                self._fetched_at = time.monotonic()
                self._failures = 0
        except Exception as exc:
            self._failures += 1
            log.warning("live quote refresh failed (%d in a row): %s", self._failures, exc)
            with self._lock:
                # Back off: retry after one TTL rather than on every request.
                self._fetched_at = time.monotonic()
        finally:
            self._refreshing = False

    def snapshot(self) -> dict[str, Quote]:
        age = time.monotonic() - self._fetched_at
        if not self._quotes and not self._refreshing:
            self._refreshing = True
            self._refresh()  # first call: block once
        elif age > settings.quote_ttl_seconds and not self._refreshing:
            self._refreshing = True
            threading.Thread(target=self._refresh, daemon=True).start()
        with self._lock:
            return dict(self._quotes)


quote_book = _QuoteBook()


def _upstox_quotes(feed, symbols: list[str]) -> dict[str, Quote]:
    """Real-time quotes for a connected user; empty if Upstox cannot answer."""
    from app.services.market_data import OptionsUnavailable

    try:
        raw = feed.quotes(symbols)
    except OptionsUnavailable:
        return {}
    except Exception as exc:  # a broker outage falls back to delayed prices
        log.warning("upstox quotes failed: %s", exc)
        return {}
    now = now_ist()
    out = {}
    for symbol, q in raw.items():
        ohlc = q.get("ohlc") or {}
        ltp = float(q.get("last_price") or 0)
        net = q.get("net_change")
        prev = ltp - float(net) if net is not None else float(ohlc.get("close") or 0)
        if ltp <= 0 or prev <= 0:
            continue
        out[symbol] = make_quote(symbol, ltp, prev, float(ohlc.get("open") or ltp),
                                 float(ohlc.get("high") or ltp), float(ohlc.get("low") or ltp),
                                 float(q.get("volume") or 0), "live", now)
    return out


def get_quotes(symbols: list[str] | None = None, feed=None) -> dict[str, Quote]:
    """Real quotes for ``symbols``: Upstox for a connected user, else Yahoo.

    Symbols no source could price are absent from the result.
    """
    wanted = [s.upper() for s in (symbols or all_symbols()) if instrument_info(s) is not None]
    out: dict[str, Quote] = {}
    if feed is not None and feed.connected:
        out.update(_upstox_quotes(feed, wanted))
    missing = [s for s in wanted if s not in out]
    if missing:
        book = quote_book.snapshot()
        out.update({s: book[s] for s in missing if s in book})
    return out


def get_quote(symbol: str, feed=None) -> Quote | None:
    return get_quotes([symbol], feed).get(symbol.upper())


def require_quote(symbol: str, feed=None) -> Quote:
    quote = get_quote(symbol, feed)
    if quote is None:
        raise MarketDataUnavailable(
            f"No price is available for {symbol.upper()} right now: Yahoo did not answer"
            + ("" if feed is not None and feed.connected else " and Upstox is not connected") + ".")
    return quote


def index_strip(feed=None) -> list[dict]:
    quotes = get_quotes(list(INDICES), feed)
    return [quotes[k].to_dict() for k in INDICES if k in quotes]


def movers(kind: str = "gainers", limit: int = 10, feed=None) -> list[dict]:
    """Top gainers, losers or movers (by absolute change) among the stocks."""
    stocks = [q for q in get_quotes(list(universe()["symbol"]), feed).values() if q.kind == "equity"]
    if kind == "losers":
        stocks.sort(key=lambda q: q.change_pct)
    elif kind == "movers":
        stocks.sort(key=lambda q: abs(q.change_pct), reverse=True)
    else:
        stocks.sort(key=lambda q: q.change_pct, reverse=True)
    return [q.to_dict() for q in stocks[:limit]]


# --------------------------------------------------------------------------
# Candles
# --------------------------------------------------------------------------

# interval -> (Yahoo interval, longest range Yahoo serves at that interval)
INTERVALS = {
    "1m": ("1m", 7), "5m": ("5m", 59), "15m": ("15m", 59),
    "1h": ("60m", 729), "1D": ("1d", 3650),
}
RANGES = {"1D": 1, "5D": 5, "1M": 31, "3M": 92, "1Y": 366, "5Y": 1830}

_candle_cache: dict[tuple, tuple[float, dict]] = {}
_candle_lock = threading.Lock()


def _frame_to_bars(frame: pd.DataFrame) -> list[dict]:
    bars = []
    for ts, row in frame.iterrows():
        stamp = pd.Timestamp(ts)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(IST)
        bars.append({
            "time": int(stamp.timestamp()),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": float(row["volume"]) if not pd.isna(row["volume"]) else 0.0,
        })
    return bars


def _resample(frame: pd.DataFrame, interval: str) -> pd.DataFrame:
    rule = {"1m": None, "5m": "5min", "15m": "15min", "1h": "60min"}[interval]
    if rule is None:
        return frame
    return frame.resample(rule, origin="start").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["close"])


def get_candles(symbol: str, interval: str = "1m", range_: str = "1D", feed=None) -> dict:
    """OHLCV bars for a chart, oldest first, times in UNIX seconds."""
    symbol = symbol.upper()
    if instrument_info(symbol) is None:
        raise KeyError(symbol)
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {sorted(INTERVALS)}")
    if range_ not in RANGES:
        raise ValueError(f"range must be one of {sorted(RANGES)}")
    max_days = INTERVALS[interval][1]
    days = min(RANGES[range_], max_days)
    clamped = RANGES[range_] > max_days

    frame, source = None, None
    if feed is not None and feed.connected:
        from app.integrations.upstox.instruments import master
        from app.services.market_data import OptionsUnavailable

        try:
            key = master.key_for(symbol)
            if key:
                frame = feed.candles(key, interval, days)
                source = "live"
        except OptionsUnavailable:
            frame = None
        except Exception as exc:
            log.warning("upstox candles failed for %s: %s", symbol, exc)
            frame = None
        if frame is not None and frame.empty:
            frame = None

    if frame is None:
        key = (symbol, interval, days)
        ttl = 30.0 if interval != "1D" else 600.0
        with _candle_cache_guard():
            cached = _candle_cache.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            frame = cached[1]
        else:
            try:
                frame = provider.fetch_candles(symbol, interval, range_, days)
            except Exception as exc:
                log.warning("candle fetch failed for %s: %s", symbol, exc)
                frame = None
            if frame is not None:
                with _candle_cache_guard():
                    _candle_cache[key] = (time.monotonic(), frame)
        source = "delayed"

    if frame is None or frame.empty:
        raise MarketDataUnavailable(f"No candles are available for {symbol} right now.")

    return {
        "symbol": symbol,
        "interval": interval,
        "range": range_,
        "range_clamped_to_days": days if clamped else None,
        "source": source,
        "bars": _frame_to_bars(frame),
        "as_of": now_ist().isoformat(timespec="seconds"),
    }


def _candle_cache_guard():
    return _candle_lock


def reset_caches() -> None:
    """Forget every cached quote and candle (tests, and a manual refresh)."""
    global _universe_cache
    with _candle_lock:
        _candle_cache.clear()
    quote_book._quotes.clear()
    quote_book._fetched_at = 0.0
    _universe_cache = None
