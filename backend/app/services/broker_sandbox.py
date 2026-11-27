"""A simulated brokerage API.

This is a mock. It talks to nothing. Every holding and transaction it returns
is generated here, deterministically from the account reference, and every
response it produces is labelled as simulated so that no caller and no screen
can present it as a live connection.

It exists because the integration layer around a broker -- the authorisation
flow, token storage and refresh, incremental sync, duplicate suppression,
and the handling of expiry, rate limits, outages and partial responses -- is
most of the engineering, and all of it can be built and tested without
credentials. `docs/account-linking.md` records exactly what live access to
Zerodha, Upstox or Groww requires, so what is missing is an account and an
approval, not a design.

What this deliberately does **not** do:

* It never asks for a password. The flow mimics OAuth: the user authorises
  at the provider and the platform receives a short-lived code to exchange
  for a token. A platform that collects brokerage passwords can drain an
  account, and careful handling does not make asking acceptable.
* It never pretends a simulated response is real. `is_simulated` is on the
  record, on the API response and on every screen.

The failure modes are simulatable on demand rather than at random, because a
test that fails one time in twenty is worse than no test.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

__all__ = [
    "SUPPORTED_PROVIDERS",
    "SANDBOX_SCOPES",
    "BrokerError",
    "TokenExpired",
    "RateLimited",
    "ProviderUnavailable",
    "ScopeNotGranted",
    "SandboxBroker",
]

# Providers the sandbox will pretend to be. The names matter only for the
# documentation of what live access would need; none of them is contacted.
SUPPORTED_PROVIDERS = ("sandbox", "zerodha_sandbox", "upstox_sandbox", "groww_sandbox")

SANDBOX_SCOPES = ("holdings:read", "transactions:read", "profile:read")

# How long a sandbox token lives. Short on purpose: a refresh path that is
# never exercised is a refresh path that does not work.
TOKEN_LIFETIME = timedelta(hours=6)

# Deterministic instrument universe, chosen to overlap the seeded assets so a
# sync produces holdings the analytics layer can actually price.
_UNIVERSE = (
    ("RELIANCE", "equity"), ("TCS", "equity"), ("INFY", "equity"),
    ("HDFCBANK", "equity"), ("ITC", "equity"),
    ("NIFTYBEES", "etf"), ("GOLDBEES", "gold"), ("DEBT", "debt"),
)


class BrokerError(RuntimeError):
    """Base class for every simulated broker failure."""

    kind = "broker_error"
    retryable = False


class TokenExpired(BrokerError):
    kind = "token_expired"
    retryable = True


class RateLimited(BrokerError):
    kind = "rate_limited"
    retryable = True

    def __init__(self, message: str, retry_after_seconds: int = 60):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailable(BrokerError):
    kind = "provider_unavailable"
    retryable = True


class ScopeNotGranted(BrokerError):
    """The user did not grant the scope this call needs.

    A missing scope must raise. Returning an empty list would be read as "the
    user holds nothing", and a sync that treats that as truth deletes a real
    portfolio.
    """

    kind = "scope_not_granted"
    retryable = False


@dataclass
class SandboxBroker:
    """A deterministic stand-in for a brokerage API.

    ``failure`` makes a chosen error happen on the next call, so each failure
    path can be tested explicitly.
    """

    account_reference: str = "SBX0001"
    provider: str = "sandbox"
    granted_scopes: tuple[str, ...] = SANDBOX_SCOPES
    failure: str | None = None
    extra_holdings: int = 0
    partial: bool = False
    calls: list[str] = field(default_factory=list)

    # ---------------- authorisation ----------------

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        """Where the user would be sent to authorise.

        Returned rather than followed. Nothing here opens a browser or
        contacts a host.
        """
        scopes = "+".join(self.granted_scopes)
        return (
            f"https://sandbox.invalid/{self.provider}/authorize"
            f"?client_id=wealthos-sandbox&response_type=code"
            f"&scope={scopes}&state={state}&redirect_uri={redirect_uri}"
        )

    def exchange_code(self, code: str) -> dict:
        """Swap a short-lived authorisation code for tokens.

        No password is involved at any point, by construction: this method
        takes a code and nothing else.
        """
        self.calls.append("exchange_code")
        self._maybe_fail()
        if not code or len(code) < 8:
            raise BrokerError("authorisation code is missing or malformed")

        seed = self._seed(code)
        return {
            "access_token": f"sbx_at_{seed[:24]}",
            "refresh_token": f"sbx_rt_{seed[24:48]}",
            "expires_at": datetime.now(timezone.utc) + TOKEN_LIFETIME,
            "account_reference": self.account_reference,
            "display_name": f"{self.provider.replace('_', ' ').title()} "
                            f"····{self.account_reference[-4:]}",
            "granted_scopes": list(self.granted_scopes),
            "is_simulated": True,
        }

    def refresh(self, refresh_token: str) -> dict:
        self.calls.append("refresh")
        self._maybe_fail()
        if not refresh_token.startswith("sbx_rt_"):
            raise BrokerError("refresh token is not recognised")
        seed = self._seed(refresh_token)
        return {
            "access_token": f"sbx_at_{seed[:24]}",
            "refresh_token": refresh_token,
            "expires_at": datetime.now(timezone.utc) + TOKEN_LIFETIME,
            "is_simulated": True,
        }

    # ---------------- data ----------------

    def holdings(self, access_token: str) -> dict:
        self.calls.append("holdings")
        self._require("holdings:read")
        self._maybe_fail()
        self._check_token(access_token)

        seed = self._seed(self.account_reference)
        count = min(len(_UNIVERSE), 4 + self.extra_holdings)
        rows = []
        for index in range(count):
            symbol, asset_class = _UNIVERSE[index]
            nibble = int(seed[index * 2 : index * 2 + 2], 16)
            rows.append({
                "symbol": symbol,
                "asset_class": asset_class,
                "quantity": float(5 + nibble % 45),
                "average_price": round(100.0 + (nibble % 90) * 11.5, 2),
            })

        truncated = bool(self.partial)
        if truncated:
            rows = rows[: max(1, len(rows) // 2)]

        return {
            "holdings": rows,
            "is_simulated": True,
            "partial": truncated,
            "note": (
                "Simulated holdings, generated deterministically from the "
                "account reference. No brokerage account was contacted."
            ),
        }

    def transactions(self, access_token: str, since: date | None = None) -> dict:
        self.calls.append("transactions")
        self._require("transactions:read")
        self._maybe_fail()
        self._check_token(access_token)

        seed = self._seed("tx" + self.account_reference)
        start = date(2024, 1, 10)
        rows = []
        for index in range(12):
            symbol, _ = _UNIVERSE[index % len(_UNIVERSE)]
            nibble = int(seed[index * 2 : index * 2 + 2], 16)
            when = start + timedelta(days=30 * index)
            if since is not None and when < since:
                continue
            quantity = float(1 + nibble % 12)
            price = round(100.0 + (nibble % 80) * 12.0, 2)
            rows.append({
                # A stable per-transaction identity from the provider. This is
                # what makes a re-sync idempotent: matching on date and amount
                # would merge two genuine same-day trades into one.
                "external_id": f"{self.account_reference}-{index:04d}",
                "symbol": symbol,
                "side": "buy" if nibble % 3 else "sell",
                "quantity": quantity,
                "price": price,
                "value": round(quantity * price, 2),
                "date": when.isoformat(),
            })

        return {
            "transactions": rows,
            "is_simulated": True,
            "note": (
                "Simulated transactions. Each carries a stable external_id so "
                "a repeated sync can recognise what it has already stored."
            ),
        }

    # ---------------- internals ----------------

    def _seed(self, material: str) -> str:
        return hashlib.sha256(
            f"{self.provider}:{self.account_reference}:{material}".encode()
        ).hexdigest()

    def _require(self, scope: str) -> None:
        if scope not in self.granted_scopes:
            raise ScopeNotGranted(
                f"the account was linked without the {scope!r} scope, so this "
                "data cannot be read. Re-authorise and grant it."
            )

    def _check_token(self, access_token: str) -> None:
        if not access_token or not access_token.startswith("sbx_at_"):
            raise TokenExpired("access token is missing, malformed or expired")

    def _maybe_fail(self) -> None:
        if self.failure is None:
            return
        failure, self.failure = self.failure, None
        if failure == "token_expired":
            raise TokenExpired("the access token has expired")
        if failure == "rate_limited":
            raise RateLimited("too many requests to the provider", retry_after_seconds=60)
        if failure == "unavailable":
            raise ProviderUnavailable("the provider is not responding")
        if failure == "scope":
            raise ScopeNotGranted("the required scope was not granted")
        raise BrokerError(f"simulated failure: {failure}")
