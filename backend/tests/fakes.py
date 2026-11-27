"""Test doubles for the market-data providers.

Nothing here is reachable from the application: tests install these in
place of Yahoo and Upstox so the suite is deterministic and offline. The
shapes follow the providers' documented responses.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pandas as pd

from app.integrations.upstox.instruments import IST, master
from app.services import live_market_service as live

# --------------------------------------------------------------------------
# Yahoo: quotes and daily candles from the seeded test market
# --------------------------------------------------------------------------

PANEL_NAME = {"NIFTY": "NIFTY50"}


class FixtureMarket:
    """Delayed quotes derived from the deterministic prices `conftest` seeds."""

    name = "delayed"

    def __init__(self, panel: pd.DataFrame):
        self.panel = panel

    def _series(self, symbol: str) -> pd.Series | None:
        col = PANEL_NAME.get(symbol, symbol)
        if col not in self.panel.columns:
            return None
        s = self.panel[col].dropna()
        return s if len(s) >= 2 else None

    def fetch_quotes(self, symbols):
        out, now = {}, live.now_ist()
        for symbol in symbols:
            s = self._series(symbol)
            if s is None:
                continue
            ltp, prev = float(s.iloc[-1]), float(s.iloc[-2])
            out[symbol] = live.make_quote(symbol, ltp, prev, prev, max(ltp, prev), min(ltp, prev),
                                          100_000.0, "delayed", now)
        return out

    def fetch_candles(self, symbol, interval, range_, days):
        s = self._series(symbol)
        if s is None or interval != "1D":
            return None
        s = s.iloc[-max(days, 5):]
        return pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": 1000.0})


# --------------------------------------------------------------------------
# Upstox: an instrument master and a mock API
# --------------------------------------------------------------------------

NIFTY_EXPIRIES = (date(2026, 12, 1), date(2026, 12, 8))
NIFTY_STRIKES = list(range(25000, 27001, 50))
NIFTY_LOT = 65
SPOT = 25900.0


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=IST).timestamp() * 1000)


def install_master() -> None:
    records = [{"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE",
                "instrument_key": "NSE_EQ|INE002A01018"},
               {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "TCS",
                "instrument_key": "NSE_EQ|INE467B01029"}]
    n = 1000
    for exp in NIFTY_EXPIRIES:
        for k in NIFTY_STRIKES:
            for t in ("CE", "PE"):
                n += 1
                records.append({"segment": "NSE_FO", "instrument_type": t, "underlying_symbol": "NIFTY",
                                "instrument_key": f"NSE_FO|{n}", "expiry": _ms(exp), "strike_price": float(k),
                                "lot_size": NIFTY_LOT, "trading_symbol": f"NIFTY {k} {t} {exp:%d %b %y}".upper()})
    records.append({"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "RELIANCE",
                    "instrument_key": "NSE_FO|9001", "expiry": _ms(date(2026, 12, 29)), "strike_price": 0,
                    "lot_size": 500, "trading_symbol": "RELIANCE FUT 29 DEC 26"})
    master.load_records(records)
    master._day = datetime.now(IST).date()


def _premium(strike: float, kind: str) -> float:
    intrinsic = max(SPOT - strike, 0) if kind == "CE" else max(strike - SPOT, 0)
    return round(intrinsic + 120 * math.exp(-abs(SPOT - strike) / 400) + 0.5, 2)


def _chain_rows(expiry: str) -> list[dict]:
    exp = date.fromisoformat(expiry)
    rows = []
    for k in NIFTY_STRIKES:
        legs = {}
        for t, name in (("CE", "call_options"), ("PE", "put_options")):
            c = master.contract("NIFTY", exp, float(k), t)
            oi = 100_000 + (k - 25000) * (40 if t == "CE" else -30) + 300_000 * (k == (26000 if t == "CE" else 25500))
            legs[name] = {
                "instrument_key": c.instrument_key,
                "market_data": {"ltp": _premium(k, t), "close_price": _premium(k, t) * 1.05, "volume": 5000 + k % 700,
                                "oi": max(oi, 1000), "prev_oi": max(oi, 1000) - 2000, "bid_price": 0, "ask_price": 0},
                "option_greeks": {"vega": 10.0, "theta": -5.0, "gamma": 0.0005,
                                  "delta": 0.5 if t == "CE" else -0.5, "iv": 14.5, "pop": 50},
            }
        rows.append({"expiry": expiry, "strike_price": float(k), "underlying_key": "NSE_INDEX|Nifty 50",
                     "underlying_spot_price": SPOT, **legs})
    return rows


def _price_for_key(key: str) -> float:
    c = master.by_key.get(key)
    if c is not None and c.instrument_type in ("CE", "PE"):
        return _premium(c.strike, c.instrument_type)
    return {"NSE_EQ|INE002A01018": 1500.0, "NSE_INDEX|Nifty 50": SPOT, "NSE_FO|9001": 1510.0}.get(key, 100.0)


class FakeUpstox:
    """Routes for httpx.MockTransport. Records calls; can simulate an expired token."""

    GOOD_CODE = "good-code"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.expired_tokens: set[str] = set()
        self.holdings = [
            {"trading_symbol": "RELIANCE", "quantity": 5, "t1_quantity": 0, "average_price": 1000.0},
            {"trading_symbol": "NOTINUNIVERSE", "quantity": 3, "t1_quantity": 0, "average_price": 50.0},
        ]
        self.margin = 123456.0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _ok(self, data) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": data})

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = unquote(url.path)
        self.calls.append(f"{request.method} {path}")
        params = {k: v[0] for k, v in parse_qs(url.query).items()}

        if path == "/v2/login/authorization/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("code") != self.GOOD_CODE:
                return httpx.Response(400, json={"status": "error", "errors": [
                    {"error_code": "UDAPI100057", "message": "Invalid auth code"}]})
            return httpx.Response(200, json={"user_id": "AB1234", "user_name": "Test Trader",
                                             "access_token": "good-token", "exchanges": ["NSE", "NFO"],
                                             "products": ["D", "I"]})

        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token in self.expired_tokens:
            return httpx.Response(401, json={"status": "error", "errors": [
                {"error_code": "UDAPI100050", "message": "Invalid token used to access API"}]})

        if path == "/v2/option/chain":
            return self._ok(_chain_rows(params["expiry_date"]))
        if path == "/v2/market-quote/quotes":
            data = {}
            for key in params["instrument_key"].split(","):
                p = _price_for_key(key)
                data[f"X:{key}"] = {"instrument_token": key, "last_price": p, "net_change": round(p * 0.01, 2),
                                    "volume": 1000, "oi": 5000, "ohlc": {"open": p, "high": p, "low": p, "close": p}}
            return self._ok(data)
        if path == "/v2/charges/margin":
            return self._ok({"required_margin": self.margin, "final_margin": self.margin, "margins": []})
        if path.startswith("/v3/historical-candle/intraday/"):
            key = path.split("/")[4]
            p = _price_for_key(key)
            candles = [[f"2026-11-25T{9 + m // 60:02d}:{m % 60:02d}:00+05:30", p, p, p, p, 100,
                        50_000 + m * (300 if key.endswith(("1", "3", "5", "7", "9")) else -200)]
                       for m in range(15, 120, 15)]
            return self._ok({"candles": list(reversed(candles))})
        if path.startswith("/v3/historical-candle/"):
            return self._ok({"candles": []})
        if path == "/v2/portfolio/long-term-holdings":
            return self._ok(self.holdings)
        return httpx.Response(404, json={"status": "error", "errors": [{"error_code": "X", "message": path}]})


def connect_upstox(db, user, token: str = "good-token") -> None:
    """Give a user a live Upstox session, as a completed OAuth login would."""
    from app.core.secrets import encrypt_secret
    from app.models import BrokerCredential, LinkedAccount
    from app.models.enums import LinkedAccountStatus

    db.add(BrokerCredential(user_id=user.id, broker="upstox", api_key_encrypted=encrypt_secret("key-12345678"),
                            api_secret_encrypted=encrypt_secret("secret-123456"), api_key_hint="5678"))
    db.add(LinkedAccount(user_id=user.id, provider="upstox", account_reference="AB1234",
                         display_name="Upstox · Test", status=LinkedAccountStatus.ACTIVE,
                         access_token_encrypted=encrypt_secret(token),
                         token_expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc), is_simulated=False))
    db.commit()


def dump(obj) -> str:
    return json.dumps(obj, default=str)
