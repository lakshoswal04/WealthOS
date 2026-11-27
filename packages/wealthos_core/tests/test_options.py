"""Option pricing and the modelled open-interest surface."""

from __future__ import annotations

import math
from datetime import date

import pytest

from wealthos_core.options import (
    RISK_FREE_RATE, bs_greeks, bs_price, expiries, max_pain, payoff_at_expiry, smile_iv,
    strike_grid, time_to_expiry,
)

SPOT, T, VOL = 25_900.0, 7 / 365, 0.15


@pytest.mark.parametrize("strike", [24_500, 25_500, 25_900, 26_300, 27_000])
def test_put_call_parity_holds_at_every_strike(strike):
    # C - P = S - K e^{-rT}, exactly, for European options.
    call = bs_price(SPOT, strike, T, VOL, "call")
    put = bs_price(SPOT, strike, T, VOL, "put")
    assert call - put == pytest.approx(SPOT - strike * math.exp(-RISK_FREE_RATE * T), abs=1e-6)


def test_a_known_value():
    # Hull's textbook case: S=42, K=40, r=10%, sigma=20%, T=0.5 -> C=4.76, P=0.81.
    assert bs_price(42, 40, 0.5, 0.2, "call", r=0.10) == pytest.approx(4.76, abs=0.01)
    assert bs_price(42, 40, 0.5, 0.2, "put", r=0.10) == pytest.approx(0.81, abs=0.01)


def test_greeks_have_the_right_signs():
    call = bs_greeks(SPOT, 26_000, T, VOL, "call")
    put = bs_greeks(SPOT, 26_000, T, VOL, "put")
    assert 0 < call["delta"] < 1 and -1 < put["delta"] < 0
    assert call["delta"] - put["delta"] == pytest.approx(1.0, abs=1e-9)
    assert call["gamma"] > 0 and call["gamma"] == pytest.approx(put["gamma"])
    assert call["vega"] > 0 and call["theta"] < 0


def test_an_expired_option_is_worth_its_intrinsic_value():
    assert bs_price(26_000, 25_900, 0, VOL, "call") == 100
    assert bs_price(26_000, 25_900, 0, VOL, "put") == 0


def test_the_smile_charges_more_for_downside_strikes():
    atm = smile_iv(0.15, SPOT, SPOT)
    assert atm == pytest.approx(0.15)
    assert smile_iv(0.15, SPOT, SPOT * 0.95) > smile_iv(0.15, SPOT, SPOT * 1.05)


def test_strike_grid_is_centred_on_the_money():
    grid = strike_grid(25_912, 50, each_side=3)
    assert grid == [25_750, 25_800, 25_850, 25_900, 25_950, 26_000, 26_050]


def test_weekly_nifty_expiries_fall_on_tuesdays():
    thursday = date(2026, 11, 26)
    got = expiries("NIFTY", thursday, 3)
    assert got == [date(2026, 12, 1), date(2026, 12, 8), date(2026, 12, 15)]
    assert expiries("NIFTY", date(2026, 12, 1), 1) == [date(2026, 12, 1)]  # expiry day itself


def test_monthly_banknifty_expiries_are_the_last_tuesday():
    got = expiries("BANKNIFTY", date(2026, 11, 26), 2)
    assert got == [date(2026, 12, 29), date(2027, 1, 26)]


def test_an_expiring_option_keeps_time_value_until_the_close():
    t = time_to_expiry(date(2026, 12, 1), date(2026, 12, 1), minute_of_session=300)
    assert 0 < t < 1 / 365


def test_payoff_of_a_bull_call_spread_by_hand():
    legs = [{"option_type": "CE", "strike": 100, "premium": 5, "action": "buy"},
            {"option_type": "CE", "strike": 110, "premium": 2, "action": "sell"}]
    assert payoff_at_expiry(legs, 90) == pytest.approx(-3)     # both expire worthless: lose the debit
    assert payoff_at_expiry(legs, 105) == pytest.approx(2)     # 5 intrinsic less the 3 debit
    assert payoff_at_expiry(legs, 130) == pytest.approx(7)     # capped at width (10) less debit


def test_max_pain_by_hand():
    # 10 calls struck at 100 and 30 puts struck at 200.
    # Settle at 100: calls 0, puts 30*100 = 3000.
    # Settle at 150: calls 10*50 = 500, puts 30*50 = 1500 -> 2000.
    # Settle at 200: calls 10*100 = 1000, puts 0 -> 1000.   <- smallest
    assert max_pain([100, 150, 200], [10, 0, 0], [0, 0, 30]) == 200
    # Only puts at 150: settling at or above 150 costs nothing; the lowest such wins.
    assert max_pain([100, 150, 200], [0, 0, 0], [0, 50, 0]) == 150
