"""Paper trading against delayed and modelled prices.

Accounting model, kept deliberately simple and consistent:

* Cash moves on every fill: a buy pays ``price × quantity``, a sell
  receives it. That holds for stocks and for option premiums alike, so cash
  is always "what would be in the bank".
* Positions are net and signed. Stocks cannot go short; options can, and a
  short option blocks the margin Upstox quotes for it at the time of the
  fill (stored on the position) out of the cash available for new trades.
* Realised P&L is recorded when a position is reduced, from its average
  price, so the portfolio page can show it without replaying history.
* Options left open past expiry are settled at intrinsic value against the
  underlying's real close on expiry day, the way index options cash-settle.
* Every price is real: stocks from Upstox (live) or Yahoo (delayed); options
  only from the user's Upstox session, so option orders need it.

There is no broker. ``mode`` is always "paper", and the API says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.upstox.instruments import OPTION_UNDERLYINGS, master
from app.models import PaperAccount, PaperOrder, PaperPosition, User
from app.services import live_market_service as live
from app.services import options_service
from app.services.market_data import Feed, OptionsUnavailable, feed_for

MAX_ORDER_VALUE = 50_000_000    # a fat-finger guard, not a risk model


class OrderRejected(ValueError):
    """An order that cannot be accepted, with a reason fit to show the user."""


@dataclass
class Instrument:
    instrument: str                 # equity | option
    symbol: str
    underlying: str
    option_type: str | None = None
    strike: float | None = None
    expiry: date | None = None
    lot_size: int = 1


# --------------------------------------------------------------------------
# Instruments and prices
# --------------------------------------------------------------------------

def option_symbol(underlying: str, expiry: date, strike: float, option_type: str) -> str:
    return f"{underlying} {expiry.strftime('%d %b').upper()} {int(strike)} {option_type}"


def resolve(instrument: str, symbol: str, option_type: str | None = None,
            strike: float | None = None, expiry: str | date | None = None) -> Instrument:
    """Validate what the user asked to trade against the real instrument list."""
    symbol = (symbol or "").upper().strip()
    if instrument == "equity":
        info = live.instrument_info(symbol)
        if info is None or info["kind"] != "equity":
            raise OrderRejected(f"{symbol or 'That'} is not a tradable stock in the universe.")
        return Instrument("equity", symbol, symbol)

    if instrument == "option":
        if symbol not in OPTION_UNDERLYINGS:
            raise OrderRejected(f"Options trade on {', '.join(OPTION_UNDERLYINGS)}; not {symbol}.")
        if option_type not in {"CE", "PE"}:
            raise OrderRejected("Option type must be CE or PE.")
        try:
            listed = master.expiries_for(symbol, live.now_ist().date())
        except Exception as exc:
            raise OrderRejected(f"The instrument list is unavailable: {exc}") from exc
        if not listed:
            raise OrderRejected(f"No listed {symbol} expiries were found.")
        exp = expiry if isinstance(expiry, date) else (date.fromisoformat(expiry) if expiry else listed[0])
        if exp not in listed:
            raise OrderRejected(f"{exp} is not a listed {symbol} expiry.")
        if strike is None:
            raise OrderRejected("An option order needs a strike.")
        contract = master.contract(symbol, exp, float(strike), option_type)
        if contract is None:
            raise OrderRejected(f"{symbol} {int(strike)} {option_type} is not listed for {exp}.")
        return Instrument("option", option_symbol(symbol, exp, strike, option_type), symbol,
                          option_type, float(strike), exp, contract.lot_size)

    raise OrderRejected("Instrument must be equity or option.")


def _from_row(row: PaperOrder | PaperPosition) -> Instrument:
    lot = 1
    if row.instrument == "option" and row.expiry is not None:
        try:
            c = master.contract(row.underlying, row.expiry, float(row.strike), row.option_type)
            lot = c.lot_size if c else 1
        except Exception:
            lot = 1
    return Instrument(row.instrument, row.symbol, row.underlying, row.option_type,
                      row.strike, row.expiry, lot)


def _expiry_close(underlying: str, day: date) -> float | None:
    """The underlying's real close on ``day`` (the settlement reference)."""
    hist = live.daily_store.history(underlying)
    if hist is not None:
        on_day = hist[hist.index.date == day]
        if not on_day.empty:
            return float(on_day["close"].iloc[-1])
    try:
        bars = live.get_candles(underlying, "1D", "1M")["bars"]
    except Exception:
        return None
    for b in bars:
        if datetime.fromtimestamp(b["time"], tz=live.IST).date() == day:
            return float(b["close"])
    return None


