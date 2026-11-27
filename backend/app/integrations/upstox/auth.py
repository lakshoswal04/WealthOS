"""Upstox OAuth: the authorise URL, the code exchange, and token lifetime.

Each user registers their own Upstox developer app and enters its API key
and secret; the platform never sees their Upstox password. The access token
Upstox issues is valid until 03:30 IST the next day and cannot be refreshed,
so a daily login is unavoidable.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.integrations.upstox.client import UpstoxError, _raise_for, http

IST = ZoneInfo("Asia/Kolkata")
DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"


def authorize_url(api_key: str, redirect_uri: str, state: str) -> str:
    return DIALOG_URL + "?" + urlencode({
        "response_type": "code", "client_id": api_key, "redirect_uri": redirect_uri, "state": state,
    })


def exchange_code(code: str, api_key: str, api_secret: str, redirect_uri: str) -> dict:
    """Trade the one-time code for an access token."""
    with http() as client:
        try:
            response = client.post(
                "/v2/login/authorization/token",
                data={"code": code, "client_id": api_key, "client_secret": api_secret,
                      "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
                headers={"Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
        except Exception as exc:  # httpx errors
            raise UpstoxError(f"Upstox could not be reached ({type(exc).__name__}).") from exc
    _raise_for(response)
    body = response.json()
    if not body.get("access_token"):
        raise UpstoxError("Upstox did not return an access token.")
    return body


def token_expiry(issued: datetime | None = None) -> datetime:
    """03:30 IST on the day after issue, as Upstox documents."""
    issued = (issued or datetime.now(timezone.utc)).astimezone(IST)
    expiry_day = issued.date() + timedelta(days=1)
    if issued.time() < time(3, 30):
        expiry_day = issued.date()
    return datetime.combine(expiry_day, time(3, 30), tzinfo=IST).astimezone(timezone.utc)
