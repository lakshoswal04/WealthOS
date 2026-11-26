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

# Annualisation factor by sampling frequency. Every caller today works on
# daily series and uses TRADING_DAYS_PER_YEAR directly; this mapping exists so
# that a monthly or quarterly series is annualised with the same documented
# factors rather than an ad-hoc literal at the call site.
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
#
# SYMBOL is the primary key in the `assets` table and the column name in every
# price panel; NAME is for display only. They are not interchangeable. This
# constant previously read "NIFTY 50", which is the name, not the symbol: no
# such row exists, so any caller importing it would have silently received an
# empty benchmark series and a NaN beta rather than an error. Nothing imported
# it, which is the only reason that never surfaced. Keep the two apart.
BENCHMARK_SYMBOL: str = "NIFTY50"
BENCHMARK_NAME: str = "NIFTY 50"

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

# --------------------------------------------------------------------------
# Minimum data requirements
# --------------------------------------------------------------------------

# Hard floor: below this many overlapping daily observations a volatility,
# Sharpe or drawdown figure is refused outright rather than shown with a
# caveat. 60 trading days is roughly three months.
#
# The floor is a judgement about honesty, not a statistical theorem. The
# standard error of an estimated volatility is approximately sigma / sqrt(2n),
# so at n = 60 the estimate carries about 9% relative error — wide, but a
# real measurement. Below that the number moves more with the window than
# with the portfolio.
MIN_OBSERVATIONS_FOR_RISK: int = 60

# Soft threshold: at or above a full year the same estimate carries about 4.5%
# relative error, which is where the figure stops needing a caveat. Between
# the two the number is reported and labelled as provisional.
RELIABLE_OBSERVATIONS_FOR_RISK: int = TRADING_DAYS_PER_YEAR

# A holding is kept in the common risk window only if it has a price on at
# least this share of the dates in that window. Dropping to the intersection
# of all holdings' dates is the correct thing to do, but one recently listed
# asset would otherwise truncate the window for every other holding. 0.9
# admits a symbol missing the odd trading day while excluding one that simply
# did not exist for part of the period.
MIN_SYMBOL_COVERAGE: float = 0.9