def price(inst: Instrument, feed: Feed) -> dict:
    """{ltp, prev_close, source} for an instrument right now, from real data."""
    if inst.instrument == "equity":
        try:
            q = live.require_quote(inst.symbol, feed)
        except live.MarketDataUnavailable as exc:
            raise OrderRejected(str(exc)) from exc
        return {"ltp": q.ltp, "prev_close": q.prev_close, "source": q.source}
    if inst.expiry is not None and inst.expiry < live.now_ist().date():
        return {"ltp": None, "prev_close": None, "source": "expired", "expired": True}
    try:
        p = options_service.option_quote(feed, inst.underlying, str(inst.expiry), inst.strike,
                                         inst.option_type)
    except OptionsUnavailable as exc:
        raise OrderRejected(str(exc)) from exc
    except ValueError as exc:
        raise OrderRejected(str(exc)) from exc
    return {"ltp": p["ltp"], "prev_close": p["prev_close"], "source": "live", "expired": False,
            "instrument_key": p["instrument_key"]}


# --------------------------------------------------------------------------
# Account
# --------------------------------------------------------------------------

def account(db: Session, user: User) -> PaperAccount:
    acct = db.scalar(select(PaperAccount).where(PaperAccount.user_id == user.id))
    if acct is None:
        start = settings.paper_starting_cash
        acct = PaperAccount(user_id=user.id, cash=start, starting_cash=start, realized_pnl=0)
        db.add(acct)
        db.commit()
        db.refresh(acct)
    return acct


def _positions(db: Session, user: User) -> list[PaperPosition]:
    return list(db.scalars(
        select(PaperPosition).where(PaperPosition.user_id == user.id).order_by(PaperPosition.id)
    ))


def margin_used(positions: list[PaperPosition]) -> float:
    """Margin blocked by open short options, as Upstox quoted it at each fill."""
    return round(sum(p.margin_blocked or 0.0 for p in positions if p.quantity < 0), 2)


def reset(db: Session, user: User) -> PaperAccount:
    for model in (PaperOrder, PaperPosition):
        for row in db.scalars(select(model).where(model.user_id == user.id)):
            db.delete(row)
    acct = account(db, user)
    acct.cash = acct.starting_cash
    acct.realized_pnl = 0
    db.commit()
    return acct


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------

