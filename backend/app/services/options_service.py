"""Index option chains, open interest and futures, from Upstox.

Every number here is exchange data delivered through the requesting user's
own Upstox session: premiums, OI, OI change, volume, implied volatility and
Greeks come from Upstox's option chain; expiries, strikes and lot sizes from
its instrument master; futures from its quotes. Without a session every
function raises `OptionsUnavailable` with the reason, and the UI shows that
reason -- there is no modelled fallback.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from wealthos_core.options import max_pain

from app.integrations.upstox.instruments import OPTION_UNDERLYINGS, master
from app.services import live_market_service as live
from app.services.market_data import Feed, OptionsUnavailable

DATA_NOTE = "Option data from Upstox: live premiums, open interest, volume, IV and Greeks."

__all__ = ["UnknownUnderlying", "OptionsUnavailable", "DATA_NOTE", "list_expiries", "chain",
           "summary", "option_quote", "option_candles", "multi_strike_oi", "oi_crossovers",
           "unusual_activity", "top_options", "top_futures", "fno_heatmap", "lot_size"]


class UnknownUnderlying(ValueError):
    pass


def _check(underlying: str) -> str:
    underlying = underlying.upper()
    if underlying not in OPTION_UNDERLYINGS:
        raise UnknownUnderlying(
            f"Options are available on {', '.join(OPTION_UNDERLYINGS)}; not {underlying}."
        )
    return underlying


def lot_size(underlying: str) -> int:
    size = master.lot_size(_check(underlying))
    if not size:
        raise OptionsUnavailable("Lot sizes could not be read from the Upstox instrument list.", "no_master")
    return size


def list_expiries(underlying: str, count: int = 6) -> list[str]:
    underlying = _check(underlying)
    return [str(d) for d in master.expiries_for(underlying, live.now_ist().date())[:count]]


def _resolve_expiry(underlying: str, expiry: str | None) -> date:
    listed = master.expiries_for(underlying, live.now_ist().date())
    if not listed:
        raise OptionsUnavailable(f"No listed {underlying} expiries were found.", "no_master")
    if expiry is None:
        return listed[0]
    chosen = date.fromisoformat(expiry)
    if chosen not in listed:
        raise ValueError(f"{expiry} is not a listed {underlying} expiry")
    return chosen


def _leg(side: dict) -> dict:
    md = side.get("market_data") or {}
    g = side.get("option_greeks") or {}
    ltp = float(md.get("ltp") or 0)
    close = float(md.get("close_price") or 0)
    oi = int(md.get("oi") or 0)
    prev_oi = int(md.get("prev_oi") or 0)
    return {
        "instrument_key": side.get("instrument_key"),
        "ltp": round(ltp, 2),
        "change": round(ltp - close, 2) if close else 0.0,
        "change_pct": round((ltp / close - 1) * 100, 2) if close else 0.0,
        "iv": round(float(g.get("iv") or 0), 2),
        "delta": round(float(g.get("delta") or 0), 3),
        "gamma": round(float(g.get("gamma") or 0), 5),
        "theta": round(float(g.get("theta") or 0), 2),
        "vega": round(float(g.get("vega") or 0), 2),
        "oi": oi,
        "oi_change": oi - prev_oi,
        "volume": int(md.get("volume") or 0),
        "bid": float(md.get("bid_price") or 0),
        "ask": float(md.get("ask_price") or 0),
    }


def chain(feed: Feed, underlying: str, expiry: str | None = None, strikes_each_side: int = 15) -> dict:
    """The live chain: both legs at every strike around the money."""
    underlying = _check(underlying)
    exp = _resolve_expiry(underlying, expiry)
    raw = feed.option_chain(underlying, exp)
    if not raw:
        raise OptionsUnavailable(f"Upstox returned no {underlying} chain for {exp}.", "empty")

    spot = float(raw[0].get("underlying_spot_price") or 0)
    rows = sorted(({"strike": float(r["strike_price"]), "ce": _leg(r.get("call_options") or {}),
                    "pe": _leg(r.get("put_options") or {})} for r in raw), key=lambda r: r["strike"])
    for r in rows:
        r["strike"] = int(r["strike"]) if r["strike"].is_integer() else r["strike"]
    atm_i = min(range(len(rows)), key=lambda i: abs(rows[i]["strike"] - spot))
    rows = rows[max(atm_i - strikes_each_side, 0): atm_i + strikes_each_side + 1]

    strikes = [r["strike"] for r in rows]
    call_oi = [r["ce"]["oi"] for r in rows]
    put_oi = [r["pe"]["oi"] for r in rows]
    atm = min(strikes, key=lambda k: abs(k - spot))
    atm_row = next(r for r in rows if r["strike"] == atm)
    ivs = [v for v in (atm_row["ce"]["iv"], atm_row["pe"]["iv"]) if v > 0]
    total_call, total_put = sum(call_oi), sum(put_oi)
    spot_quote = live.get_quote(underlying, feed)

    return {
        "underlying": underlying,
        "expiry": str(exp),
        "expiries": list_expiries(underlying),
        "spot": round(spot, 2),
        "spot_change_pct": spot_quote.change_pct if spot_quote else None,
        "atm_strike": atm,
        "atm_iv": round(sum(ivs) / len(ivs), 2) if ivs else None,
        "lot_size": lot_size(underlying),
        "strike_step": (strikes[1] - strikes[0]) if len(strikes) > 1 else None,
        "change_basis": "since the previous session's close",
        "total_call_oi": total_call,
        "total_put_oi": total_put,
        "total_call_oi_change": sum(r["ce"]["oi_change"] for r in rows),
        "total_put_oi_change": sum(r["pe"]["oi_change"] for r in rows),
        "pcr": round(total_put / total_call, 2) if total_call else None,
        "max_pain": max_pain(strikes, call_oi, put_oi),
        "resistance": strikes[call_oi.index(max(call_oi))] if any(call_oi) else None,
        "support": strikes[put_oi.index(max(put_oi))] if any(put_oi) else None,
        "rows": rows,
        "source": "live",
        "note": DATA_NOTE,
        "as_of": live.now_ist().isoformat(timespec="seconds"),
    }


def summary(feed: Feed, underlying: str = "NIFTY", expiry: str | None = None) -> dict:
    """The chain reduced to the figures a trader asks about first."""
    full = chain(feed, underlying, expiry, strikes_each_side=15)
    rows = full["rows"]

    def top(leg: str, key: str, n: int = 3) -> list[dict]:
        ranked = sorted(rows, key=lambda r: r[leg][key], reverse=True)[:n]
        return [{"strike": r["strike"], key: r[leg][key]} for r in ranked]

    atm_row = next(r for r in rows if r["strike"] == full["atm_strike"])
    keep = ("underlying", "expiry", "spot", "spot_change_pct", "atm_strike", "atm_iv", "pcr",
            "max_pain", "support", "resistance", "total_call_oi", "total_put_oi",
            "total_call_oi_change", "total_put_oi_change", "lot_size", "change_basis",
            "source", "note", "as_of")
    out = {k: full[k] for k in keep}
    out.update({
        "atm_call_premium": atm_row["ce"]["ltp"],
        "atm_put_premium": atm_row["pe"]["ltp"],
        "highest_call_oi": top("ce", "oi"),
        "highest_put_oi": top("pe", "oi"),
        "biggest_call_oi_addition": top("ce", "oi_change"),
        "biggest_put_oi_addition": top("pe", "oi_change"),
    })
    return out


def _contract(underlying: str, expiry: str | None, strike: float, option_type: str):
    underlying = _check(underlying)
    exp = _resolve_expiry(underlying, expiry)
    c = master.contract(underlying, exp, float(strike), option_type.upper())
    if c is None:
        raise ValueError(f"{underlying} {exp} {strike} {option_type} is not a listed contract.")
    return c


def option_quote(feed: Feed, underlying: str, expiry: str, strike: float, option_type: str) -> dict:
    """The live premium of one contract, with its previous close."""
    c = _contract(underlying, expiry, strike, option_type)
    q = feed.contract_quotes([c]).get(c.instrument_key)
    if not q:
        raise OptionsUnavailable(f"Upstox has no quote for {c.trading_symbol}.", "empty")
    ltp = float(q.get("last_price") or 0)
    net = q.get("net_change")
    prev = ltp - float(net) if net is not None else float((q.get("ohlc") or {}).get("close") or 0)
    return {"ltp": round(ltp, 2), "prev_close": round(prev, 2), "oi": int(q.get("oi") or 0),
            "instrument_key": c.instrument_key, "lot_size": c.lot_size,
            "trading_symbol": c.trading_symbol, "source": "live"}


def option_candles(feed: Feed, underlying: str, expiry: str | None, strike: float, option_type: str,
                   interval: str = "1m", range_: str = "1D") -> dict:
    c = _contract(underlying, expiry, strike, option_type)
    days = {"1D": 1, "5D": 5}.get(range_, 1)
    frame = feed.candles(c.instrument_key, interval, days, with_oi=True)
    return {
        "symbol": c.trading_symbol, "underlying": c.underlying, "expiry": str(c.expiry),
        "strike": c.strike, "option_type": option_type.upper(), "interval": interval, "range": range_,
        "bars": [{"time": int(ts.timestamp()), "open": float(r.open), "high": float(r.high),
                  "low": float(r.low), "close": float(r.close), "volume": float(r.volume),
                  "oi": float(r.oi)} for ts, r in frame.iterrows()],
        "lot_size": c.lot_size, "source": "live",
    }


def _oi_series(feed: Feed, keys: list[str], interval: str = "5m") -> dict[str, list]:
    """Today's OI candles for several contracts, fetched in parallel."""
    def one(key: str):
        frame = feed.candles(key, interval, 1, with_oi=True)
        return key, [(ts, int(r.oi)) for ts, r in frame.iterrows()]

    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, keys))


