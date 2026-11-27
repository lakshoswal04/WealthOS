"""Autopilot: the trained models, applied to one user's money and portfolio.

Three jobs, all on real prices and the models trained in ml/pipelines 13-19:

* **Run a paper sleeve.** Every ``cadence_sessions`` completed sessions it
  rebuilds its basket from the swing ensemble's picks, sized by forecast
  volatility for the user's risk profile and scaled by the market regime,
  and places the paper orders itself (the user switched it on and can pause
  it). Every run is recorded with its orders and reasons, and posted to the
  notification bell.
* **Review the user's real holdings** (CSV import or Upstox sync): weight,
  sector, risk contribution, and the models' view of each stock. It suggests;
  it does not trade real money.
* **Plan an amount** ("how can I invest 50,000 across sectors?") from live
  prices and the models, whether or not the user holds anything yet.

Personalisation comes from the user's own data: their risk profile, their
real holdings (Autopilot leans away from sectors they already hold heavily),
names and sectors they told it to avoid (settings and "Things to avoid" in
Memory). The models themselves are trained on market history, not on one
person's handful of holdings, which would only teach them noise.
"""

from __future__ import annotations

import logging
import math
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Alert, AutopilotRun, AutopilotSettings, User
from app.models.enums import AlertSeverity, AlertType
from app.services import live_market_service as live
from app.services import paper_trading_service as paper
from app.services import signals_service as signals
from app.services.market_data import feed_for
from wealthos_core import swing_features as sf
from wealthos_core.allocation import RiskProfile, profile_for, size_basket

log = logging.getLogger("wealthos.autopilot")

TAG = "autopilot"
MIN_BUDGET = 10_000
MIN_TRADE = 1_500            # rupees; smaller adjustments are not worth the costs
SECTOR_SHARE = 0.35          # at most this share of the basket's names in one sector
HEAVY_SECTOR = 0.35          # a sector this large in real holdings is not added to
DISCLAIMER = signals.DISCLAIMER

SECTOR_ALIASES = {
    "bank": "Financial Services", "banks": "Financial Services", "banking": "Financial Services",
    "finance": "Financial Services", "financial": "Financial Services", "nbfc": "Financial Services",
    "insurance": "Financial Services",
    "it": "Information Technology", "tech": "Information Technology", "technology": "Information Technology",
    "software": "Information Technology",
    "pharma": "Healthcare", "health": "Healthcare", "healthcare": "Healthcare", "hospital": "Healthcare",
    "auto": "Automobile", "autos": "Automobile", "automobile": "Automobile", "car": "Automobile",
    "fmcg": "FMCG", "consumer": "FMCG",
    "metal": "Metals & Mining", "metals": "Metals & Mining", "mining": "Metals & Mining", "steel": "Metals & Mining",
    "power": "Power", "energy": "Oil Gas & Fuels", "oil": "Oil Gas & Fuels", "gas": "Oil Gas & Fuels",
    "infra": "Capital Goods", "infrastructure": "Capital Goods", "capital goods": "Capital Goods",
    "defence": "Capital Goods", "defense": "Capital Goods",
    "cement": "Construction Materials", "realty": "Realty", "real estate": "Realty",
    "telecom": "Telecommunication", "chemicals": "Chemicals",
}

# Long-term core: real, listed ETFs priced from the analytics table.
CORE_ETFS = {"NIFTYBEES": "Indian equity (NIFTY 50)", "GOLDBEES": "Gold", "DEBT": "Government bonds (GILT5YBEES)"}
CORE_SHARE = {"conservative": 0.8, "moderate": 0.6, "aggressive": 0.4}
EQUITY_TILT = {"conservative": 0.0, "moderate": 0.35, "aggressive": 0.6}


class AutopilotError(ValueError):
    pass


def _tolerance(user: User) -> str | None:
    rt = getattr(user, "risk_tolerance", None)
    return getattr(rt, "value", rt)


def _num(v, digits: int = 2):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(f) else round(f, digits)


# --------------------------------------------------------------------------- settings

def settings_for(db: Session, user: User) -> AutopilotSettings:
    row = db.scalar(select(AutopilotSettings).where(AutopilotSettings.user_id == user.id))
    if row is None:
        row = AutopilotSettings(user_id=user.id, enabled=False, budget=100_000.0, cadence_sessions=5,
                                avoid_symbols=[], avoid_sectors=[], sleeve={}, sleeve_cash=None)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def settings_dict(row: AutopilotSettings) -> dict:
    return {
        "enabled": row.enabled, "budget": row.budget, "cadence_sessions": row.cadence_sessions,
        "avoid_symbols": list(row.avoid_symbols or []), "avoid_sectors": list(row.avoid_sectors or []),
        "sleeve": dict(row.sleeve or {}), "sleeve_cash": _num(row.sleeve_cash),
        "last_run_on": str(row.last_run_on) if row.last_run_on else None,
    }