def place_order(db: Session, user: User, *, instrument: str, symbol: str, side: str,
                quantity: int | None = None, lots: int | None = None,
                order_type: str = "market", limit_price: float | None = None,
                product: str | None = None, option_type: str | None = None,
                strike: float | None = None, expiry: str | None = None,
                tag: str = "manual", feed: Feed | None = None) -> PaperOrder:
    """Validate, record and (if marketable) fill an order.

    A rejected order is still recorded, with its reason, so the order book
    shows what was attempted.
    """
    if side not in {"buy", "sell"}:
        raise OrderRejected("Side must be buy or sell.")
    if order_type not in {"market", "limit"}:
        raise OrderRejected("Order type must be market or limit.")
    inst = resolve(instrument, symbol, option_type, strike, expiry)

    if inst.instrument == "option":
        if lots is not None:
            quantity = lots * inst.lot_size
        if not quantity or quantity % inst.lot_size:
            raise OrderRejected(f"{inst.underlying} options trade in lots of {inst.lot_size}.")
        product = "nrml"
    else:
        product = product or "delivery"
        if product not in {"delivery", "intraday"}:
            raise OrderRejected("Stock orders are delivery or intraday.")
    if not quantity or quantity <= 0:
        raise OrderRejected("Quantity must be a positive whole number.")
    if order_type == "limit" and (limit_price is None or limit_price <= 0):
        raise OrderRejected("A limit order needs a positive limit price.")

    feed = feed or feed_for(db, user)
    quote = price(inst, feed)
    if quote.get("expired"):
        raise OrderRejected(f"{inst.symbol} has expired.")
    if quote["ltp"] * quantity > MAX_ORDER_VALUE:
        raise OrderRejected("Order value exceeds the ₹5 crore per-order limit.")

    order = PaperOrder(
        user_id=user.id, instrument=inst.instrument, symbol=inst.symbol,
        underlying=inst.underlying, option_type=inst.option_type, strike=inst.strike,
        expiry=inst.expiry, side=side, quantity=int(quantity), order_type=order_type,
        limit_price=limit_price, product=product, status="open", tag=tag[:48],
        price_source=quote["source"],
    )
    db.add(order)
    db.flush()

    fill_at = _marketable_price(order, quote["ltp"])
    if fill_at is not None:
        try:
            _fill(db, user, order, inst, fill_at, feed)
        except OrderRejected as exc:
            order.status, order.reject_reason = "rejected", str(exc)
    db.commit()
    db.refresh(order)
    return order


def _marketable_price(order: PaperOrder, ltp: float) -> float | None:
    if order.order_type == "market":
        return ltp
    if order.side == "buy" and ltp <= order.limit_price:
        return ltp
    if order.side == "sell" and ltp >= order.limit_price:
        return ltp
    return None


def _fill(db: Session, user: User, order: PaperOrder, inst: Instrument, fill: float,
          feed: Feed | None = None) -> None:
    acct = account(db, user)
    positions = _positions(db, user)
    pos = next((p for p in positions if p.symbol == order.symbol and p.product == order.product), None)
    held = pos.quantity if pos else 0
    delta = order.quantity if order.side == "buy" else -order.quantity
    new_qty = held + delta
    value = fill * order.quantity

    if inst.instrument == "equity" and new_qty < 0:
        raise OrderRejected(
            f"You hold {held} {order.symbol} ({order.product}); short selling stocks is not supported."
        )

    available = float(acct.cash) - margin_used(positions)
    if order.side == "buy":
        if value > available + 1e-6:
            raise OrderRejected(
                f"Insufficient funds: needs ₹{value:,.2f}, ₹{max(available, 0):,.2f} available."
            )
    new_margin = 0.0
    if order.side == "sell" and inst.instrument == "option" and new_qty < 0:
        opening_short = min(order.quantity, abs(new_qty))
        if order.tag != "expiry":
            contract = master.contract(inst.underlying, inst.expiry, float(inst.strike), inst.option_type)
            if feed is None or contract is None:
                raise OrderRejected("Writing options needs a live Upstox session to quote the margin.")
            try:
                new_margin = feed.margin(contract.instrument_key, opening_short, "SELL", "D")
            except OptionsUnavailable as exc:
                raise OrderRejected(str(exc)) from exc
            except Exception as exc:
                raise OrderRejected(f"Upstox could not quote the margin: {exc}") from exc
            if new_margin > available + value + 1e-6:
                raise OrderRejected(
                    f"Insufficient margin to write {opening_short} units: Upstox quotes ₹{new_margin:,.2f}."
                )

    realized = 0.0
    if pos is None:
        pos = PaperPosition(user_id=user.id, instrument=inst.instrument, symbol=inst.symbol,
                            underlying=inst.underlying, option_type=inst.option_type,
                            strike=inst.strike, expiry=inst.expiry, product=order.product,
                            quantity=0, avg_price=0.0, realized_pnl=0.0, tag=order.tag)
        db.add(pos)
    if held == 0 or (held > 0) == (delta > 0):
        pos.avg_price = (abs(held) * pos.avg_price + order.quantity * fill) / (abs(held) + order.quantity)
    else:
        closing = min(abs(held), abs(delta))
        realized = closing * (fill - pos.avg_price) * (1 if held > 0 else -1)
        if held < 0 and pos.margin_blocked:
            # Covering part of a short releases that share of its margin.
            pos.margin_blocked = pos.margin_blocked * (1 - closing / abs(held))
        if abs(delta) > abs(held):          # flipped through zero
            pos.avg_price = fill
    pos.margin_blocked = (pos.margin_blocked or 0.0) + new_margin
    pos.quantity = new_qty
    pos.realized_pnl = (pos.realized_pnl or 0.0) + realized

    acct.cash = float(acct.cash) + (-value if order.side == "buy" else value)
    acct.realized_pnl = float(acct.realized_pnl) + realized

    order.status = "filled"
    order.fill_price = round(fill, 2)
    order.filled_at = datetime.now(timezone.utc)
    if new_qty == 0:
        db.delete(pos)