def multi_strike_oi(feed: Feed, underlying: str, strikes: list[float], expiry: str | None = None) -> dict:
    """How open interest at chosen strikes built up through today's session."""
    underlying = _check(underlying)
    exp = _resolve_expiry(underlying, expiry)
    pairs = []
    for k in strikes[:6]:
        ce = master.contract(underlying, exp, float(k), "CE")
        pe = master.contract(underlying, exp, float(k), "PE")
        if ce and pe:
            pairs.append((k, ce, pe))
    series_raw = _oi_series(feed, [c.instrument_key for _, ce, pe in pairs for c in (ce, pe)])
    series = []
    for k, ce, pe in pairs:
        ce_pts, pe_pts = dict(series_raw[ce.instrument_key]), dict(series_raw[pe.instrument_key])
        times = sorted(set(ce_pts) | set(pe_pts))
        series.append({"strike": k, "points": [
            {"time": t.strftime("%H:%M"), "ce": ce_pts.get(t), "pe": pe_pts.get(t)} for t in times]})
    return {"underlying": underlying, "expiry": str(exp), "series": series, "source": "live",
            "note": "Open interest from Upstox 5-minute candles."}


def oi_crossovers(feed: Feed, underlying: str = "NIFTY", expiry: str | None = None,
                  strikes_each_side: int = 6) -> dict:
    """Strikes where put OI overtook call OI, or the reverse, during today's session."""
    full = chain(feed, underlying, expiry, strikes_each_side)
    exp = date.fromisoformat(full["expiry"])
    pairs = [(r["strike"], master.contract(full["underlying"], exp, float(r["strike"]), "CE"),
              master.contract(full["underlying"], exp, float(r["strike"]), "PE")) for r in full["rows"]]
    pairs = [p for p in pairs if p[1] and p[2]]
    raw = _oi_series(feed, [c.instrument_key for _, ce, pe in pairs for c in (ce, pe)], "15m")
    crossings = []
    for k, ce, pe in pairs:
        ce_pts, pe_pts = dict(raw[ce.instrument_key]), dict(raw[pe.instrument_key])
        prev = None
        for t in sorted(set(ce_pts) & set(pe_pts)):
            diff = pe_pts[t] - ce_pts[t]
            sign = (diff > 0) - (diff < 0)
            if prev is not None and sign and prev and sign != prev:
                crossings.append({
                    "strike": k, "time": t.strftime("%H:%M"),
                    "direction": "puts_overtook_calls" if sign > 0 else "calls_overtook_puts",
                    "call_oi": ce_pts[t], "put_oi": pe_pts[t]})
            if sign:
                prev = sign
    crossings.sort(key=lambda c: c["time"], reverse=True)
    return {"underlying": full["underlying"], "expiry": full["expiry"], "spot": full["spot"],
            "crossovers": crossings, "strikes_checked": len(pairs), "interval": "15m", "source": "live",
            "method": "Put OI minus call OI at each strike on 15-minute candles; a crossover is a change of sign."}


