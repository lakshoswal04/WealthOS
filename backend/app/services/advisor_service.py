"""Swing plans: from model signals to a sized, risk-profiled paper basket.

The plan is the swing model stack applied to one user's money:

1. their risk profile (``User.risk_tolerance``) sets basket size, per-stock
   cap, volatility target, stop and target distances, and how far exposure
   falls in a stressed market;
2. the regime model's filtered probabilities scale how much is invested;
3. the ensemble's top-ranked names are sized by inverse forecast volatility
   and scaled to the volatility target (``allocation.size_basket``, the same
   function the stage-19 backtest uses);
4. quantities are whole shares at the live (or delayed) price.

Nothing is placed until the user confirms; ``execute`` then places paper
delivery orders tagged ``model:swing``.
"""

from __future__ import annotations

import math

import numpy as np
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import live_market_service as live
from app.services import paper_trading_service as paper
from app.services import signals_service as signals
from app.services.market_data import feed_for
from wealthos_core import swing_features as sf
from wealthos_core.allocation import profile_for, size_basket

MIN_AMOUNT = 10_000
MAX_LEGS = 15
TAG = "model:swing"


def _tolerance(user: User) -> str | None:
    rt = getattr(user, "risk_tolerance", None)
    return getattr(rt, "value", rt)


def swing_plan(db: Session, user: User, amount: float) -> dict:
    if not math.isfinite(amount) or amount < MIN_AMOUNT:
        raise paper.OrderRejected(f"A swing plan needs at least ₹{MIN_AMOUNT:,}.")
    acct = paper.account(db, user)
    available = float(acct.cash) - paper.margin_used(paper._positions(db, user))
    if amount > available:
        raise paper.OrderRejected(f"Only ₹{max(available, 0):,.2f} is available in the paper account.")

    snap = signals.snapshot()
    profile = profile_for(_tolerance(user))
    exposure = signals.profile_exposure(snap, profile)
    top = snap.table.head(profile.max_names)
    names = list(top.index)
    returns = np.log(snap.wide.close[names].ffill(limit=5)).diff().iloc[-126:]
    weights, scale, port_vol = size_basket(top["vol_annual"], returns, profile)

    feed = feed_for(db, user)
    investable = amount * exposure
    positions, invested = [], 0.0
    universe = len(snap.table)
    for sym in names:
        w = float(weights.get(sym, 0.0))
        if w <= 0:
            continue
        quote = live.get_quote(sym, feed)
        price = float(quote.ltp) if quote is not None else float(top.loc[sym, "last_close"])
        qty = int((investable * w) // price) if price > 0 else 0
        view = signals.row_view(sym, top.loc[sym], profile, universe)
        vol10 = view["vol_10d"]
        positions.append({
            **{k: view[k] for k in ("symbol", "name", "sector", "rank", "of", "score", "range_10d",
                                    "vol_annual", "drivers")},
            "weight": round(w, 4),
            "price": round(price, 2),
            "price_source": quote.source if quote is not None else "last close",
            "quantity": qty,
            "cost": round(qty * price, 2),
            "stop": round(price * (1 - profile.stop_multiple * vol10), 2) if vol10 else None,
            "target": round(price * (1 + profile.target_multiple * vol10), 2) if vol10 else None,
        })
        invested += qty * price

    regime = snap.regime
    notes = [
        f"Your profile is {profile.name}: up to {profile.max_names} names, at most "
        f"{profile.max_weight:.0%} in one stock, aiming for about {profile.vol_target:.0%} annual volatility.",
    ]
    if regime.get("available"):
        p = regime["probabilities"]
        notes.append(f"The market regime reads {regime['state']} (calm {p['calm']:.0%}, normal {p['normal']:.0%}, "
                     f"stress {p['stress']:.0%}), so the plan invests {exposure:.0%} of the amount.")
    if scale < 0.999:
        notes.append(f"The basket's forecast volatility ({port_vol:.0%}) is above your target, "
                     f"so position sizes are scaled to {scale:.0%}.")
    notes.append(f"Hold about {sf.HORIZON} sessions; stops and targets are {profile.stop_multiple} and "
                 f"{profile.target_multiple} times each stock's 10-session forecast volatility.")
    if not snap.card.get("recommended"):
        notes.append("The model did not pass its deployment gate out of sample; treat this as a research "
                     "experiment.")
    return {
        "as_of": str(snap.as_of.date()),
        "amount": round(amount, 2),
        "profile": profile.as_dict(),
        "regime": {k: v for k, v in regime.items() if k != "history"},
        "exposure": round(exposure, 4),
        "vol_scale": round(scale, 4),
        "forecast_portfolio_vol": round(port_vol, 4),
        "invested": round(invested, 2),
        "cash_reserve": round(amount - invested, 2),
        "positions": positions,
        "notes": notes,
        "model": snap.card,
        "disclaimer": signals.DISCLAIMER,
    }


def execute(db: Session, user: User, positions: list[dict]) -> list:
    """Place the confirmed legs as paper delivery buys. Rejected legs are skipped."""
    placed = []
    feed = feed_for(db, user)
    for leg in positions[:MAX_LEGS]:
        qty = int(leg.get("quantity") or 0)
        if qty <= 0:
            continue
        try:
            placed.append(paper.place_order(db, user, instrument="equity", symbol=str(leg["symbol"]),
                                            side="buy", quantity=qty, product="delivery", tag=TAG, feed=feed))
        except paper.OrderRejected:
            continue
    return placed