def cancel_order(db: Session, user: User, order_id: int) -> PaperOrder | None:
    order = db.scalar(select(PaperOrder).where(PaperOrder.id == order_id,
                                               PaperOrder.user_id == user.id))
    if order is None:
        return None
    if order.status != "open":
        raise OrderRejected(f"Only open orders can be cancelled; this one is {order.status}.")
    order.status = "cancelled"
    db.commit()
    db.refresh(order)
    return order


def process_open_orders(db: Session, user: User, feed: Feed | None = None) -> int:
    """Fill any resting limit order the price has now reached."""
    filled = 0
    open_orders = list(db.scalars(select(PaperOrder).where(PaperOrder.user_id == user.id,
                                                           PaperOrder.status == "open")))
    if not open_orders:
        return 0
    feed = feed or feed_for(db, user)
    for order in open_orders:
        inst = _from_row(order)
        try:
            quote = price(inst, feed)
        except OrderRejected:
            continue
        if quote.get("expired"):
            order.status, order.reject_reason = "cancelled", "Expired before it filled."
            continue
        at = _marketable_price(order, quote["ltp"])
        if at is None:
            continue
        # A resting limit fills at its limit, not at a better price it never saw.
        try:
            _fill(db, user, order, inst, order.limit_price, feed)
            filled += 1
        except OrderRejected as exc:
            order.status, order.reject_reason = "rejected", str(exc)
    db.commit()
    return filled


def settle_expired(db: Session, user: User) -> int:
    """Cash-settle option positions at the underlying's real expiry-day close.

    A position whose settlement close is not yet available is left open and
    retried on the next read, rather than settled against a guess.
    """
    today = live.now_ist().date()
    settled = 0
    for pos in _positions(db, user):
        if pos.instrument != "option" or pos.expiry is None or pos.expiry >= today:
            continue
        spot = _expiry_close(pos.underlying, pos.expiry)
        if spot is None:
            continue
        intrinsic = max(spot - pos.strike, 0) if pos.option_type == "CE" else max(pos.strike - spot, 0)
        order = PaperOrder(
            user_id=user.id, instrument="option", symbol=pos.symbol, underlying=pos.underlying,
            option_type=pos.option_type, strike=pos.strike, expiry=pos.expiry,
            side="sell" if pos.quantity > 0 else "buy", quantity=abs(pos.quantity),
            order_type="market", product=pos.product, status="open", tag="expiry",
            price_source="settlement",
        )
        db.add(order)
        db.flush()
        _fill(db, user, order, _from_row(pos), round(intrinsic, 2))
        settled += 1
    db.commit()
    return settled


# --------------------------------------------------------------------------
# Portfolio view
# --------------------------------------------------------------------------

def _sparkline(symbol: str, points: int = 30) -> list[float]:
    hist = live.daily_store.history(symbol)
    if hist is None:
        return []
    return [round(float(v), 2) for v in hist["close"].iloc[-points:]]