def unusual_activity(feed: Feed, limit: int = 15) -> dict:
    """Contracts trading far more than their open interest, or adding OI fast."""
    items = []
    for underlying in ("NIFTY", "BANKNIFTY", "SENSEX"):
        try:
            full = chain(feed, underlying, None, 20)
        except (OptionsUnavailable, ValueError):
            continue
        for r in full["rows"]:
            for leg, label in (("ce", "CE"), ("pe", "PE")):
                d = r[leg]
                if d["volume"] <= 0 or d["oi"] <= 0:
                    continue
                prev_oi = d["oi"] - d["oi_change"]
                items.append({
                    "symbol": f"{underlying} {r['strike']} {label}", "underlying": underlying,
                    "expiry": full["expiry"], "strike": r["strike"], "option_type": label,
                    "ltp": d["ltp"], "change_pct": d["change_pct"], "volume": d["volume"], "oi": d["oi"],
                    "volume_to_oi": round(d["volume"] / d["oi"], 2),
                    "oi_change_pct": round(d["oi_change"] / prev_oi * 100, 1) if prev_oi > 0 else None,
                })
    if not items and not feed.connected:
        raise OptionsUnavailable(feed.reason, feed.state)
    items.sort(key=lambda i: i["volume_to_oi"], reverse=True)
    return {"contracts": items[:limit], "source": "live",
            "method": "Ranked by volume divided by open interest: a contract trading many times its "
                      "outstanding positions in a day is unusual."}


