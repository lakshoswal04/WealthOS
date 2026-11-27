"""Option mathematics: Black-Scholes, Greeks, payoffs and max pain.

Market data (premiums, open interest, IV) comes from the broker; this module
only computes. It prices a strategy's T+0 curve from the *real* implied
volatility the chain reports, builds payoff-at-expiry diagrams, and finds
max pain from real open interest. Pure: no I/O, no clock reads.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

__all__ = [
    "norm_cdf", "bs_price", "bs_greeks", "smile_iv", "strike_grid",
    "expiries", "time_to_expiry", "max_pain", "payoff_at_expiry", "UNDERLYINGS",
]

RISK_FREE_RATE = 0.065          # roughly the 91-day T-bill yield
SESSION_MINUTES = 375           # 09:15 to 15:30 IST

# Strike step, contract lot size and expiry weekday (0=Mon) per underlying.
# Lot sizes are exchange-set and revised; these are the 2025-26 values.
UNDERLYINGS: dict[str, dict] = {
    "NIFTY":      {"step": 50,  "lot": 75,  "weekday": 1, "weekly": True},
    "BANKNIFTY":  {"step": 100, "lot": 35,  "weekday": 1, "weekly": False},
    "FINNIFTY":   {"step": 50,  "lot": 65,  "weekday": 1, "weekly": False},
    "MIDCPNIFTY": {"step": 25,  "lot": 140, "weekday": 1, "weekly": False},
    "SENSEX":     {"step": 100, "lot": 20,  "weekday": 3, "weekly": True},
}


# --------------------------------------------------------------------------
# Black-Scholes
# --------------------------------------------------------------------------

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(spot: float, strike: float, t: float, r: float, sigma: float) -> tuple[float, float]:
    vol_t = sigma * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / vol_t
    return d1, d1 - vol_t


def bs_price(spot: float, strike: float, t: float, sigma: float, kind: str,
             r: float = RISK_FREE_RATE) -> float:
    """European option premium. ``kind`` is "call" or "put"."""
    if t <= 0 or sigma <= 0:
        intrinsic = spot - strike if kind == "call" else strike - spot
        return max(intrinsic, 0.0)
    d1, d2 = _d1_d2(spot, strike, t, r, sigma)
    discount = math.exp(-r * t)
    if kind == "call":
        return spot * norm_cdf(d1) - strike * discount * norm_cdf(d2)
    return strike * discount * norm_cdf(-d2) - spot * norm_cdf(-d1)


def bs_greeks(spot: float, strike: float, t: float, sigma: float, kind: str,
              r: float = RISK_FREE_RATE) -> dict[str, float]:
    """Delta, gamma, theta (per calendar day) and vega (per volatility point)."""
    if t <= 0 or sigma <= 0:
        itm = spot > strike if kind == "call" else spot < strike
        return {"delta": (1.0 if kind == "call" else -1.0) if itm else 0.0,
                "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1, d2 = _d1_d2(spot, strike, t, r, sigma)
    pdf = _norm_pdf(d1)
    discount = math.exp(-r * t)
    gamma = pdf / (spot * sigma * math.sqrt(t))
    vega = spot * pdf * math.sqrt(t) / 100.0
    common = -spot * pdf * sigma / (2.0 * math.sqrt(t))
    if kind == "call":
        delta = norm_cdf(d1)
        theta = common - r * strike * discount * norm_cdf(d2)
    else:
        delta = norm_cdf(d1) - 1.0
        theta = common + r * strike * discount * norm_cdf(-d2)
    return {"delta": delta, "gamma": gamma, "theta": theta / 365.0, "vega": vega}


def smile_iv(base_iv: float, spot: float, strike: float) -> float:
    """Implied volatility on a skewed smile around an at-the-money level.

    Index options trade a put skew: downside strikes carry more volatility
    than upside ones. ``base_iv`` is the at-the-money level, anchored on
    India VIX by the caller.
    """
    m = math.log(strike / spot)
    return max(base_iv * (1.0 - 1.4 * m + 9.0 * m * m), 0.05)


# --------------------------------------------------------------------------
# Strikes and expiries
# --------------------------------------------------------------------------

def strike_grid(spot: float, step: int, each_side: int = 20) -> list[int]:
    atm = int(round(spot / step) * step)
    return [atm + step * i for i in range(-each_side, each_side + 1)]


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def expiries(underlying: str, today: date, count: int = 4) -> list[date]:
    """The next ``count`` expiry dates, today included if it is one."""
    spec = UNDERLYINGS[underlying]
    weekday = spec["weekday"]
    out: list[date] = []
    if spec["weekly"]:
        d = today + timedelta(days=(weekday - today.weekday()) % 7)
        while len(out) < count:
            out.append(d)
            d += timedelta(days=7)
        return out
    year, month = today.year, today.month
    while len(out) < count:
        d = _last_weekday_of_month(year, month, weekday)
        if d >= today:
            out.append(d)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def time_to_expiry(today: date, expiry: date, minute_of_session: int) -> float:
    """Years to expiry, counting the rest of today's session.

    Never quite zero on expiry day before the close, so an expiring option
    keeps some time value until 15:30.
    """
    days = (expiry - today).days
    remaining_today = max(SESSION_MINUTES - minute_of_session, 1) / SESSION_MINUTES
    return max(days + remaining_today, 1 / SESSION_MINUTES) / 365.0


def max_pain(strikes: list[int], call_oi: list[int], put_oi: list[int]) -> int:
    """The settlement price that would cost option buyers the most.

    For each candidate settlement, total what every open contract would be
    worth to its holder; max pain is the candidate where that total is
    smallest.
    """
    best, best_payout = strikes[0], math.inf
    for settle in strikes:
        payout = sum(c * max(settle - k, 0) + p * max(k - settle, 0)
                     for k, c, p in zip(strikes, call_oi, put_oi))
        if payout < best_payout:
            best, best_payout = settle, payout
    return best


def payoff_at_expiry(legs: list[dict], spot: float) -> float:
    """P&L per unit of a multi-leg position if the underlying settles at ``spot``.

    Each leg: {"option_type": "CE"|"PE", "strike": float, "premium": float,
    "action": "buy"|"sell", "quantity": units (default 1)}.
    """
    total = 0.0
    for leg in legs:
        intrinsic = (max(spot - leg["strike"], 0.0) if leg["option_type"] == "CE"
                     else max(leg["strike"] - spot, 0.0))
        sign = 1.0 if leg["action"] == "buy" else -1.0
        total += sign * (intrinsic - leg["premium"]) * leg.get("quantity", 1)
    return total