def _tag_label(tag: str) -> str:
    if tag.startswith("strategy:"):
        return "Strategy"
    return {"autopilot": "Autopilot", "ai": "AI", "manual": "Manual", "expiry": "Expiry"}.get(tag, tag)


def portfolio(db: Session, user: User, feed: Feed | None = None) -> dict:
    feed = feed or feed_for(db, user)
    process_open_orders(db, user, feed)
    settle_expired(db, user)
    acct = account(db, user)
    positions = _positions(db, user)

    session = live.last_session_date()
    holdings, open_positions = [], []
    holdings_value = holdings_invested = day_pnl = prev_value = 0.0
    positions_mtm = positions_pnl = 0.0
    unpriced: list[dict] = []

    for p in positions:
        inst = _from_row(p)
        try:
            quote = price(inst, feed)
        except OrderRejected as exc:
            quote = {"ltp": None, "prev_close": None, "source": "unavailable", "reason": str(exc)}
        if quote.get("ltp") is None:
            # No real price: carry the position at cost as book value and say
            # so, rather than invent a mark.
            reason = quote.get("reason") or "Awaiting the expiry-day settlement price."
            unpriced.append({"symbol": p.symbol, "reason": reason})
            book = p.avg_price * p.quantity
            row = {
                "id": p.id, "symbol": p.symbol, "underlying": p.underlying,
                "instrument": p.instrument, "product": p.product, "option_type": p.option_type,
                "strike": p.strike, "expiry": str(p.expiry) if p.expiry else None,
                "quantity": p.quantity, "avg_price": round(p.avg_price, 2), "ltp": None,
                "day_change_pct": None, "current_value": round(book, 2),
                "invested": round(book, 2), "pnl": None, "day_pnl": 0.0, "pnl_pct": None,
                "realized_pnl": round(p.realized_pnl or 0.0, 2), "tag": p.tag,
                "tag_label": _tag_label(p.tag), "price_source": "unavailable", "price_note": reason,
                "lot_size": inst.lot_size,
            }
            if p.instrument == "equity" and p.product == "delivery":
                info = live.instrument_info(p.symbol) or {}
                row["name"], row["sparkline"] = info.get("name", p.symbol), _sparkline(p.symbol)
                holdings.append(row)
                holdings_value += book
                holdings_invested += book
            else:
                open_positions.append(row)
                positions_mtm += book
            continue
        ltp, prev = quote["ltp"], quote["prev_close"]
        value = ltp * p.quantity
        pnl = (ltp - p.avg_price) * p.quantity
        # A position opened today did not exist at yesterday's close: its
        # day's P&L runs from the fill, not from the instrument's prior close.
        opened_today = p.created_at is not None and p.created_at.astimezone(live.IST).date() >= session
        baseline = p.avg_price if opened_today else prev
        today = (ltp - baseline) * p.quantity
        day_pnl += today
        prev_value += baseline * p.quantity
        row = {
            "id": p.id, "symbol": p.symbol, "underlying": p.underlying,
            "instrument": p.instrument, "product": p.product,
            "option_type": p.option_type, "strike": p.strike,
            "expiry": str(p.expiry) if p.expiry else None,
            "quantity": p.quantity, "avg_price": round(p.avg_price, 2), "ltp": ltp,
            "day_change_pct": round((ltp / prev - 1) * 100, 2) if prev else 0.0,
            "current_value": round(value, 2), "invested": round(p.avg_price * p.quantity, 2),
            "pnl": round(pnl, 2),
            "day_pnl": round(today, 2),
            "pnl_pct": round((ltp / p.avg_price - 1) * 100 * (1 if p.quantity > 0 else -1), 2)
            if p.avg_price else 0.0,
            "realized_pnl": round(p.realized_pnl or 0.0, 2),
            "tag": p.tag, "tag_label": _tag_label(p.tag), "price_source": quote["source"],
            "lot_size": inst.lot_size,
        }
        if p.instrument == "equity" and p.product == "delivery":
            info = live.instrument_info(p.symbol) or {}
            row["name"] = info.get("name", p.symbol)
            row["sparkline"] = _sparkline(p.symbol)
            holdings.append(row)
            holdings_value += value
            holdings_invested += p.avg_price * p.quantity
        else:
            open_positions.append(row)
            positions_mtm += value
            positions_pnl += pnl

    margin = margin_used(positions)
    cash = float(acct.cash)
    total = cash + holdings_value + positions_mtm
    start = float(acct.starting_cash)

    since = datetime.now(timezone.utc) - timedelta(days=7)
    recent = db.scalars(select(PaperOrder).where(
        PaperOrder.user_id == user.id, PaperOrder.status == "filled",
        PaperOrder.filled_at >= since))
    activity: dict[str, int] = {}
    for o in recent:
        key = o.filled_at.astimezone(live.IST).date().isoformat()
        activity[key] = activity.get(key, 0) + 1
    today = live.now_ist().date()
    weekly = [{"date": str(today - timedelta(days=i)),
               "weekday": (today - timedelta(days=i)).strftime("%a").upper(),
               "orders": activity.get(str(today - timedelta(days=i)), 0)}
              for i in range(6, -1, -1)]

    return {
        "mode": "paper",
        "cash": round(cash, 2),
        "margin_used": margin,
        "available": round(cash - margin, 2),
        "starting_cash": start,
        "total_value": round(total, 2),
        "total_return": round(total - start, 2),
        "total_return_pct": round((total / start - 1) * 100, 2) if start else 0.0,
        "realized_pnl": round(float(acct.realized_pnl), 2),
        "holdings_value": round(holdings_value, 2),
        "holdings_invested": round(holdings_invested, 2),
        "holdings_pnl": round(holdings_value - holdings_invested, 2),
        "holdings_pnl_pct": round((holdings_value / holdings_invested - 1) * 100, 2)
        if holdings_invested else 0.0,
        "positions_pnl": round(positions_pnl, 2),
        "day_change": round(day_pnl, 2),
        "day_change_pct": round(day_pnl / abs(prev_value) * 100, 2) if prev_value else 0.0,
        "holdings": sorted(holdings, key=lambda h: h["current_value"], reverse=True),
        "positions": open_positions,
        "weekly_activity": weekly,
        "unpriced": unpriced,
        "options_feed": {"connected": feed.connected, "reason": feed.reason},
        "as_of": live.now_ist().isoformat(timespec="seconds"),
    }


