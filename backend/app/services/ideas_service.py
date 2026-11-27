"""Trade ideas and a backtestable strategy library.

Ideas here are *rule-based setups*, not advice. Each one names the screen
it came from and the arithmetic behind its levels -- entry at the last
price, stop and target as multiples of the 14-day average true range -- so
the user can see exactly why it exists and judge it.

Backtests run long-only on daily bars with no look-ahead: a signal computed
on a session's close is acted on the next session, and every entry and exit
pays a round-trip cost. Metrics come from ``wealthos_core`` so they are
computed exactly as the portfolio analytics compute them.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from wealthos_core.indicators import ema, macd, rsi, sma
from wealthos_core.metrics import sharpe_ratio
from wealthos_core.returns import annualized_return, total_return
from wealthos_core.risk import max_drawdown

from app.services import live_market_service as live
from app.services import options_service, screener_service

DISCLAIMER = (
    "Educational, rule-based setups generated from screens and live option "
    "prices. Not investment advice. Paper trade them before trusting them."
)

COST_PER_SIDE = 0.001   # brokerage, STT and slippage, roughly 0.1% a side


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _history(symbol: str) -> pd.DataFrame | None:
    hist = live.daily_store.history(symbol)
    if hist is None or len(hist) < 30:
        return None
    return hist[["open", "high", "low", "close", "volume"]]


def atr(frame: pd.DataFrame, period: int = 14) -> float | None:
    prev = frame["close"].shift(1)
    tr = pd.concat([frame["high"] - frame["low"], (frame["high"] - prev).abs(),
                    (frame["low"] - prev).abs()], axis=1).max(axis=1)
    value = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().iloc[-1]
    return None if pd.isna(value) else float(value)


def _idea_id(*parts: object) -> str:
    return hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=6).hexdigest()


def _levels(entry: float, unit: float, side: str, stop_mult: float, target_mult: float) -> dict:
    sign = 1 if side == "buy" else -1
    stop = entry - sign * stop_mult * unit
    target = entry + sign * target_mult * unit
    return {"entry": round(entry, 2), "stop_loss": round(stop, 2), "target": round(target, 2),
            "risk_reward": round(target_mult / stop_mult, 2)}


# --------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------

def _equity_ideas(db: Session, kind: str, limit: int, feed=None) -> list[dict]:
    rows, _ = screener_service.snapshots(db)
    quotes = live.get_quotes([r["symbol"] for r in rows], feed)
    session = live.last_session_date()
    ideas = []

    for r in rows:
        q = quotes.get(r["symbol"])
        hist = _history(r["symbol"])
        if q is None or hist is None:
            continue
        unit = atr(hist)
        if not unit:
            continue
        rv = r.get("rel_volume") or 0
        chg = r.get("change_1d_pct") or 0
        s20, s200 = r.get("sma_20"), r.get("sma_200")

        if kind == "intraday":
            if 1.0 <= chg <= 6.0 and rv >= 1.2 and s20 and q.ltp > s20:
                side, why = "buy", [f"Up {chg:.2f}% today on {rv:.2f}× normal volume",
                                    "Trading above its 20-day average"]
            elif -6.0 <= chg <= -1.0 and rv >= 1.2 and s20 and q.ltp < s20:
                side, why = "sell", [f"Down {abs(chg):.2f}% today on {rv:.2f}× normal volume",
                                     "Trading below its 20-day average"]
            else:
                continue
            levels = _levels(q.ltp, unit, side, 0.5, 0.9)
            horizon, score = "Intraday, exit by 15:15", abs(chg) * rv
        else:  # delivery
            near_high = (r.get("pct_from_52w_high") or -99) >= -3 and r.get("above_sma_200")
            dip = (r.get("rsi_14") or 100) <= 40 and r.get("above_sma_200")
            if near_high and 50 <= (r.get("rsi_14") or 0) <= 72:
                why = [f"{abs(r['pct_from_52w_high']):.2f}% below its 52-week high",
                       "Above its 200-day average", f"RSI {r['rsi_14']:.2f}: strong, not stretched"]
                score = 50 + (r.get("change_1m_pct") or 0)
            elif dip:
                why = [f"RSI {r['rsi_14']:.2f} after a pullback",
                       "Long-term trend intact: above its 200-day average"]
                score = 40 - (r.get("rsi_14") or 40)
            else:
                continue
            side = "buy"
            levels = _levels(q.ltp, unit, side, 2.0, 3.0)
            horizon = "2 to 6 weeks"
            if s200:
                why.append(f"200-day average at ₹{s200:,.2f}")

        ideas.append({
            "id": _idea_id(kind, r["symbol"], session, side),
            "kind": kind, "instrument": "equity", "symbol": r["symbol"], "name": r["name"],
            "sector": r["sector"], "side": side, "ltp": q.ltp, "change_pct": q.change_pct,
            **levels, "atr": round(unit, 2), "horizon": horizon, "rationale": why,
            "method": "Entry at the last price; stop and target are multiples of the 14-day ATR.",
            "price_source": q.source, "_score": score,
        })

    ideas.sort(key=lambda i: i["_score"], reverse=True)
    for i in ideas:
        i.pop("_score")
    return ideas[:limit]


def _option_leg(chain: dict, strike: int, leg: str, action: str) -> dict:
    row = next(r for r in chain["rows"] if r["strike"] == strike)
    return {"action": action, "strike": strike, "option_type": leg.upper(),
            "premium": row[leg]["ltp"], "expiry": chain["expiry"]}


def _fno_ideas(feed) -> list[dict]:
    """Spreads priced from the live Upstox chain. Requires a session."""
    feed.require()
    ideas = []
    session = live.last_session_date()
    for underlying in ("NIFTY", "BANKNIFTY"):
        # Wide enough that a monthly BANKNIFTY's wings, a full sigma out,
        # still land on listed strikes.
        try:
            chain = options_service.chain(feed, underlying, None, 50)
        except options_service.OptionsUnavailable as exc:
            if exc.state in ("no_master", "empty"):
                continue          # this underlying has no data today; the others may
            raise
        if not chain["atm_iv"] or chain["support"] is None or chain["resistance"] is None:
            continue  # the live chain lacks what a setup needs; skip rather than assume
        step, lot = chain["strike_step"] or 50, chain["lot_size"]
        atm, pcr, spot = chain["atm_strike"], chain["pcr"] or 1.0, chain["spot"]
        strikes = sorted({r["strike"] for r in chain["rows"]})
        # Size every spread from the one-sigma move to expiry. Fixed-width
        # spreads are nonsense across expiries: 200 points is wide for a
        # weekly NIFTY and at the money for a monthly BANKNIFTY.
        days = max((date.fromisoformat(chain["expiry"]) - session).days, 1)
        move = spot * chain["atm_iv"] / 100 * math.sqrt(days / 365)
        half = max(step, round(0.5 * move / step) * step)

        def clamp(k: float) -> float:
            # The nearest listed strike: real strike grids are not uniform.
            return min(strikes, key=lambda s: abs(s - k))

        if pcr >= 1.1 and spot >= chain["max_pain"]:
            bias, name = "bullish", "Bull call spread"
            legs = [_option_leg(chain, atm, "ce", "buy"),
                    _option_leg(chain, clamp(atm + half), "ce", "sell")]
            why = [f"Put-call ratio {pcr:.2f}: put writers outnumber call writers",
                   f"Spot {spot:,.2f} at or above max pain {chain['max_pain']:,}",
                   f"Heaviest put OI (support) at {chain['support']:,}"]
        elif pcr <= 0.85 and spot <= chain["max_pain"]:
            bias, name = "bearish", "Bear put spread"
            legs = [_option_leg(chain, atm, "pe", "buy"),
                    _option_leg(chain, clamp(atm - half), "pe", "sell")]
            why = [f"Put-call ratio {pcr:.2f}: call writers dominate",
                   f"Spot {spot:,.2f} at or below max pain {chain['max_pain']:,}",
                   f"Heaviest call OI (resistance) at {chain['resistance']:,}"]
        else:
            bias, name = "range-bound", "Iron condor"
            # Short strikes at the OI walls, but never inside half a sigma.
            hi = clamp(max(chain["resistance"], atm + half))
            lo = clamp(min(chain["support"], atm - half))
            legs = [_option_leg(chain, hi, "ce", "sell"),
                    _option_leg(chain, clamp(hi + half), "ce", "buy"),
                    _option_leg(chain, lo, "pe", "sell"),
                    _option_leg(chain, clamp(lo - half), "pe", "buy")]
            why = [f"Put-call ratio {pcr:.2f}: no strong directional positioning",
                   f"Short strikes at {hi:,} and {lo:,}: the OI walls, at least half the "
                   f"expected move ({move:,.0f} points) from spot"]

        if len({(l["strike"], l["option_type"]) for l in legs}) < len(legs):
            continue  # the chain could not fit the spread; no idea beats a broken one
        net = sum(l["premium"] * (1 if l["action"] == "sell" else -1) for l in legs)
        if name == "Iron condor":
            width = max(legs[1]["strike"] - legs[0]["strike"], legs[2]["strike"] - legs[3]["strike"])
            max_profit, max_loss = net * lot, (width - net) * lot
        else:
            width = abs(legs[1]["strike"] - legs[0]["strike"])
            debit = -net
            max_profit, max_loss = (width - debit) * lot, debit * lot

        ideas.append({
            "id": _idea_id("fno", underlying, session, name),
            "kind": "fno", "instrument": "option_strategy", "symbol": underlying,
            "name": f"{underlying} {name}", "bias": bias, "strategy": name,
            "expiry": chain["expiry"], "spot": spot, "lot_size": lot, "legs": legs,
            "net_premium": round(net, 2),
            "net_premium_type": "credit" if net > 0 else "debit",
            "max_profit": round(max_profit, 2), "max_loss": round(max_loss, 2),
            "rationale": why, "horizon": f"Until expiry {chain['expiry']}",
            "method": "Bias from put-call ratio and max pain; spread widths are half the "
                      "one-sigma expected move to expiry.",
            "expected_move": round(move, 2),
            "price_source": "live", "spot_source": "live",
        })
    return ideas


def _model_ideas(limit: int, feed=None) -> list[dict]:
    """The swing ensemble's top picks, in the same shape as the rule-based ideas."""
    from app.services import signals_service
    from wealthos_core.allocation import profile_for

    data = signals_service.signals(None, limit)
    profile = profile_for(None)
    quotes = live.get_quotes([p["symbol"] for p in data["picks"]], feed)
    card = data["model"]
    ideas = []
    for p in data["picks"]:
        q = quotes.get(p["symbol"])
        ltp = q.ltp if q is not None else p["last_close"]
        vol10 = p.get("vol_10d")
        if not ltp or not vol10:
            continue
        stop = round(ltp * (1 - profile.stop_multiple * vol10), 2)
        target = round(ltp * (1 + profile.target_multiple * vol10), 2)
        why = [f"Ranked {p['rank']} of {p['of']} by the swing ensemble"]
        for d in p["drivers"][:3]:
            if d["percentile"] is not None:
                why.append(f"{d['label'].capitalize()} at the {d['percentile']}th percentile {d['effect']} the score")
        rng = p.get("range_10d")
        if rng and rng.get("low") is not None:
            why.append(f"80% range for the next 10 sessions: {rng['low'] * 100:+.1f}% to {rng['high'] * 100:+.1f}%")
        ideas.append({
            "id": _idea_id("model", p["symbol"], data["as_of"], "buy"),
            "kind": "model", "instrument": "equity", "symbol": p["symbol"], "name": p["name"],
            "sector": p["sector"], "side": "buy", "ltp": ltp,
            "change_pct": q.change_pct if q is not None else None,
            "entry": round(ltp, 2), "stop_loss": stop, "target": target,
            "risk_reward": round(profile.target_multiple / profile.stop_multiple, 2),
            "atr": None, "horizon": "About 2 weeks (10 sessions)", "rationale": why,
            "method": (f"Swing ensemble v{card.get('version')} (LightGBM ranker, LightGBM regression and ridge), "
                       f"walk-forward tested from {card['oos'].get('first_test_year')}. Stop and target are "
                       f"{profile.stop_multiple} and {profile.target_multiple} times the 10-session volatility forecast."),
            "price_source": q.source if q is not None else "last close",
            "model": {"score": p["score"], "percentile": p["percentile"], "range_10d": rng,
                      "recommended": card.get("recommended")},
        })
    return ideas


