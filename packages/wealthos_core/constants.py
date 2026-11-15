"""Shared constants for all WealthOS financial calculations.

Every assumption that affects a reported number lives here so it can be cited
in the project report and changed in exactly one place.
"""

from __future__ import annotations

# Number of Indian equity trading days in a year. Used to annualise daily
# return and volatility figures.
TRADING_DAYS_PER_YEAR: int = 252

# Calendar periods, for snapshot series sampled at lower frequency.
MONTHS_PER_YEAR: int = 12
WEEKS_PER_YEAR: int = 52

PERIODS_PER_YEAR = {
    "daily": TRADING_DAYS_PER_YEAR,
    "weekly": WEEKS_PER_YEAR,
    "monthly": MONTHS_PER_YEAR,
    "quarterly": 4,
    "annual": 1,
}

# Default annual risk-free rate used by Sharpe/Sortino/alpha.
# Chosen as a round proxy for the Indian 10-year government security yield over
# the sample period. It is an assumption, not an observation: the report must
# state it, and every ratio is recomputed if it changes.
DEFAULT_RISK_FREE_RATE: float = 0.06

# Deterministic annual accrual applied to the "cash" asset class.
# LIQUIDBEES and similar liquid ETFs pin their NAV at a constant and return
# cash through dividends, so their *price* series shows zero return. Modelling
# cash at an explicit documented rate is more honest than reading a flat price
# series as a flat return.
CASH_ANNUAL_RETURN: float = 0.055

# Benchmark used for beta, alpha and relative performance.
BENCHMARK_SYMBOL: str = "NIFTY 50"

# Asset classes recognised across the platform.
ASSET_CLASSES = ("equity", "etf", "gold", "debt", "cash")

# Relative liquidity scores per asset class, 0 (illiquid) to 1 (immediate).
# Used by the Health Score liquidity component.
ASSET_CLASS_LIQUIDITY = {
    "cash": 1.00,
    "debt": 0.75,
    "etf": 0.85,
    "gold": 0.80,
    "equity": 0.70,
}
