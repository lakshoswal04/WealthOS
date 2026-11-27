"""Stock screeners: ready-made screens and a small filter language.

A screen is a list of filters over the fields ``wealthos_core.indicators``
computes per symbol, plus fundamentals fetched from Yahoo:

    {"filters": [{"field": "rsi_14", "op": "lte", "value": 35},
                 {"field": "above_sma_200", "op": "is_true"},
                 {"field": "sma_50", "op": "gt", "value_field": "sma_200"}],
     "sort": {"field": "change_1d_pct", "dir": "desc"}, "limit": 50}

Data, in order of preference:

1. the universe's daily OHLCV (``data/processed/universe_daily.parquet``),
   with today's row patched from the live quote book so a screen reflects
   the current session rather than yesterday's close;
2. the analytics price panel, close-only, when the parquet is absent (a
   fresh checkout, or the test suite). Volume and candlestick fields are
   then unavailable and screens that need them say so.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from wealthos_core.indicators import SNAPSHOT_FIELDS, snapshot

from app.core.config import settings
from app.services import live_market_service as live

log = logging.getLogger("wealthos.screener")

FUNDAMENTAL_FIELDS: dict[str, str] = {
    "pe": "Price / earnings (trailing)",
    "pb": "Price / book",
    "roe_pct": "Return on equity (%)",
    "market_cap_cr": "Market cap (₹ Cr)",
    "dividend_yield_pct": "Dividend yield (%)",
    "debt_to_equity": "Debt / equity (%)",
}

CANDLESTICK_FIELDS = {"doji", "hammer", "shooting_star", "bullish_engulfing", "bearish_engulfing"}
VOLUME_FIELDS = {"rel_volume", "avg_value_cr"}
BOOLEAN_FIELDS = {
    k for k in SNAPSHOT_FIELDS
    if k.startswith(("above_", "new_", "macd_", "golden_", "death_", "crossed_"))
} | CANDLESTICK_FIELDS

OPS = {"gt", "gte", "lt", "lte", "eq", "between", "is_true", "is_false"}


class ScreenError(ValueError):
    pass


# --------------------------------------------------------------------------
# Ready-made screens
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Screen:
    id: str
    name: str
    group: str            # technicals | fundamentals | candlestick
    category: str
    description: str
    filters: list[dict]
    columns: list[str]
    sort: dict = field(default_factory=lambda: {"field": "change_1d_pct", "dir": "desc"})


LIQUID = {"field": "avg_value_cr", "op": "gte", "value": 1}

SCREENS: list[Screen] = [
    Screen("52w-high-breakouts", "52-week high breakouts", "technicals", "Breakouts",
           "A new 52-week high in the latest session, on volume 1.5× or more its 20-session average.",
           [{"field": "new_52w_high", "op": "is_true"},
            {"field": "rel_volume", "op": "gte", "value": 1.5}, LIQUID],
           ["new_52w_high", "rel_volume", "avg_value_cr"]),
    Screen("near-52w-high", "Near the 52-week high", "technicals", "Near 52-week high / low",
           "Within 2% of the 52-week high and above the 200-day average.",
           [{"field": "pct_from_52w_high", "op": "gte", "value": -2},
            {"field": "above_sma_200", "op": "is_true"}],
           ["pct_from_52w_high", "above_sma_200", "avg_value_cr"],
           {"field": "pct_from_52w_high", "dir": "desc"}),
    Screen("near-52w-low", "Near the 52-week low", "technicals", "Near 52-week high / low",
           "Within 3% of the 52-week low.",
           [{"field": "pct_from_52w_low", "op": "lte", "value": 3}],
           ["pct_from_52w_low", "rsi_14", "avg_value_cr"],
           {"field": "pct_from_52w_low", "dir": "asc"}),
    Screen("volume-shockers", "Volume shockers", "technicals", "Volume",
           "Volume 3× or more its 20-session average, and up 2% or more in the latest session.",
           [{"field": "rel_volume", "op": "gte", "value": 3},
            {"field": "change_1d_pct", "op": "gte", "value": 2}],
           ["rel_volume", "change_1d_pct", "avg_value_cr"],
           {"field": "rel_volume", "dir": "desc"}),
    Screen("volume-buildup", "Volume build-up", "technicals", "Volume",
           "Volume 1.5× or more its average for the session, with the price above its 50-day average.",
           [{"field": "rel_volume", "op": "gte", "value": 1.5},
            {"field": "above_sma_50", "op": "is_true"}],
           ["rel_volume", "change_1d_pct", "avg_value_cr"],
           {"field": "rel_volume", "dir": "desc"}),
    Screen("rsi-dip-above-200", "RSI dip above the 200-day", "technicals", "Pullbacks",
           "RSI (14) of 35 or less while the price stays above its 200-day average.",
           [{"field": "rsi_14", "op": "lte", "value": 35},
            {"field": "above_sma_200", "op": "is_true"}],
           ["rsi_14", "above_sma_200"], {"field": "rsi_14", "dir": "asc"}),
    Screen("golden-cross", "Golden cross", "technicals", "Crossovers",
           "The 50-day average crossed above the 200-day in the last ten sessions.",
           [{"field": "golden_cross_10d", "op": "is_true"}],
           ["golden_cross_10d", "avg_value_cr"]),
    Screen("death-cross", "Death cross", "technicals", "Crossovers",
           "The 50-day average crossed below the 200-day in the last ten sessions.",
           [{"field": "death_cross_10d", "op": "is_true"}],
           ["death_cross_10d", "avg_value_cr"]),
    Screen("macd-turned-up", "MACD turned up", "technicals", "Crossovers",
           "MACD crossed above its signal line in the last 3 sessions, with the price above its 200-day average.",
           [{"field": "macd_bullish_cross_3d", "op": "is_true"},
            {"field": "above_sma_200", "op": "is_true"}],
           ["macd_bullish_cross_3d", "above_sma_200", "avg_value_cr"]),
    Screen("back-above-50", "Back above the 50-day average", "technicals", "Crossovers",
           "Crossed above its 50-day average in the past week and is still above it, ₹1 Cr+ traded a day on average.",
           [{"field": "crossed_above_sma_50_5d", "op": "is_true"},
            {"field": "above_sma_50", "op": "is_true"}, LIQUID],
           ["avg_value_cr"]),
    Screen("slipped-below-200", "Slipped below the 200-day average", "technicals", "Crossovers",
           "Crossed below its 200-day average in the past week and is still below it: long-term support given up.",
           [{"field": "crossed_below_sma_200_5d", "op": "is_true"},
            {"field": "above_sma_200", "op": "is_false"}],
           ["avg_value_cr"], {"field": "change_1d_pct", "dir": "asc"}),
    Screen("momentum-leaders", "One-month momentum leaders", "technicals", "Momentum",
           "Up 10% or more over a month and trading above the 50-day average.",
           [{"field": "change_1m_pct", "op": "gte", "value": 10},
            {"field": "above_sma_50", "op": "is_true"}],
           ["change_1m_pct", "rsi_14"], {"field": "change_1m_pct", "dir": "desc"}),
    Screen("strong-uptrend", "Strong uptrend", "technicals", "Trend",
           "Price above the 50-day, and the 50-day above the 200-day.",
           [{"field": "above_sma_50", "op": "is_true"},
            {"field": "sma_50", "op": "gt", "value_field": "sma_200"}],
           ["change_1m_pct", "pct_from_52w_high"], {"field": "change_1m_pct", "dir": "desc"}),
    Screen("downtrend", "Persistent downtrend", "technicals", "Trend",
           "Price below the 50-day, and the 50-day below the 200-day.",
           [{"field": "above_sma_50", "op": "is_false"},
            {"field": "sma_50", "op": "lt", "value_field": "sma_200"}],
           ["change_1m_pct", "pct_from_52w_low"], {"field": "change_1m_pct", "dir": "asc"}),
    Screen("overbought", "Overbought", "technicals", "Overbought / oversold",
           "RSI (14) at 70 or above.",
           [{"field": "rsi_14", "op": "gte", "value": 70}],
           ["rsi_14", "change_5d_pct"], {"field": "rsi_14", "dir": "desc"}),
    Screen("oversold", "Oversold", "technicals", "Overbought / oversold",
           "RSI (14) at 30 or below.",
           [{"field": "rsi_14", "op": "lte", "value": 30}],
           ["rsi_14", "change_5d_pct"], {"field": "rsi_14", "dir": "asc"}),
    Screen("oversold-bounce", "Oversold bounce", "technicals", "Reversals",
           "RSI (14) still at 40 or below, but up 2% or more today.",
           [{"field": "rsi_14", "op": "lte", "value": 40},
            {"field": "change_1d_pct", "op": "gte", "value": 2}],
           ["rsi_14", "change_1d_pct"]),
    Screen("pullback-in-uptrend", "Pullback in an uptrend", "technicals", "Reversals",
           "Down over the past week while still above the 200-day average.",
           [{"field": "change_5d_pct", "op": "lte", "value": -3},
            {"field": "above_sma_200", "op": "is_true"}],
           ["change_5d_pct", "rsi_14"], {"field": "change_5d_pct", "dir": "asc"}),

    Screen("doji", "Doji", "candlestick", "Indecision",
           "Open and close within a tenth of the day's range: buyers and sellers in balance.",
           [{"field": "doji", "op": "is_true"}], ["rsi_14", "change_5d_pct"]),
    Screen("hammer-after-decline", "Hammer after a decline", "candlestick", "Bullish reversal",
           "A long lower shadow at least twice the body, after a falling week.",
           [{"field": "hammer", "op": "is_true"}, {"field": "change_5d_pct", "op": "lt", "value": 0}],
           ["change_5d_pct", "rsi_14"]),
    Screen("bullish-engulfing", "Bullish engulfing", "candlestick", "Bullish reversal",
           "A rising candle whose body swallows the previous falling one.",
           [{"field": "bullish_engulfing", "op": "is_true"}], ["change_1d_pct", "rsi_14"]),
    Screen("bearish-engulfing", "Bearish engulfing", "candlestick", "Bearish reversal",
           "A falling candle whose body swallows the previous rising one.",
           [{"field": "bearish_engulfing", "op": "is_true"}], ["change_1d_pct", "rsi_14"],
           {"field": "change_1d_pct", "dir": "asc"}),
    Screen("shooting-star", "Shooting star", "candlestick", "Bearish reversal",
           "A long upper shadow at least twice the body: a rally rejected.",
           [{"field": "shooting_star", "op": "is_true"}], ["change_5d_pct", "rsi_14"]),

    Screen("value-quality", "Reasonable value, good returns", "fundamentals", "Value",
           "Trailing P/E under 25 with return on equity of 15% or more.",
           [{"field": "pe", "op": "between", "value": [0.01, 25]},
            {"field": "roe_pct", "op": "gte", "value": 15}],
           ["pe", "roe_pct", "market_cap_cr"], {"field": "roe_pct", "dir": "desc"}),
    Screen("high-roe", "High return on equity", "fundamentals", "Quality",
           "Return on equity of 20% or more.",
           [{"field": "roe_pct", "op": "gte", "value": 20}],
           ["roe_pct", "pe", "pb"], {"field": "roe_pct", "dir": "desc"}),
    Screen("dividend-payers", "Dividend payers", "fundamentals", "Income",
           "Dividend yield of 2% or more.",
           [{"field": "dividend_yield_pct", "op": "gte", "value": 2}],
           ["dividend_yield_pct", "pe"], {"field": "dividend_yield_pct", "dir": "desc"}),
    Screen("low-debt-quality", "Low debt, steady returns", "fundamentals", "Quality",
           "Debt to equity under 30% and return on equity of 12% or more.",
           [{"field": "debt_to_equity", "op": "lt", "value": 30},
            {"field": "roe_pct", "op": "gte", "value": 12}],
           ["debt_to_equity", "roe_pct"], {"field": "roe_pct", "dir": "desc"}),
    Screen("mega-caps", "Mega caps", "fundamentals", "Size",
           "Market capitalisation above ₹2 lakh crore.",
           [{"field": "market_cap_cr", "op": "gte", "value": 200000}],
           ["market_cap_cr", "pe"], {"field": "market_cap_cr", "dir": "desc"}),
]

SCREENS_BY_ID = {s.id: s for s in SCREENS}


def field_catalog() -> list[dict]:
    out = []
    for key, label in SNAPSHOT_FIELDS.items():
        group = "candlestick" if key in CANDLESTICK_FIELDS else "technical"
        out.append({"field": key, "label": label, "group": group,
                    "type": "boolean" if key in BOOLEAN_FIELDS else "number"})
    for key, label in FUNDAMENTAL_FIELDS.items():
        out.append({"field": key, "label": label, "group": "fundamental", "type": "number"})
    return out


ALL_FIELDS = {f["field"] for f in field_catalog()}


# --------------------------------------------------------------------------
# Fundamentals (Yahoo, fetched in the background, cached for a day)
# --------------------------------------------------------------------------

class _Fundamentals:
    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._fetched_on: str | None = None
        self._running = False
        self._lock = threading.Lock()

    @property
    def _path(self):
        return settings.processed_dir / "fundamentals.json"

    def get(self) -> tuple[dict[str, dict], str]:
        """(per-symbol fundamentals, status)."""
        today = str(live.last_session_date())
        if not self._data and self._path.exists():
            try:
                blob = json.loads(self._path.read_text())
                self._data, self._fetched_on = blob["data"], blob["fetched_on"]
            except Exception:
                pass
        if self._fetched_on != today:
            self._start_refresh(today)
        if not self._data:
            return {}, "loading" if self._running else "unavailable"
        return self._data, "ready"

    def _start_refresh(self, today: str) -> None:
        if not settings.live_market_enabled or self._running:
            return
        self._running = True

        def one(symbol: str) -> tuple[str, dict | None]:
            import yfinance as yf
            try:
                info = yf.Ticker(f"{symbol}.NS").info
            except Exception:
                return symbol, None

            def num(key: str, scale: float = 1.0) -> float | None:
                value = info.get(key)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    return round(float(value) * scale, 2)
                return None

            return symbol, {
                "pe": num("trailingPE"), "pb": num("priceToBook"),
                "roe_pct": num("returnOnEquity", 100), "market_cap_cr": num("marketCap", 1e-7),
                "dividend_yield_pct": num("dividendYield"), "debt_to_equity": num("debtToEquity"),
            }

        def run() -> None:
            try:
                symbols = list(live.universe()["symbol"])
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = dict(r for r in pool.map(one, symbols) if r[1] is not None)
                if results:
                    with self._lock:
                        self._data, self._fetched_on = results, today
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    self._path.write_text(json.dumps({"fetched_on": today, "data": results}))
                    log.info("fundamentals refreshed for %d symbols", len(results))
            except Exception as exc:
                log.warning("fundamentals refresh failed: %s", exc)
            finally:
                self._running = False

        threading.Thread(target=run, daemon=True).start()


fundamentals = _Fundamentals()


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------

_snap_lock = threading.Lock()
_snap_cache: dict = {"key": None, "rows": None, "source": None}


def _frames_from_parquet() -> dict[str, pd.DataFrame] | None:
    frame = live.daily_store.frame()
    if frame is None:
        return None
    stocks = set(live.universe()["symbol"])
    quotes = live.quote_book.snapshot()
    session = pd.Timestamp(live.last_session_date())
    out = {}
    for symbol, one in frame[frame["symbol"].isin(stocks)].groupby("symbol"):
        one = one.set_index("date").sort_index()[["open", "high", "low", "close", "volume"]]
        q = quotes.get(symbol)
        if q is not None and q.source == "delayed":
            # Today's bar from the live quote, so screens track the session.
            today = pd.DataFrame(
                {"open": [q.open], "high": [q.high], "low": [q.low], "close": [q.ltp],
                 "volume": [q.volume]}, index=[session])
            one = pd.concat([one[one.index < session], today])
        out[symbol] = one
    return out


def _frames_from_panel(db: Session) -> dict[str, pd.DataFrame]:
    from app.services.market_service import market_cache

    panel = market_cache.panel(db)
    assets = market_cache.assets(db)
    # The analytics asset frame is indexed by symbol.
    equities = set(assets.index[assets["asset_class"] == "equity"]) if not assets.empty else set()
    out = {}
    for symbol in panel.columns:
        if symbol not in equities:
            continue
        close = panel[symbol].dropna()
        if len(close) < 2:
            continue
        out[symbol] = pd.DataFrame({"open": close, "high": close, "low": close,
                                    "close": close, "volume": float("nan")})
    return out


def snapshots(db: Session) -> tuple[list[dict], str]:
    """One row per stock with every screener field; recomputed every 2 minutes."""
    funds, _ = fundamentals.get()
    # Fundamentals arrive in the background; their arrival must invalidate
    # snapshots built without them.
    key = (str(live.last_session_date()), live.minute_of_session() // 2,
           live.daily_store._mtime, len(funds))
    with _snap_lock:
        if _snap_cache["key"] == key and _snap_cache["rows"] is not None:
            return _snap_cache["rows"], _snap_cache["source"]

    frames = _frames_from_parquet()
    source = "universe_daily"
    if frames is None:
        frames, source = _frames_from_panel(db), "analytics_panel_close_only"

    names = live.universe().set_index("symbol")
    rows = []
    for symbol, frame in frames.items():
        if len(frame) < 2:
            continue
        row = snapshot(frame)
        if source != "universe_daily":
            for key_ in VOLUME_FIELDS | CANDLESTICK_FIELDS:
                row[key_] = None
        row.update(funds.get(symbol, {}))
        row["symbol"] = symbol
        row["name"] = str(names.loc[symbol, "name"]) if symbol in names.index else symbol
        row["sector"] = str(names.loc[symbol, "sector"]) if symbol in names.index else None
        rows.append(row)

    with _snap_lock:
        _snap_cache.update(key=key, rows=rows, source=source)
    return rows, source


def reset_cache() -> None:
    with _snap_lock:
        _snap_cache.update(key=None, rows=None, source=None)


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def validate(definition: dict) -> dict:
    """Normalise a screen definition, rejecting anything malformed."""
    filters = definition.get("filters")
    if not isinstance(filters, list) or not filters:
        raise ScreenError("A screen needs at least one filter.")
    if len(filters) > 12:
        raise ScreenError("A screen can have at most 12 filters.")
    clean = []
    for f in filters:
        if not isinstance(f, dict):
            raise ScreenError("Each filter must be an object.")
        name, op = f.get("field"), f.get("op")
        if name not in ALL_FIELDS:
            raise ScreenError(f"Unknown field: {name!r}.")
        if op not in OPS:
            raise ScreenError(f"Unknown operator: {op!r}.")
        item = {"field": name, "op": op}
        if op in {"is_true", "is_false"}:
            pass
        elif "value_field" in f:
            if f["value_field"] not in ALL_FIELDS or op == "between":
                raise ScreenError(f"Cannot compare {name} with {f.get('value_field')!r}.")
            item["value_field"] = f["value_field"]
        elif op == "between":
            v = f.get("value")
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
                raise ScreenError("'between' needs a [low, high] pair.")
            item["value"] = [float(v[0]), float(v[1])]
        else:
            v = f.get("value")
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ScreenError(f"Filter on {name} needs a numeric value.")
            item["value"] = float(v)
        clean.append(item)

    sort = definition.get("sort") or {"field": "change_1d_pct", "dir": "desc"}
    if sort.get("field") not in ALL_FIELDS or sort.get("dir") not in {"asc", "desc"}:
        raise ScreenError("Sort must name a known field and a direction of asc or desc.")
    limit = int(definition.get("limit") or 50)
    return {"filters": clean, "sort": {"field": sort["field"], "dir": sort["dir"]},
            "limit": max(1, min(limit, 100))}


def _passes(row: dict, f: dict) -> bool:
    value = row.get(f["field"])
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    op = f["op"]
    if op == "is_true":
        return value is True
    if op == "is_false":
        return value is False
    target = row.get(f["value_field"]) if "value_field" in f else f.get("value")
    if target is None:
        return False
    if op == "between":
        return target[0] <= value <= target[1]
    return {
        "gt": value > target, "gte": value >= target, "lt": value < target,
        "lte": value <= target, "eq": value == target,
    }[op]


def _clean_number(value):
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 2)
    return value


def run(db: Session, definition: dict, columns: list[str] | None = None) -> dict:
    """Evaluate a screen over the universe."""
    spec = validate(definition)
    rows, source = snapshots(db)
    used = {f["field"] for f in spec["filters"]}

    missing = []
    if source != "universe_daily" and used & (VOLUME_FIELDS | CANDLESTICK_FIELDS):
        missing.append("volume and candlestick fields need daily OHLCV, which has not been fetched")
    if used & set(FUNDAMENTAL_FIELDS):
        _, status = fundamentals.get()
        if status != "ready":
            missing.append(f"fundamentals are {status}")
    if missing:
        return {"available": False, "reason": "; ".join(missing).capitalize() + ".",
                "results": [], "count": 0, "universe_size": len(rows), "data_source": source}

    hits = [r for r in rows if all(_passes(r, f) for f in spec["filters"])]
    sort_field, reverse = spec["sort"]["field"], spec["sort"]["dir"] == "desc"
    hits.sort(key=lambda r: (r.get(sort_field) is None,
                             -(r.get(sort_field) or 0) if reverse else (r.get(sort_field) or 0)))
    shown = ["close", "change_1d_pct"] + [c for c in (columns or []) if c not in {"close", "change_1d_pct"}]
    shown += [f for f in used if f not in shown]
    results = [
        {"symbol": r["symbol"], "name": r["name"], "sector": r["sector"],
         **{c: _clean_number(r.get(c)) for c in shown}}
        for r in hits[: spec["limit"]]
    ]
    quotes_live = live.quote_book.snapshot()
    return {
        "available": True,
        "count": len(hits),
        "universe_size": len(rows),
        "columns": shown,
        "results": results,
        "definition": spec,
        "data_source": source,
        "price_source": "delayed" if quotes_live else "end_of_day",
        "as_of": live.now_ist().isoformat(timespec="seconds"),
    }


def run_screen(db: Session, screen_id: str, limit: int = 50) -> dict:
    screen = SCREENS_BY_ID.get(screen_id)
    if screen is None:
        raise ScreenError(f"Unknown screen: {screen_id!r}.")
    result = run(db, {"filters": screen.filters, "sort": screen.sort, "limit": limit},
                 columns=screen.columns)
    result["screen"] = describe(screen)
    return result


def describe(screen: Screen) -> dict:
    return {"id": screen.id, "name": screen.name, "group": screen.group,
            "category": screen.category, "description": screen.description,
            "filters": screen.filters, "sort": screen.sort, "columns": screen.columns,
            "field_labels": [field_label(f["field"]) for f in screen.filters]}


def field_label(name: str) -> str:
    return SNAPSHOT_FIELDS.get(name) or FUNDAMENTAL_FIELDS.get(name) or name


def list_screens() -> list[dict]:
    return [describe(s) for s in SCREENS]


def warm() -> None:
    """Start the background fetches the first screener request would need."""
    fundamentals.get()