def orders(db: Session, user: User, limit: int = 200) -> list[dict]:
    rows = db.scalars(select(PaperOrder).where(PaperOrder.user_id == user.id)
                      .order_by(PaperOrder.id.desc()).limit(limit))
    return [order_dict(o) for o in rows]


def order_dict(o: PaperOrder) -> dict:
    return {
        "id": o.id, "symbol": o.symbol, "instrument": o.instrument, "underlying": o.underlying,
        "option_type": o.option_type, "strike": o.strike,
        "expiry": str(o.expiry) if o.expiry else None, "side": o.side, "quantity": o.quantity,
        "order_type": o.order_type, "limit_price": o.limit_price, "product": o.product,
        "status": o.status, "fill_price": o.fill_price, "reject_reason": o.reject_reason,
        "tag": o.tag, "tag_label": _tag_label(o.tag), "price_source": o.price_source,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
    }


# --------------------------------------------------------------------------
# Autopilot
# --------------------------------------------------------------------------

def autopilot_preview(db: Session, user: User, amount: float) -> dict:
    """The first basket Autopilot would buy: the swing models' picks for this user.

    Nothing is placed; see ``autopilot_service`` for the engine.
    """
    from app.services import autopilot_service

    return autopilot_service.preview_start(db, user, amount)


def autopilot_execute(db: Session, user: User, basket: list[dict], amount: float | None = None) -> list[PaperOrder]:
    """Confirm the basket: Autopilot buys it and then manages it every few sessions."""
    from app.services import autopilot_service

    return autopilot_service.start(db, user, basket, amount)
