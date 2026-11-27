"""An authenticated Upstox API client.

One client per user access token. Errors are typed so callers can tell a
session that needs a fresh login from a provider that is merely busy.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger("wealthos.upstox")

BASE_URL = "https://api.upstox.com"
TIMEOUT = httpx.Timeout(8.0, connect=4.0)

# Tests install an httpx.MockTransport here; production leaves it None.
TRANSPORT: httpx.BaseTransport | None = None

TOKEN_ERROR_CODES = {"UDAPI100050", "UDAPI100016", "UDAPI100067"}


class UpstoxError(RuntimeError):
    """Upstox answered with an error."""

    def __init__(self, message: str, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class TokenInvalid(UpstoxError):
    """The access token is expired or revoked: the user must log in again."""


class RateLimited(UpstoxError):
    pass


class Unavailable(UpstoxError):
    """Upstox could not be reached or returned a server error."""


def _raise_for(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    code, message = None, f"Upstox returned HTTP {response.status_code}"
    try:
        body = response.json()
        errors = body.get("errors") or []
        if errors:
            code = errors[0].get("error_code") or errors[0].get("errorCode")
            message = errors[0].get("message") or message
    except ValueError:
        pass
    if response.status_code == 401 or code in TOKEN_ERROR_CODES:
        raise TokenInvalid("Your Upstox session has expired. Log in to Upstox again.", code, 401)
    if response.status_code == 429:
        raise RateLimited("Upstox is rate-limiting requests; try again in a moment.", code, 429)
    if response.status_code >= 500:
        raise Unavailable(f"Upstox is unavailable ({response.status_code}).", code, response.status_code)
    raise UpstoxError(message, code, response.status_code)


def http(**kwargs: Any) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, transport=TRANSPORT, **kwargs)


class UpstoxClient:
    def __init__(self, access_token: str):
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json: dict | None = None, retries: int = 1) -> Any:
        for attempt in range(retries + 1):
            try:
                with http(headers=self._headers) as client:
                    response = client.request(method, path, params=params, json=json)
            except httpx.HTTPError as exc:
                if attempt < retries:
                    time.sleep(0.4)
                    continue
                raise Unavailable(f"Upstox could not be reached ({type(exc).__name__}).") from exc
            if response.status_code == 429 and attempt < retries:
                time.sleep(1.0)
                continue
            _raise_for(response)
            body = response.json()
            if body.get("status") == "error":
                _raise_for(httpx.Response(400, json=body))
            return body.get("data")
        raise Unavailable("Upstox did not answer.")

    # ---- market data ----------------------------------------------------

    def option_chain(self, instrument_key: str, expiry: str) -> list[dict]:
        return self._request("GET", "/v2/option/chain",
                             params={"instrument_key": instrument_key, "expiry_date": expiry}) or []

    def quotes(self, instrument_keys: list[str]) -> dict[str, dict]:
        """Full quotes keyed by instrument key (Upstox keys its response by symbol)."""
        out: dict[str, dict] = {}
        for i in range(0, len(instrument_keys), 500):
            batch = instrument_keys[i:i + 500]
            data = self._request("GET", "/v2/market-quote/quotes",
                                 params={"instrument_key": ",".join(batch)}) or {}
            for item in data.values():
                key = item.get("instrument_token")
                if key:
                    out[key] = item
        return out

    def intraday_candles(self, instrument_key: str, unit: str, interval: int) -> list[list]:
        path = f"/v3/historical-candle/intraday/{quote(instrument_key, safe='')}/{unit}/{interval}"
        return (self._request("GET", path) or {}).get("candles", [])

    def historical_candles(self, instrument_key: str, unit: str, interval: int,
                           to_date: str, from_date: str) -> list[list]:
        path = (f"/v3/historical-candle/{quote(instrument_key, safe='')}/{unit}/{interval}"
                f"/{to_date}/{from_date}")
        return (self._request("GET", path) or {}).get("candles", [])

    def margin(self, instruments: list[dict]) -> dict:
        return self._request("POST", "/v2/charges/margin", json={"instruments": instruments[:20]}) or {}

    # ---- portfolio --------------------------------------------------------

    def holdings(self) -> list[dict]:
        return self._request("GET", "/v2/portfolio/long-term-holdings") or []