def top_options(feed: Feed, kind: str = "gainers", limit: int = 10) -> list[dict]:
    contracts = []
    for underlying in ("NIFTY", "BANKNIFTY", "SENSEX"):
        try:
            full = chain(feed, underlying, None, 8)
        except (OptionsUnavailable, ValueError):
            if not feed.connected:
                raise
            continue
        for row in full["rows"]:
            for leg, label in (("ce", "CE"), ("pe", "PE")):
                d = row[leg]
                contracts.append({"symbol": f"{underlying} {row['strike']} {label}", "underlying": underlying,
                                  "expiry": full["expiry"], "strike": row["strike"], "option_type": label,
                                  "ltp": d["ltp"], "change_pct": d["change_pct"], "oi": d["oi"],
                                  "volume": d["volume"]})
    key = {"losers": lambda c: c["change_pct"], "movers": lambda c: -c["volume"]}.get(kind, lambda c: -c["change_pct"])
    return sorted(contracts, key=key)[:limit]


def top_futures(feed: Feed, kind: str = "gainers", limit: int = 10) -> list[dict]:
    """Near-month futures of NIFTY 100 stocks and the indices, from live quotes."""
    feed.require()
    today = live.now_ist().date()
    names = list(live.universe()["symbol"]) + ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
    contracts = [c for c in (master.near_future(n, today) for n in names) if c]
    quotes = feed.contract_quotes(contracts)
    out = []
    for c in contracts:
        q = quotes.get(c.instrument_key)
        if not q:
            continue
        ltp = float(q.get("last_price") or 0)
        net = q.get("net_change")
        prev = ltp - float(net) if net is not None else 0
        if ltp <= 0 or prev <= 0:
            continue
        out.append({"symbol": c.trading_symbol, "underlying": c.underlying, "expiry": str(c.expiry),
                    "ltp": round(ltp, 2), "change_pct": round((ltp / prev - 1) * 100, 2),
                    "oi": int(q.get("oi") or 0), "volume": int(q.get("volume") or 0),
                    "lot_size": c.lot_size})
    key = {"losers": lambda c: c["change_pct"], "movers": lambda c: -abs(c["change_pct"])}.get(
        kind, lambda c: -c["change_pct"])
    return sorted(out, key=key)[:limit]


def fno_heatmap(feed: Feed | None = None) -> dict:
    """Every NIFTY 100 stock's day change, grouped by sector."""
    quotes = live.get_quotes(list(live.universe()["symbol"]), feed)
    if not quotes:
        raise live.MarketDataUnavailable("No stock prices are available right now.")
    sectors: dict[str, list[dict]] = {}
    for q in quotes.values():
        sectors.setdefault(q.sector or "Other", []).append(
            {"symbol": q.symbol, "change_pct": q.change_pct, "ltp": q.ltp})
    groups = [{"sector": name, "change_pct": round(sum(s["change_pct"] for s in items) / len(items), 2),
               "stocks": sorted(items, key=lambda s: s["change_pct"], reverse=True)}
              for name, items in sectors.items()]
    groups.sort(key=lambda g: g["change_pct"], reverse=True)
    sources = {q.source for q in quotes.values()}
    return {"groups": groups, "source": "live" if sources == {"live"} else "delayed",
            "priced": len(quotes), "universe": len(live.universe())}
