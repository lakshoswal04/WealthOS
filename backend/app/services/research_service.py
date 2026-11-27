"""News, calendar, corporate actions, commodities, pairs and strategy tools.

All real data:

* News, earnings and dividend dates, dividends and splits: Yahoo Finance.
* Commodities: COMEX/NYMEX futures from Yahoo, in US dollars. They are *not*
  MCX prices; an INR figure is a currency conversion at the live USD/INR
  rate and excludes import duty and GST. Each payload says so.
* Pairs: computed from the universe's real daily closes.
* Strategy payoff and wizard: priced from the user's live Upstox option
  chain (premiums and implied volatility). Black-Scholes is only used to
  draw the today-curve from that real IV.

Fan-out calls to Yahoo are cached, so a page view does not re-download them.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from wealthos_core.options import bs_price, payoff_at_expiry, time_to_expiry

from app.core.config import settings
from app.services import live_market_service as live
from app.services import options_service
from app.services.market_data import Feed

log = logging.getLogger("wealthos.research")

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _cached(key: str, ttl: float, load):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
    value = load()
    with _lock:
        _cache[key] = (time.monotonic(), value)
    return value


def _require_network() -> None:
    if not settings.live_market_enabled:
        raise live.MarketDataUnavailable("Live data is switched off on this server.")


def _ticker(symbol: str):
    import yfinance as yf
    return yf.Ticker(live.yahoo_ticker(symbol))


# --------------------------------------------------------------------------
# News
# --------------------------------------------------------------------------

def _news_for(symbol: str) -> list[dict]:
    try:
        raw = _ticker(symbol).news or []
    except Exception as exc:
        log.debug("news failed for %s: %s", symbol, exc)
        return []
    out = []
    for item in raw:
        c = item.get("content") or item
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or c.get("link"))
        title = c.get("title")
        if not title or not url:
            continue
        out.append({
            "id": item.get("id") or c.get("id") or url, "symbol": symbol, "title": title,
            "summary": (c.get("summary") or c.get("description") or "")[:400],
            "publisher": (c.get("provider") or {}).get("displayName") or c.get("publisher"),
            "url": url, "published_at": c.get("pubDate") or c.get("displayTime"),
        })
    return out


def news(symbol: str | None = None, limit: int = 40) -> dict:
    _require_network()
    if symbol:
        symbol = symbol.upper()
        if live.instrument_info(symbol) is None:
            raise ValueError(f"{symbol} is not in the universe")
        items = _cached(f"news:{symbol}", 900, lambda: _news_for(symbol))
    else:
        def load():
            symbols = list(live.universe()["symbol"])
            with ThreadPoolExecutor(max_workers=8) as pool:
                batches = list(pool.map(_news_for, symbols))
            return [i for b in batches for i in b]
        items = _cached("news:all", 900, load)
    seen, unique = set(), []
    for i in sorted(items, key=lambda x: x.get("published_at") or "", reverse=True):
        if i["id"] in seen or i["title"] in seen:
            continue
        seen.update({i["id"], i["title"]})
        unique.append(i)
    return {"items": unique[:limit], "source": "Yahoo Finance", "count": len(unique)}


# --------------------------------------------------------------------------
# Calendar and corporate actions
# --------------------------------------------------------------------------

def _calendar_for(symbol: str) -> list[dict]:
    try:
        cal = _ticker(symbol).calendar or {}
    except Exception:
        return []
    events = []
    for d in cal.get("Earnings Date") or []:
        events.append({"symbol": symbol, "event": "earnings", "date": str(d),
                       "detail": (f"EPS estimate {cal['Earnings Average']:.2f}"
                                  if isinstance(cal.get("Earnings Average"), (int, float)) else None)})
    for label, key in (("ex_dividend", "Ex-Dividend Date"), ("dividend_payment", "Dividend Date")):
        if cal.get(key):
            events.append({"symbol": symbol, "event": label, "date": str(cal[key]), "detail": None})
    return events


def calendar(days_ahead: int = 60) -> dict:
    """Upcoming earnings and dividend dates across the NIFTY 100."""
    _require_network()

    def load():
        symbols = list(live.universe()["symbol"])
        with ThreadPoolExecutor(max_workers=8) as pool:
            return [e for batch in pool.map(_calendar_for, symbols) for e in batch]

    events = _cached("calendar", 6 * 3600, load)
    today = live.now_ist().date()
    horizon = today.toordinal() + days_ahead
    upcoming = [e for e in events if today.isoformat() <= e["date"] and date.fromisoformat(e["date"]).toordinal() <= horizon]
    names = live.universe().set_index("symbol")["name"].to_dict()
    for e in upcoming:
        e["name"] = names.get(e["symbol"], e["symbol"])
    upcoming.sort(key=lambda e: (e["date"], e["symbol"]))
    return {"events": upcoming, "days_ahead": days_ahead, "source": "Yahoo Finance"}


def stock_events(symbol: str) -> dict:
    """Dividends, splits and upcoming dates for one stock."""
    _require_network()
    symbol = symbol.upper()
    info = live.instrument_info(symbol)
    if info is None or info["kind"] != "equity":
        raise ValueError(f"{symbol} is not a stock in the universe")

    def load():
        t = _ticker(symbol)
        divs = t.dividends
        splits = t.splits
        return {
            "dividends": [{"date": str(ts.date()), "amount": round(float(v), 2)} for ts, v in divs.tail(12).items()],
            "splits": [{"date": str(ts.date()), "ratio": float(v)} for ts, v in splits.tail(6).items()],
            "upcoming": _calendar_for(symbol),
        }

    data = _cached(f"events:{symbol}", 3600, load)
    return {"symbol": symbol, "name": info["name"], **data, "source": "Yahoo Finance"}


# --------------------------------------------------------------------------
# Commodities (COMEX/NYMEX, not MCX)
# --------------------------------------------------------------------------

COMMODITIES = {
    "GC=F": ("Gold", "USD / troy oz", "COMEX"),
    "SI=F": ("Silver", "USD / troy oz", "COMEX"),
    "HG=F": ("Copper", "USD / lb", "COMEX"),
    "CL=F": ("Crude oil (WTI)", "USD / barrel", "NYMEX"),
    "BZ=F": ("Crude oil (Brent)", "USD / barrel", "ICE"),
    "NG=F": ("Natural gas", "USD / MMBtu", "NYMEX"),
}
TROY_OZ_G = 31.1034768


def commodities() -> dict:
    _require_network()

    def load():
        import yfinance as yf
        tickers = list(COMMODITIES) + ["USDINR=X"]
        raw = yf.download(tickers, period="5d", interval="1d", group_by="ticker", progress=False, threads=True)
        return raw

    raw = _cached("commodities", 120, load)
    level0 = set(raw.columns.get_level_values(0)) if not raw.empty else set()

    def last_two(t):
        if t not in level0:
            return None
        s = raw[t]["Close"].dropna()
        return (float(s.iloc[-1]), float(s.iloc[-2])) if len(s) >= 2 else None

    fx = last_two("USDINR=X")
    rows = []
    for t, (name, unit, venue) in COMMODITIES.items():
        pair = last_two(t)
        if not pair:
            continue
        price, prev = pair
        row = {"ticker": t, "name": name, "venue": venue, "unit": unit, "price": round(price, 2),
               "change": round(price - prev, 2), "change_pct": round((price / prev - 1) * 100, 2)}
        if fx and name in ("Gold", "Silver"):
            row["inr_reference"] = {
                "value": round(price * fx[0] / TROY_OZ_G * (10 if name == "Gold" else 1000), 0),
                "unit": "₹ / 10 g" if name == "Gold" else "₹ / kg",
            }
        rows.append(row)
    if not rows:
        raise live.MarketDataUnavailable("Commodity prices are unavailable right now.")
    return {
        "commodities": rows, "usd_inr": round(fx[0], 2) if fx else None, "source": "Yahoo Finance (delayed)",
        "note": "International futures in US dollars, not MCX. ₹ references convert at the live USD/INR "
                "rate and exclude import duty and GST, so they differ from Indian prices.",
    }


# --------------------------------------------------------------------------
# Pairs
# --------------------------------------------------------------------------

def _closes(symbol: str) -> pd.Series:
    hist = live.daily_store.history(symbol)
    if hist is None or len(hist) < 120:
        raise live.MarketDataUnavailable(f"Not enough daily history for {symbol}.")
    return hist["close"]


def _half_life(spread: pd.Series) -> float | None:
    lagged = spread.shift(1).dropna()
    delta = spread.diff().dropna()
    lagged, delta = lagged.align(delta, join="inner")
    if len(lagged) < 30:
        return None
    beta = np.polyfit(lagged.values, delta.values, 1)[0]
    if beta >= 0:
        return None
    return round(float(-math.log(2) / beta), 1)


def pair(a: str, b: str, lookback: int = 250, z_window: int = 60) -> dict:
    """Ratio, z-score, correlation, hedge ratio and half-life for two stocks."""
    a, b = a.upper(), b.upper()
    if a == b:
        raise ValueError("Pick two different stocks.")
    pa, pb = _closes(a), _closes(b)
    df = pd.concat([pa, pb], axis=1, keys=[a, b]).dropna().iloc[-lookback:]
    if len(df) < z_window + 20:
        raise live.MarketDataUnavailable("The two series overlap too little to compare.")
    log_ratio = np.log(df[a] / df[b])
    mean = log_ratio.rolling(z_window).mean()
    std = log_ratio.rolling(z_window).std()
    z = (log_ratio - mean) / std
    rets = np.log(df).diff().dropna()
    corr = float(rets[a].corr(rets[b]))
    hedge = float(np.polyfit(np.log(df[b]).values, np.log(df[a]).values, 1)[0])
    spread = np.log(df[a]) - hedge * np.log(df[b])
    latest_z = float(z.iloc[-1])
    signal = ("ratio stretched high: the pair trade would sell A, buy B" if latest_z >= 2 else
              "ratio stretched low: the pair trade would buy A, sell B" if latest_z <= -2 else
              "within normal range")
    step = max(1, len(df) // 180)
    return {
        "a": a, "b": b, "sessions": len(df), "correlation": round(corr, 3), "hedge_ratio": round(hedge, 3),
        "z_score": round(latest_z, 2), "half_life_days": _half_life(spread), "z_window": z_window,
        "ratio": round(float(df[a].iloc[-1] / df[b].iloc[-1]), 4), "signal": signal,
        "series": [{"date": str(ts.date()), "ratio": round(float(r), 4),
                    "z": None if pd.isna(zz) else round(float(zz), 2)}
                   for ts, r, zz in zip(df.index[::step], (df[a] / df[b]).values[::step], z.values[::step])],
        "method": f"z-score of log(A/B) against its {z_window}-session mean; correlation of daily log returns; "
                  "hedge ratio by regression of log prices; half-life from an AR(1) fit of the spread.",
    }


def pair_screen(min_correlation: float = 0.7, min_abs_z: float = 1.5, limit: int = 25) -> dict:
    """Same-sector pairs that move together and have drifted apart."""
    def load():
        uni = live.universe()
        frame = live.daily_store.frame()
        if frame is None:
            raise live.MarketDataUnavailable("Daily history has not been fetched yet.")
        closes = frame.pivot(index="date", columns="symbol", values="close").iloc[-250:]
        rets = np.log(closes).diff()
        results = []
        for sector, group in uni.groupby("sector"):
            names = [s for s in group["symbol"] if s in closes.columns and closes[s].notna().sum() >= 200]
            if len(names) < 2:
                continue
            corr = rets[names].corr()
            for i, x in enumerate(names):
                for y in names[i + 1:]:
                    c = corr.loc[x, y]
                    if pd.isna(c) or c < 0.5:
                        continue
                    lr = np.log(closes[x] / closes[y]).dropna()
                    z = (lr.iloc[-1] - lr.iloc[-60:].mean()) / lr.iloc[-60:].std()
                    results.append({"a": x, "b": y, "sector": sector, "correlation": round(float(c), 3),
                                    "z_score": round(float(z), 2)})
        return results

    rows = _cached("pairs", 1800, load)
    hits = [r for r in rows if r["correlation"] >= min_correlation and abs(r["z_score"]) >= min_abs_z]
    hits.sort(key=lambda r: abs(r["z_score"]), reverse=True)
    return {"pairs": hits[:limit], "checked": len(rows), "min_correlation": min_correlation,
            "min_abs_z": min_abs_z, "source": "Daily closes (Yahoo)"}


# --------------------------------------------------------------------------
# Strategy payoff and wizard (live chain)
# --------------------------------------------------------------------------

def payoff(feed: Feed, underlying: str, expiry: str | None, legs: list[dict]) -> dict:
    """Payoff at expiry and today, for legs priced from the live chain.

    Each leg: {"option_type": "CE"|"PE", "strike": float, "action": "buy"|"sell", "lots": int}.
    """
    if not legs or len(legs) > 6:
        raise ValueError("A strategy needs 1 to 6 legs.")
    full = options_service.chain(feed, underlying, expiry, 60)
    rows = {r["strike"]: r for r in full["rows"]}
    lot = full["lot_size"]
    priced = []
    for leg in legs:
        strike = float(leg["strike"])
        row = rows.get(int(strike) if strike.is_integer() else strike)
        if row is None:
            raise ValueError(f"{strike:g} is not a listed strike near the money for {full['expiry']}.")
        side = row["ce" if leg["option_type"] == "CE" else "pe"]
        if side["ltp"] <= 0:
            raise ValueError(f"{strike:g} {leg['option_type']} has no traded price right now.")
        priced.append({"option_type": leg["option_type"], "strike": strike, "action": leg["action"],
                       "lots": int(leg.get("lots") or 1), "premium": side["ltp"],
                       "iv": side["iv"] / 100 if side["iv"] else None,
                       "quantity": int(leg.get("lots") or 1) * lot})

    spot = full["spot"]
    lo, hi = spot * 0.9, spot * 1.1
    grid = np.linspace(lo, hi, 121)
    exp = date.fromisoformat(full["expiry"])
    now = live.now_ist()
    t = time_to_expiry(now.date(), exp, live.minute_of_session(now))

    def today_value(s: float) -> float | None:
        total = 0.0
        for l in priced:
            if not l["iv"]:
                return None
            value = bs_price(s, l["strike"], t, l["iv"], "call" if l["option_type"] == "CE" else "put")
            total += (1 if l["action"] == "buy" else -1) * (value - l["premium"]) * l["quantity"]
        return total

    curve = [{"spot": round(float(s), 2), "expiry": round(payoff_at_expiry(priced, float(s)), 2),
              "today": (round(v, 2) if (v := today_value(float(s))) is not None else None)} for s in grid]
    pnl = [p["expiry"] for p in curve]
    breakevens = [round((curve[i]["spot"] + curve[i + 1]["spot"]) / 2, 2)
                  for i in range(len(curve) - 1) if (pnl[i] <= 0 < pnl[i + 1]) or (pnl[i] >= 0 > pnl[i + 1])]
    # Slope at the edges tells whether profit or loss keeps growing beyond the chart.
    unbounded_profit = pnl[-1] > pnl[-2] + 1e-6 or pnl[0] > pnl[1] + 1e-6
    unbounded_loss = pnl[-1] < pnl[-2] - 1e-6 or pnl[0] < pnl[1] - 1e-6
    net = sum((1 if l["action"] == "sell" else -1) * l["premium"] * l["quantity"] for l in priced)
    return {
        "underlying": full["underlying"], "expiry": full["expiry"], "spot": spot, "lot_size": lot,
        "legs": priced, "net_premium": round(net, 2), "net_premium_type": "credit" if net > 0 else "debit",
        "max_profit": None if unbounded_profit else round(max(pnl), 2),
        "max_loss": None if unbounded_loss else round(min(pnl), 2),
        "breakevens": breakevens, "curve": curve, "source": "live",
        "method": "Premiums and implied volatility from the live Upstox chain; the today-curve reprices "
                  "each leg with Black-Scholes at that leg's own IV.",
    }


VIEWS = {
    "bullish": "Bull call spread", "bearish": "Bear put spread",
    "neutral": "Iron condor", "volatile": "Long straddle",
}


def wizard(feed: Feed, underlying: str, view: str, expiry: str | None = None) -> dict:
    """Map a market view to a defined-risk strategy, sized from the live chain's expected move."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {', '.join(VIEWS)}")
    full = options_service.chain(feed, underlying, expiry, 60)
    if not full["atm_iv"]:
        raise ValueError("The live chain has no implied volatility at the money right now.")
    strikes = sorted(r["strike"] for r in full["rows"])
    spot, atm = full["spot"], full["atm_strike"]
    now = live.now_ist()
    days = max((date.fromisoformat(full["expiry"]) - now.date()).days, 1)
    move = spot * full["atm_iv"] / 100 * math.sqrt(days / 365)

    def near(k: float) -> float:
        return min(strikes, key=lambda s: abs(s - k))

    half = move / 2
    if view == "bullish":
        legs = [{"option_type": "CE", "strike": atm, "action": "buy"},
                {"option_type": "CE", "strike": near(atm + half), "action": "sell"}]
    elif view == "bearish":
        legs = [{"option_type": "PE", "strike": atm, "action": "buy"},
                {"option_type": "PE", "strike": near(atm - half), "action": "sell"}]
    elif view == "neutral":
        hi, lo = near(atm + half), near(atm - half)
        legs = [{"option_type": "CE", "strike": hi, "action": "sell"},
                {"option_type": "CE", "strike": near(hi + half), "action": "buy"},
                {"option_type": "PE", "strike": lo, "action": "sell"},
                {"option_type": "PE", "strike": near(lo - half), "action": "buy"}]
    else:
        legs = [{"option_type": "CE", "strike": atm, "action": "buy"},
                {"option_type": "PE", "strike": atm, "action": "buy"}]
    if len({(l["strike"], l["option_type"]) for l in legs}) < len(legs):
        raise ValueError("The listed strikes are too sparse to build this strategy at this expiry.")
    result = payoff(feed, underlying, full["expiry"], [dict(l, lots=1) for l in legs])
    result.update({"view": view, "strategy": VIEWS[view], "expected_move": round(move, 2),
                   "sizing": "Spread widths are half the one-sigma move to expiry implied by the live ATM IV."})
    return result