def recommendations(db: Session, kind: str = "delivery", limit: int = 8, feed=None) -> dict:
    if kind not in {"intraday", "delivery", "fno", "model"}:
        raise ValueError("kind must be intraday, delivery, fno or model")
    if kind == "model":
        ideas = _model_ideas(limit, feed)
        from app.services.signals_service import DISCLAIMER as MODEL_DISCLAIMER
        return {"kind": kind, "ideas": ideas, "count": len(ideas), "disclaimer": MODEL_DISCLAIMER,
                "as_of": live.now_ist().isoformat(timespec="seconds")}
    if kind == "fno":
        from app.services.market_data import offline_feed
        ideas = _fno_ideas(feed or offline_feed())
    else:
        ideas = _equity_ideas(db, kind, limit, feed)
    return {"kind": kind, "ideas": ideas, "count": len(ideas), "disclaimer": DISCLAIMER,
            "as_of": live.now_ist().isoformat(timespec="seconds")}


# --------------------------------------------------------------------------
# Strategy library and backtests
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    style: str           # intraday | swing | positional
    description: str
    entry: str
    exit: str
    default_symbol: str = "NIFTY"


STRATEGIES = [
    Strategy("gap-and-go", "Gap and go", "intraday",
             "Rides opening strength: buys when a session opens above the previous high.",
             "Open above the previous session's high", "Exit at the same session's close",
             "RELIANCE"),
    Strategy("inside-day-breakout", "Inside-day breakout", "intraday",
             "After a quiet inside day, buys the next session's break of that day's high.",
             "High breaks above the previous inside day's high", "Exit at that session's close",
             "HDFCBANK"),
    Strategy("ema-crossover", "EMA 9/21 crossover", "swing",
             "A fast trend-following swing system.",
             "9-day EMA crosses above the 21-day EMA", "9-day EMA crosses back below the 21-day",
             "NIFTY"),
    Strategy("rsi-reversion", "RSI mean reversion", "swing",
             "Buys short-term oversold dips inside a long-term uptrend.",
             "RSI(14) below 30 while above the 200-day average",
             "RSI(14) recovers above 55, or 15 sessions pass", "INFY"),
    Strategy("macd-momentum", "MACD momentum", "swing",
             "Holds while MACD is above its signal line.",
             "MACD crosses above its signal line", "MACD crosses below its signal line", "TCS"),
    Strategy("breakout-52w", "52-week breakout", "positional",
             "Buys fresh 52-week highs and holds while the trend holds.",
             "Close at a new 52-week high", "Close below the 50-day average", "BHARTIARTL"),
    Strategy("golden-cross-trend", "Golden cross trend", "positional",
             "The classic long-term trend filter.",
             "50-day average above the 200-day", "50-day average back below the 200-day", "NIFTY"),
    Strategy("buy-and-hold", "Buy and hold", "positional",
             "The baseline every other strategy must beat.",
             "Buy on the first session", "Never sell", "NIFTY"),
]
STRATEGIES_BY_ID = {s.id: s for s in STRATEGIES}