def known_sectors() -> list[str]:
    uni = live.universe()
    return sorted(uni["sector"].dropna().unique()) if not uni.empty else []


def resolve_sector(text: str) -> str | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    sectors = known_sectors()
    for s in sectors:
        if s.lower() == t:
            return s
    if t in SECTOR_ALIASES:
        return SECTOR_ALIASES[t]
    # Partial names ("financial", "consumer dur") only from four letters up:
    # "it" is inside "capital".
    if len(t) >= 4:
        for s in sectors:
            if t in s.lower():
                return s
    return None


def update_settings(db: Session, user: User, *, enabled: bool | None = None, budget: float | None = None,
                    cadence_sessions: int | None = None, avoid_symbols: list[str] | None = None,
                    avoid_sectors: list[str] | None = None) -> dict:
    row = settings_for(db, user)
    if budget is not None:
        if not math.isfinite(budget) or budget < MIN_BUDGET:
            raise AutopilotError(f"Autopilot needs a budget of at least ₹{MIN_BUDGET:,}.")
        if row.sleeve:
            raise AutopilotError("Change the budget after Autopilot has sold its holdings (pause, then reset).")
        row.budget = float(budget)
        row.sleeve_cash = None
    if cadence_sessions is not None:
        if cadence_sessions not in (5, 10, 20):
            raise AutopilotError("Rebalance every 5, 10 or 20 sessions.")
        row.cadence_sessions = cadence_sessions
    if avoid_symbols is not None:
        uni = set(live.universe()["symbol"])
        bad = [s for s in avoid_symbols if s.upper() not in uni]
        if bad:
            raise AutopilotError(f"Not NIFTY 100 stocks: {', '.join(bad)}.")
        row.avoid_symbols = sorted({s.upper() for s in avoid_symbols})
    if avoid_sectors is not None:
        resolved = [resolve_sector(s) for s in avoid_sectors]
        if None in resolved:
            raise AutopilotError(f"Sectors must be among: {', '.join(known_sectors())}.")
        row.avoid_sectors = sorted(set(resolved))
    if enabled is not None:
        if enabled and not row.enabled:
            acct = paper.account(db, user)
            free = float(acct.cash) - paper.margin_used(paper._positions(db, user))
            if row.sleeve_cash is None and free < row.budget:
                raise AutopilotError(f"Only ₹{max(free, 0):,.0f} is free in the paper account; "
                                     f"lower the budget below that.")
            if row.sleeve_cash is None:
                row.sleeve_cash = float(row.budget)
        row.enabled = enabled
    db.commit()
    return settings_dict(row)


def _avoided(db: Session, user: User, row: AutopilotSettings) -> tuple[set[str], set[str]]:
    """Avoid lists from settings plus 'Things to avoid' in Memory."""
    from app.services import account_service

    symbols = {s.upper() for s in (row.avoid_symbols or [])}
    sectors = set(row.avoid_sectors or [])
    uni = live.universe()
    names = dict(zip(uni["symbol"], uni["name"]))
    for m in account_service.memories(db, user):
        if m.section != "avoid":
            continue
        text = m.text.lower()
        for sym, name in names.items():
            if sym.lower() in text.split() or name.lower() in text:
                symbols.add(sym)
        for word, sector in list(SECTOR_ALIASES.items()) + [(s.lower(), s) for s in known_sectors()]:
            if f" {word} " in f" {text} " or f" {word}s " in f" {text} ":
                sectors.add(sector)
    return symbols, sectors


# --------------------------------------------------------------------------- real holdings

def real_holdings(db: Session, user: User) -> list:
    from app.services import portfolio_service

    return portfolio_service.value_holdings(db, portfolio_service.get_holdings(db, user))


def _sector_weights(rows) -> dict[str, float]:
    total = sum(r.market_value or 0 for r in rows)
    out: dict[str, float] = {}
    for r in rows:
        if r.market_value:
            key = r.sector or str(r.asset_class)
            out[key] = out.get(key, 0.0) + r.market_value / total
    return out