def list_strategies(style: str | None = None) -> list[dict]:
    return [s.__dict__ | {"backtestable": True}
            for s in STRATEGIES if style is None or s.style == style]


def _positions(strategy_id: str, f: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(position held over each session's close-to-close return, intraday-only flag).

    Positions are decided on information available at the prior close and
    shifted forward one session before being applied: no look-ahead.
    """
    close = f["close"]
    flat = pd.Series(0.0, index=f.index)

    if strategy_id == "buy-and-hold":
        return pd.Series(1.0, index=f.index), flat

    if strategy_id == "ema-crossover":
        state = (ema(close, 9) > ema(close, 21)).astype(float)
    elif strategy_id == "macd-momentum":
        m = macd(close)
        state = (m["macd"] > m["signal"]).astype(float)
    elif strategy_id == "golden-cross-trend":
        state = (sma(close, 50) > sma(close, 200)).astype(float)
    elif strategy_id == "breakout-52w":
        high52 = close.rolling(252, min_periods=200).max()
        below50 = close < sma(close, 50)
        state = pd.Series(np.nan, index=f.index)
        state[close >= high52] = 1.0
        state[below50] = 0.0
        state = state.ffill().fillna(0.0)
    elif strategy_id == "rsi-reversion":
        r = rsi(close)
        above200 = close > sma(close, 200)
        held, days, out = 0.0, 0, []
        for i in range(len(f)):
            if held == 0.0 and r.iloc[i] < 30 and above200.iloc[i]:
                held, days = 1.0, 0
            elif held == 1.0:
                days += 1
                if r.iloc[i] > 55 or days >= 15:
                    held = 0.0
            out.append(held)
        state = pd.Series(out, index=f.index)
    elif strategy_id in {"gap-and-go", "inside-day-breakout"}:
        # Intraday: the trade is open-to-close (or trigger-to-close) inside
        # one session, so it is returned separately from overnight holding.
        return flat, pd.Series(1.0, index=f.index)
    else:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    return state.shift(1).fillna(0.0), flat


def _intraday_returns(strategy_id: str, f: pd.DataFrame) -> pd.Series:
    prev_high = f["high"].shift(1)
    if strategy_id == "gap-and-go":
        trigger = f["open"] > prev_high
        entry = f["open"]
    else:
        inside = (f["high"].shift(1) < f["high"].shift(2)) & (f["low"].shift(1) > f["low"].shift(2))
        trigger = inside & (f["high"] > prev_high)
        entry = np.maximum(f["open"], prev_high)
    gross = (f["close"] / entry - 1).where(trigger, 0.0)
    return gross - (2 * COST_PER_SIDE) * trigger.astype(float)


def backtest(strategy_id: str, symbol: str | None = None, years: float = 2.0) -> dict:
    strategy = STRATEGIES_BY_ID.get(strategy_id)
    if strategy is None:
        raise ValueError(f"Unknown strategy: {strategy_id!r}")
    symbol = (symbol or strategy.default_symbol).upper()
    if live.instrument_info(symbol) is None:
        raise ValueError(f"Unknown symbol: {symbol!r}")

    hist = live.daily_store.history(symbol)
    if hist is None or len(hist) < 60:
        try:
            candles = live.get_candles(symbol, "1D", "1Y" if years <= 1 else "5Y")
        except live.MarketDataUnavailable as exc:
            return {"available": False, "reason": str(exc)}
        if len(candles["bars"]) < 60:
            return {"available": False, "reason": f"Not enough daily history for {symbol}."}
        hist = pd.DataFrame(candles["bars"])
        hist.index = pd.to_datetime(hist["time"], unit="s")
    f = hist[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    f = f[f.index >= f.index.max() - pd.Timedelta(days=int(365 * years))]

    market = f["close"].pct_change().fillna(0.0)
    if strategy.style == "intraday":
        strat = _intraday_returns(strategy_id, f).fillna(0.0)
        trades = int((strat != 0).sum())
        wins = int((strat > 0).sum())
        exposure = trades / max(len(f), 1)
    else:
        pos, _ = _positions(strategy_id, f)
        turnover = pos.diff().abs().fillna(pos.iloc[0])
        strat = pos * market - turnover * COST_PER_SIDE
        entries = (pos.diff() > 0).sum() + (1 if pos.iloc[0] > 0 else 0)
        trades = int(entries)
        # A trade's result: compounded return from entry to exit.
        trade_id = (pos.diff() > 0).cumsum().where(pos > 0)
        per_trade = (1 + strat.where(pos > 0)).groupby(trade_id).prod() - 1
        wins = int((per_trade > 0).sum())
        exposure = float(pos.mean())

    equity = (1 + strat).cumprod()
    bench = (1 + market).cumprod()
    step = max(1, len(equity) // 200)
    curve = [{"time": int(pd.Timestamp(t).timestamp()), "strategy": round(float(e), 4),
              "buy_and_hold": round(float(b), 4)}
             for t, e, b in zip(equity.index[::step], equity.values[::step], bench.values[::step])]

    def pct(x: float) -> float | None:
        return None if x is None or math.isnan(x) else round(x * 100, 2)

    sharpe = sharpe_ratio(strat)
    return {
        "available": True,
        "strategy": strategy.__dict__,
        "symbol": symbol,
        "start": str(f.index.min().date()), "end": str(f.index.max().date()),
        "sessions": len(f),
        "total_return_pct": pct(total_return(strat)),
        "annualized_return_pct": pct(annualized_return(strat)),
        "max_drawdown_pct": pct(max_drawdown(strat)),
        "sharpe_ratio": None if math.isnan(sharpe) else round(sharpe, 2),
        "buy_and_hold_return_pct": pct(total_return(market)),
        "trades": trades,
        "win_rate_pct": round(wins / trades * 100, 2) if trades else None,
        "exposure_pct": round(exposure * 100, 2),
        "cost_per_side_pct": COST_PER_SIDE * 100,
        "equity_curve": curve,
        "assumptions": [
            "Long only, daily bars, signals acted on the next session (no look-ahead).",
            f"{COST_PER_SIDE * 100:.1f}% cost on every entry and exit.",
            "Past performance on two years of data says little about the future.",
        ],
    }