# --------------------------------------------------------------------------- target basket

def _select(snap: signals.Snapshot, profile: RiskProfile, avoid_symbols: set[str], avoid_sectors: set[str],
            heavy: set[str], n: int, sectors: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Top-ranked names under the sector cap, skipping avoided and heavy sectors."""
    table = snap.table
    chosen, excluded = [], []
    per_sector: dict[str, int] = {}
    cap = max(1, int(round(n * SECTOR_SHARE)))
    for sym, r in table.iterrows():
        if len(chosen) >= n:
            break
        sector = r["sector"]
        if sectors and sector not in sectors:
            continue
        reason = ("you asked Autopilot to avoid it" if sym in avoid_symbols else
                  f"you asked to avoid {sector}" if sector in avoid_sectors else
                  f"{sector} is already a large part of your real holdings" if sector in heavy and not sectors else
                  None)
        if reason:
            if r["rank"] <= n * 2:
                excluded.append({"symbol": sym, "rank": int(r["rank"]), "reason": reason})
            continue
        if not sectors and per_sector.get(sector, 0) >= cap:
            continue
        chosen.append(sym)
        per_sector[sector] = per_sector.get(sector, 0) + 1
    return chosen, excluded


def target(db: Session, user: User, base_value: float | None = None) -> dict:
    row = settings_for(db, user)
    snap = signals.snapshot()
    profile = profile_for(_tolerance(user))
    exposure = signals.profile_exposure(snap, profile)
    avoid_symbols, avoid_sectors = _avoided(db, user, row)
    sector_w = _sector_weights(real_holdings(db, user))
    heavy = {s for s, w in sector_w.items() if w >= HEAVY_SECTOR}
    names, excluded = _select(snap, profile, avoid_symbols, avoid_sectors, heavy, profile.max_names)
    if not names:
        raise AutopilotError("No eligible stocks remain after your avoid lists.")
    top = snap.table.loc[names]
    returns = np.log(snap.wide.close[names].ffill(limit=5)).diff().iloc[-126:]
    weights, scale, port_vol = size_basket(top["vol_annual"], returns, profile)
    base = float(base_value if base_value is not None else (row.sleeve_cash if row.sleeve_cash is not None else row.budget))
    invest = base * exposure
    universe = len(snap.table)
    positions = []
    for sym in names:
        view = signals.row_view(sym, top.loc[sym], profile, universe)
        positions.append({**{k: view[k] for k in ("symbol", "name", "sector", "rank", "of", "score", "range_10d",
                                                  "vol_annual", "drivers", "stop", "target")},
                          "weight": round(float(weights[sym]), 4), "value": round(invest * float(weights[sym]), 2),
                          "reference_price": view["last_close"]})
    notes = [f"{profile.name.capitalize()} profile: up to {profile.max_names} stocks, at most "
             f"{profile.max_weight:.0%} in one, aiming for about {profile.vol_target:.0%} annual volatility."]
    if snap.regime.get("available"):
        notes.append(f"Market regime: {snap.regime['state']}, so {exposure:.0%} of the sleeve is invested.")
    if heavy:
        notes.append(f"Leaning away from {', '.join(sorted(heavy))}: already {HEAVY_SECTOR:.0%}+ of your real holdings.")
    if scale < 0.999:
        notes.append(f"Sizes scaled to {scale:.0%} to stay near your volatility target.")
    return {"as_of": str(snap.as_of.date()), "profile": profile.as_dict(), "exposure": round(exposure, 4),
            "regime": {k: v for k, v in snap.regime.items() if k != "history"}, "base_value": round(base, 2),
            "positions": positions, "excluded": excluded, "notes": notes, "model": snap.card}


# --------------------------------------------------------------------------- the sleeve

def _price(sym: str, feed, fallback: float | None) -> tuple[float | None, str]:
    q = live.get_quote(sym, feed)
    if q is not None and q.ltp:
        return float(q.ltp), q.source
    return (float(fallback), "last close") if fallback else (None, "unavailable")


def _held_quantities(db: Session, user: User) -> dict[str, int]:
    return {p.symbol: int(p.quantity) for p in paper._positions(db, user)
            if p.instrument == "equity" and p.product == "delivery" and p.quantity > 0}


def plan_trades(db: Session, user: User) -> dict:
    """The orders the next rebalance would place (nothing is placed)."""
    row = settings_for(db, user)
    feed = feed_for(db, user)
    held = _held_quantities(db, user)
    # Autopilot owns only what its ledger says, and never more than is held.
    sleeve = {s: min(int(q), held.get(s, 0)) for s, q in (row.sleeve or {}).items()}
    sleeve = {s: q for s, q in sleeve.items() if q > 0}
    cash = float(row.sleeve_cash if row.sleeve_cash is not None else row.budget)
    prices: dict[str, tuple[float | None, str]] = {}
    snap = signals.snapshot()
    for s in sleeve:
        last = float(snap.wide.close[s].dropna().iloc[-1]) if s in snap.wide.close else None
        prices[s] = _price(s, feed, last)
    sleeve_value = sum(q * (prices[s][0] or 0) for s, q in sleeve.items())
    tgt = target(db, user, base_value=cash + sleeve_value)
    orders = []
    target_qty: dict[str, int] = {}
    for p in tgt["positions"]:
        if p["symbol"] not in prices:
            prices[p["symbol"]] = _price(p["symbol"], feed, p["reference_price"])
        price = prices[p["symbol"]][0]
        target_qty[p["symbol"]] = int(p["value"] // price) if price else 0
    for sym in sorted(set(sleeve) | set(target_qty)):
        have, want = sleeve.get(sym, 0), target_qty.get(sym, 0)
        price, source = prices.get(sym, (None, "unavailable"))
        if price is None or have == want:
            continue
        delta = want - have
        if want > 0 and abs(delta) * price < MIN_TRADE:
            continue                       # a small top-up is not worth the costs
        reason = ("no longer among the model's picks" if want == 0 else
                  "new pick" if have == 0 else "resized to its target weight")
        orders.append({"symbol": sym, "side": "buy" if delta > 0 else "sell", "quantity": abs(delta),
                       "price": round(price, 2), "value": round(abs(delta) * price, 2), "price_source": source,
                       "reason": reason})
    orders.sort(key=lambda o: o["side"] != "sell")         # sells first, to free cash
    return {"target": tgt, "orders": orders, "sleeve": sleeve, "sleeve_cash": round(cash, 2),
            "sleeve_value": round(sleeve_value, 2)}


def rebalance(db: Session, user: User, mode: str = "manual", run_on: date | None = None) -> dict:
    row = settings_for(db, user)
    if mode == "auto" and not row.enabled:
        return {"status": "skipped", "reason": "Autopilot is paused."}
    if row.sleeve_cash is None:
        row.sleeve_cash = float(row.budget)
    plan = plan_trades(db, user)
    feed = feed_for(db, user)
    sleeve = dict(plan["sleeve"])
    cash = float(row.sleeve_cash)
    placed, failed = [], []
    for o in plan["orders"]:
        qty = o["quantity"]
        if o["side"] == "buy":
            qty = min(qty, int(cash // o["price"])) if o["price"] else 0
            if qty <= 0:
                failed.append({**o, "error": "not enough sleeve cash"})
                continue
        try:
            order = paper.place_order(db, user, instrument="equity", symbol=o["symbol"], side=o["side"],
                                      quantity=qty, product="delivery", tag=TAG, feed=feed)
        except paper.OrderRejected as exc:
            failed.append({**o, "error": str(exc)})
            continue
        if order.status != "filled":
            failed.append({**o, "error": order.reject_reason or order.status})
            continue
        fill = float(order.fill_price) * int(order.quantity)
        if o["side"] == "buy":
            sleeve[o["symbol"]] = sleeve.get(o["symbol"], 0) + int(order.quantity)
            cash -= fill
        else:
            sleeve[o["symbol"]] = sleeve.get(o["symbol"], 0) - int(order.quantity)
            cash += fill
        placed.append({**o, "quantity": int(order.quantity), "fill_price": float(order.fill_price),
                       "order_id": order.id})
    row.sleeve = {s: q for s, q in sleeve.items() if q > 0}
    row.sleeve_cash = round(cash, 2)
    run_day = run_on or signals.snapshot().as_of.date()
    row.last_run_on = run_day
    status = "done" if not failed else ("partial" if placed else "failed")
    tgt = plan["target"]
    run = AutopilotRun(user_id=user.id, run_on=run_day, mode=mode, status=status, regime=tgt["regime"],
                       target=[{k: p[k] for k in ("symbol", "sector", "rank", "weight", "value")} for p in tgt["positions"]],
                       orders=placed + failed, notes=tgt["notes"],
                       sleeve_value=None)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "skipped", "reason": f"Autopilot already ran for {run_day}."}
    run.sleeve_value = round(cash + sum(q * (_price(s, feed, None)[0] or 0) for s, q in row.sleeve.items()), 2)
    added = sum(1 for o in placed if o["side"] == "buy")
    exited = sum(1 for o in placed if o["side"] == "sell")
    db.add(Alert(user_id=user.id, alert_type=AlertType.AUTOPILOT, severity=AlertSeverity.INFO,
                 title="Autopilot rebalanced your paper sleeve",
                 message=(f"{len(placed)} paper order(s) on {run_day}: {added} added or topped up, "
                          f"{exited} trimmed or exited"
                          + (f"; {len(failed)} could not be placed" if failed else "") + ". See Autopilot for the reasons."),
                 details={"run_on": str(run_day), "orders": len(placed)}))
    db.commit()
    return run_dict(run)


def run_dict(run: AutopilotRun) -> dict:
    return {"id": run.id, "run_on": str(run.run_on), "mode": run.mode, "status": run.status, "regime": run.regime,
            "target": run.target, "orders": run.orders, "notes": run.notes, "sleeve_value": run.sleeve_value,
            "created_at": run.created_at.isoformat() if run.created_at else None}


def runs(db: Session, user: User, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(AutopilotRun).where(AutopilotRun.user_id == user.id)
                      .order_by(AutopilotRun.run_on.desc(), AutopilotRun.id.desc()).limit(limit)).all()
    return [run_dict(r) for r in rows]


def sessions_since(calendar: pd.DatetimeIndex, last: date | None, today: date) -> int:
    if last is None:
        return 10_000
    return int(((calendar.date > last) & (calendar.date <= today)).sum())


def is_due(row: AutopilotSettings, calendar: pd.DatetimeIndex, today: date) -> bool:
    return bool(row.enabled) and sessions_since(calendar, row.last_run_on, today) >= row.cadence_sessions


def run_due(db: Session) -> list[dict]:
    """Run every enabled Autopilot whose rebalance is due on the latest completed session."""
    try:
        snap = signals.snapshot()
    except signals.SignalsUnavailable as exc:
        log.info("autopilot: signals unavailable (%s)", exc)
        return []
    today = snap.as_of.date()
    calendar = snap.wide.close.index
    out = []
    rows = db.scalars(select(AutopilotSettings).where(AutopilotSettings.enabled.is_(True))).all()
    for row in rows:
        if not is_due(row, calendar, today):
            continue
        user = db.get(User, row.user_id)
        try:
            out.append({"user_id": row.user_id, **rebalance(db, user, mode="auto", run_on=today)})
        except Exception as exc:  # noqa: BLE001 - one user's failure must not stop the others
            db.rollback()
            log.warning("autopilot run failed for user %s: %s", row.user_id, exc)
    return out


def status(db: Session, user: User) -> dict:
    row = settings_for(db, user)
    feed = feed_for(db, user)
    holdings, value = [], float(row.sleeve_cash if row.sleeve_cash is not None else row.budget)
    for sym, qty in (row.sleeve or {}).items():
        price, source = _price(sym, feed, None)
        holdings.append({"symbol": sym, "quantity": qty, "price": _num(price), "value": _num((price or 0) * qty),
                         "price_source": source})
        value += (price or 0) * qty
    next_in = None
    try:
        snap = signals.snapshot()
        done = sessions_since(snap.wide.close.index, row.last_run_on, snap.as_of.date())
        next_in = max(row.cadence_sessions - done, 0) if row.last_run_on else 0
    except signals.SignalsUnavailable:
        pass
    pnl = value - row.budget if row.sleeve_cash is not None else 0.0
    return {"settings": settings_dict(row), "holdings": holdings, "sleeve_value": round(value, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl / row.budget * 100, 2) if row.budget else None,
            "next_run_in_sessions": next_in, "runs": runs(db, user, 5), "disclaimer": DISCLAIMER}


# --------------------------------------------------------------------------- review of real holdings

def review_holdings(db: Session, user: User) -> dict:
    rows = real_holdings(db, user)
    profile = profile_for(_tolerance(user))
    if not rows:
        return {"available": False, "reason": "No holdings imported yet. Import a CSV or sync Upstox to get a review.",
                "profile": profile.as_dict()}
    snap = signals.snapshot()
    universe = len(snap.table)
    vols = snap.table["vol_annual"] if "vol_annual" in snap.table else pd.Series(dtype=float)
    sector_w = _sector_weights(rows)
    items, suggestions = [], []
    total_risk = 0.0
    for r in rows:
        w = r.weight or 0.0
        item = {"symbol": r.symbol, "name": r.name, "sector": r.sector, "asset_class": str(r.asset_class),
                "weight": _num(w, 4), "market_value": _num(r.market_value), "gain_pct": _num((r.unrealized_gain_pct or 0) * 100)}
        if r.symbol in snap.table.index:
            v = signals.row_view(r.symbol, snap.table.loc[r.symbol], profile, universe)
            item["model"] = {k: v[k] for k in ("rank", "of", "percentile", "range_10d", "vol_annual", "drivers")}
            vol = float(vols.get(r.symbol, np.nan))
        else:
            in_index = r.symbol in set(live.universe()["symbol"])
            item["model"] = None
            item["model_note"] = ("Long-term core holding (ETF, gold, bonds or cash): the swing models do not rate it."
                                  if str(r.asset_class) != "equity" else
                                  "Not among the 60 most-traded NIFTY 100 stocks today, so not ranked."
                                  if in_index else "Outside the NIFTY 100 the models cover.")
            vol = np.nan
        item["risk_contribution"] = _num(w * vol if np.isfinite(vol) else None, 4)
        if np.isfinite(vol):
            total_risk += w * vol
        items.append(item)
        rank = (item.get("model") or {}).get("percentile")
        if w > profile.max_weight * 1.5 and str(r.asset_class) == "equity":
            suggestions.append({"symbol": r.symbol, "kind": "concentration",
                                "text": f"{r.symbol} is {w:.0%} of your portfolio, above the {profile.max_weight:.0%} "
                                        f"a {profile.name} profile holds in one stock."})
        if rank is not None and rank <= 20:
            suggestions.append({"symbol": r.symbol, "kind": "weak_rank",
                                "text": f"{r.symbol} ranks in the bottom fifth of the models' universe for the next "
                                        f"10 sessions ({item['model']['rank']} of {universe}). A ranking, not a forecast."})
    for sector, w in sector_w.items():
        if w >= HEAVY_SECTOR and sector not in ("Gold", "Sovereign Debt", "Cash"):
            suggestions.append({"symbol": None, "kind": "sector",
                                "text": f"{sector} is {w:.0%} of your holdings; Autopilot leans away from adding more."})
    held = {r.symbol for r in rows}
    ideas = [s for s in snap.table.index[:15] if s not in held][:5]
    if ideas:
        suggestions.append({"symbol": None, "kind": "diversify",
                            "text": "Top-ranked stocks you do not hold: " + ", ".join(ideas) + "."})
    return {"available": True, "as_of": str(snap.as_of.date()), "profile": profile.as_dict(),
            "regime": {k: v for k, v in snap.regime.items() if k != "history"},
            "holdings": items, "sector_weights": {k: _num(v, 4) for k, v in sector_w.items()},
            "equity_risk_estimate": _num(total_risk, 4), "suggestions": suggestions,
            "note": "Suggestions are research signals about your own holdings. Nothing is traded in your real account.",
            "disclaimer": DISCLAIMER}


# --------------------------------------------------------------------------- planning an amount

def _core_weights(db: Session, profile: RiskProfile) -> dict[str, float]:
    from app.services.market_service import market_cache

    panel = market_cache.panel(db)
    cols = [c for c in CORE_ETFS if c in panel.columns]
    rets = panel[cols].iloc[-756:].pct_change().dropna(how="all")
    vol = rets.std() * np.sqrt(252)
    rp = (1 / vol) / (1 / vol).sum()
    eq = pd.Series({c: 1.0 if c == "NIFTYBEES" else 0.0 for c in cols})
    tilt = EQUITY_TILT.get(profile.name, 0.35)
    w = (1 - tilt) * rp + tilt * eq
    return (w / w.sum()).to_dict()


def allocate(db: Session, user: User, amount: float, sectors: list[str] | None = None,
             horizon: str = "swing") -> dict:
    """How to split ``amount`` across sectors (swing) or core and satellite (long term)."""
    if not math.isfinite(amount) or amount < 5_000:
        raise AutopilotError("Plan at least ₹5,000.")
    profile = profile_for(_tolerance(user))
    snap = signals.snapshot()
    feed = feed_for(db, user)
    row = settings_for(db, user)
    avoid_symbols, avoid_sectors = _avoided(db, user, row)
    wanted = None
    unknown = []
    if sectors:
        wanted = []
        for s in sectors:
            r = resolve_sector(s)
            (wanted.append(r) if r else unknown.append(s))
        wanted = list(dict.fromkeys(wanted)) or None
    held = {r.symbol for r in real_holdings(db, user)}
    notes = []
    core, satellite_amount = [], amount
    if horizon == "long_term":
        core_amount = amount * CORE_SHARE.get(profile.name, 0.6)
        satellite_amount = amount - core_amount
        from app.services.market_service import market_cache

        prices = market_cache.latest_prices(db, list(CORE_ETFS))
        for sym, w in _core_weights(db, profile).items():
            price = prices.get(sym)
            value = core_amount * w
            core.append({"symbol": "GILT5YBEES" if sym == "DEBT" else sym, "what": CORE_ETFS[sym],
                         "weight": round(w, 4), "value": round(value, 2),
                         "units": int(value // float(price)) if price and sym != "DEBT" else None})
        notes.append("The core is long-term: index, gold and government-bond ETFs, weighted by risk parity on their "
                     "real return history and tilted to equity for your profile. Buy ETFs at your broker; the paper "
                     "account trades NIFTY 100 stocks only.")
        notes.append(f"The satellite uses the swing models, whose horizon is {sf.HORIZON} sessions; review it every "
                     "couple of weeks.")
    n = len(wanted) if wanted else min(profile.max_names, 6)
    per_sector_names = 1 if not wanted or satellite_amount / max(len(wanted), 1) < 40_000 else 2
    names, excluded = [], []
    if wanted:
        for sector in wanted:
            picked, ex = _select(snap, profile, avoid_symbols, avoid_sectors, set(), per_sector_names, [sector])
            names += picked
            excluded += ex
            if not picked:
                notes.append(f"No eligible {sector} stock among today's ranked universe.")
    else:
        names, excluded = _select(snap, profile, avoid_symbols, avoid_sectors, set(), n)
    exposure = signals.profile_exposure(snap, profile)
    picks = []
    if names:
        top = snap.table.loc[names]
        returns = np.log(snap.wide.close[names].ffill(limit=5)).diff().iloc[-126:]
        weights, _, _ = size_basket(top["vol_annual"], returns, profile)
        weights = weights / weights.sum()            # the amount is the user's to place; regime noted below
        universe = len(snap.table)
        for sym in names:
            view = signals.row_view(sym, top.loc[sym], profile, universe)
            price, source = _price(sym, feed, view["last_close"])
            value = satellite_amount * float(weights[sym])
            qty = int(value // price) if price else 0
            picks.append({"sector": view["sector"], "symbol": sym, "name": view["name"], "rank": view["rank"],
                          "of": view["of"], "weight": round(float(weights[sym]), 4), "price": _num(price),
                          "price_source": source, "quantity": qty, "cost": _num(qty * (price or 0)),
                          "range_10d": view["range_10d"], "stop": view["stop"], "target": view["target"],
                          "already_held": sym in held,
                          "why": [f"{d['label']} at the {d['percentile']}th percentile {d['effect']} the score"
                                  for d in view["drivers"] if d.get("percentile") is not None]})
    invested = sum(p["cost"] or 0 for p in picks) + sum(c["value"] for c in core)
    if snap.regime.get("available") and exposure < profile.max_exposure * 0.95:
        notes.append(f"The regime model reads {snap.regime['state']}; your profile would invest about "
                     f"{exposure:.0%} of a swing budget now and keep the rest in cash.")
    if any(p["already_held"] for p in picks):
        notes.append("Some picks are stocks you already hold; adding them raises your concentration.")
    if unknown:
        notes.append(f"Not recognised as sectors: {', '.join(unknown)}. Known: {', '.join(known_sectors())}.")
    return {"amount": round(amount, 2), "horizon": horizon, "as_of": str(snap.as_of.date()),
            "profile": profile.as_dict(), "regime": {k: v for k, v in snap.regime.items() if k != "history"},
            "sectors_requested": wanted, "core": core, "picks": picks, "excluded": excluded,
            "invested": round(invested, 2), "cash_left": round(amount - invested, 2),
            "suggested_exposure": round(exposure, 4), "notes": notes, "model": snap.card, "disclaimer": DISCLAIMER}


# --------------------------------------------------------------------------- starting and stopping

def preview_start(db: Session, user: User, amount: float) -> dict:
    """The first basket Autopilot would buy for ``amount`` (nothing is placed)."""
    if not math.isfinite(amount) or amount < MIN_BUDGET:
        raise paper.OrderRejected(f"Autopilot needs at least ₹{MIN_BUDGET:,}.")
    acct = paper.account(db, user)
    free = float(acct.cash) - paper.margin_used(paper._positions(db, user))
    if amount > free:
        raise paper.OrderRejected(f"Only ₹{max(free, 0):,.2f} is available in the paper account.")
    row = settings_for(db, user)
    if row.sleeve:
        raise paper.OrderRejected("Autopilot is already running. Manage it on the Autopilot page.")
    tgt = target(db, user, base_value=amount)
    feed = feed_for(db, user)
    basket = []
    for p in tgt["positions"]:
        price, source = _price(p["symbol"], feed, p["reference_price"])
        qty = int(p["value"] // price) if price else 0
        if qty <= 0:
            continue
        basket.append({"symbol": p["symbol"], "name": p["name"], "sector": p["sector"], "ltp": price,
                       "quantity": qty, "cost": round(qty * price, 2), "price_source": source,
                       "rank": p["rank"], "weight": p["weight"], "stop": p["stop"], "target": p["target"]})
    if not basket:
        raise paper.OrderRejected("No model pick is affordable at that amount.")
    invested = sum(b["cost"] for b in basket)
    return {
        "amount": round(amount, 2), "invested": round(invested, 2), "uninvested": round(amount - invested, 2),
        "basket": basket, "notes": tgt["notes"], "regime": tgt["regime"], "profile": tgt["profile"],
        "method": (f"The swing models' top picks for your {tgt['profile']['name']} profile, sized by forecast "
                   f"volatility and scaled to the market regime. Once confirmed, Autopilot rebalances this paper "
                   f"sleeve every {row.cadence_sessions} sessions on its own; pause it on the Autopilot page."),
        "disclaimer": DISCLAIMER,
    }


def start(db: Session, user: User, basket: list[dict], amount: float | None = None) -> list:
    """Confirm a previewed basket: fund the sleeve, buy it, switch Autopilot on."""
    row = settings_for(db, user)
    if row.sleeve:
        raise paper.OrderRejected("Autopilot is already running. Manage it on the Autopilot page.")
    feed = feed_for(db, user)
    budget = float(amount) if amount else None
    placed, sleeve = [], {}
    spent = 0.0
    for leg in basket[:15]:
        try:
            order = paper.place_order(db, user, instrument="equity", symbol=str(leg["symbol"]), side="buy",
                                      quantity=int(leg["quantity"]), product="delivery", tag=TAG, feed=feed)
        except paper.OrderRejected:
            continue
        placed.append(order)
        if order.status == "filled":
            sleeve[order.symbol] = sleeve.get(order.symbol, 0) + int(order.quantity)
            spent += float(order.fill_price) * int(order.quantity)
    if not sleeve:
        return placed
    budget = max(budget or spent, spent)
    row.budget = round(budget, 2)
    row.sleeve = sleeve
    row.sleeve_cash = round(budget - spent, 2)
    row.enabled = True
    run_day = signals.snapshot().as_of.date()
    row.last_run_on = run_day
    db.add(AutopilotRun(user_id=user.id, run_on=run_day, mode="manual", status="done", regime=None,
                        target=[{"symbol": s, "quantity": q} for s, q in sleeve.items()],
                        orders=[paper.order_dict(o) for o in placed],
                        notes=["Autopilot started from a confirmed basket."], sleeve_value=round(budget, 2)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.commit()
    return placed


def stop(db: Session, user: User, sell: bool = True) -> dict:
    """Pause Autopilot; with ``sell``, exit the sleeve's paper holdings and close its ledger."""
    row = settings_for(db, user)
    row.enabled = False
    orders = []
    if sell and row.sleeve:
        feed = feed_for(db, user)
        held = _held_quantities(db, user)
        cash = float(row.sleeve_cash or 0)
        for sym, qty in list(row.sleeve.items()):
            qty = min(int(qty), held.get(sym, 0))
            if qty <= 0:
                continue
            try:
                order = paper.place_order(db, user, instrument="equity", symbol=sym, side="sell", quantity=qty,
                                          product="delivery", tag=TAG, feed=feed)
            except paper.OrderRejected:
                continue
            if order.status == "filled":
                cash += float(order.fill_price) * int(order.quantity)
            orders.append(paper.order_dict(order))
        row.sleeve = {}
        row.sleeve_cash = None
        row.last_run_on = None
    db.commit()
    return {"settings": settings_dict(row), "orders": orders}
