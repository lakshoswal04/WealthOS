"""Connecting a user's Upstox account.

The flow:

1. The user creates their own Upstox developer app and saves its API key and
   secret here (encrypted with `core.secrets`).
2. `begin_login` returns the Upstox authorise URL. Its `state` is a signed,
   ten-minute JWT bound to this user and to a one-time nonce stored on their
   credential row.
3. Upstox redirects the browser to `/api/v1/brokers/upstox/callback`, which
   calls `complete_login`: the state must verify, belong to a user whose
   pending nonce matches, and be unexpired. The nonce is cleared, so a state
   cannot be replayed; the code is exchanged for an access token, which is
   stored encrypted on a `LinkedAccount` (provider "upstox", not simulated).
4. The token reads market data and holdings until 03:30 IST next day.

Orders are never sent to Upstox. Trading in WealthOS is paper only.
"""

from __future__ import annotations

import secrets as pysecrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secrets import TokenDecryptionError, decrypt_secret, encrypt_secret
from app.integrations.upstox import auth as upstox_auth
from app.integrations.upstox.client import TokenInvalid, UpstoxClient, UpstoxError
from app.models import BrokerCredential, LinkedAccount, User
from app.models.enums import LinkedAccountStatus

PROVIDER = "upstox"
STATE_TTL = timedelta(minutes=10)
STATE_AUDIENCE = "wealthos:upstox-login"

SUPPORTED = {
    "upstox": {"name": "Upstox", "supported": True},
    "zerodha": {"name": "Zerodha", "supported": False,
                "reason": "Kite Connect needs a paid API subscription; this build connects Upstox only."},
    "groww": {"name": "Groww", "supported": False,
              "reason": "Not integrated yet; this build connects Upstox only."},
    "dhan": {"name": "Dhan", "supported": False,
             "reason": "Dhan's option-chain data needs a paid data plan; this build connects Upstox only."},
}


class BrokerSetupError(ValueError):
    """A step the user can fix, with a message fit to show them."""


# --------------------------------------------------------------------------
# App credentials
# --------------------------------------------------------------------------

def _credential(db: Session, user: User) -> BrokerCredential | None:
    return db.scalar(select(BrokerCredential).where(
        BrokerCredential.user_id == user.id, BrokerCredential.broker == PROVIDER))


def save_app_credentials(db: Session, user: User, api_key: str, api_secret: str) -> dict:
    api_key, api_secret = (api_key or "").strip(), (api_secret or "").strip()
    if not 8 <= len(api_key) <= 256:
        raise BrokerSetupError("That API key looks wrong: copy it again from your Upstox app.")
    if not 6 <= len(api_secret) <= 256:
        raise BrokerSetupError("That API secret looks wrong: copy it again from your Upstox app.")
    row = _credential(db, user)
    if row is None:
        row = BrokerCredential(user_id=user.id, broker=PROVIDER)
        db.add(row)
    row.api_key_encrypted = encrypt_secret(api_key)
    row.api_secret_encrypted = encrypt_secret(api_secret)
    row.client_id_encrypted = None
    row.api_key_hint = api_key[-4:]
    row.oauth_nonce = None
    row.oauth_nonce_expires_at = None
    db.commit()
    return status(db, user)


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------

def begin_login(db: Session, user: User) -> dict:
    row = _credential(db, user)
    if row is None:
        raise BrokerSetupError("Save your Upstox API key and secret first.")
    nonce = pysecrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + STATE_TTL
    row.oauth_nonce, row.oauth_nonce_expires_at = nonce, expires
    db.commit()
    state = jwt.encode({"sub": str(user.id), "nonce": nonce, "aud": STATE_AUDIENCE,
                        "exp": expires}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    try:
        api_key = decrypt_secret(row.api_key_encrypted)
    except TokenDecryptionError as exc:
        raise BrokerSetupError("Your saved API key can no longer be read; save it again.") from exc
    return {"authorization_url": upstox_auth.authorize_url(api_key, settings.upstox_redirect_uri, state),
            "redirect_uri": settings.upstox_redirect_uri, "expires_at": expires.isoformat()}


def complete_login(db: Session, state: str, code: str) -> User:
    """Verify the state, exchange the code, store the token. Returns the user."""
    try:
        claims = jwt.decode(state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                            audience=STATE_AUDIENCE)
        user_id = int(claims["sub"])
        nonce = str(claims["nonce"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise BrokerSetupError("This login link is invalid or has expired. Start the Upstox login again.") from exc

    user = db.get(User, user_id)
    row = _credential(db, user) if user else None
    now = datetime.now(timezone.utc)
    if (row is None or not row.oauth_nonce or not pysecrets.compare_digest(row.oauth_nonce, nonce)
            or row.oauth_nonce_expires_at is None or row.oauth_nonce_expires_at < now):
        raise BrokerSetupError("This login link was already used or has expired. Start the Upstox login again.")
    row.oauth_nonce, row.oauth_nonce_expires_at = None, None
    db.commit()

    try:
        tokens = upstox_auth.exchange_code(code, decrypt_secret(row.api_key_encrypted),
                                           decrypt_secret(row.api_secret_encrypted or ""),
                                           settings.upstox_redirect_uri)
    except UpstoxError as exc:
        raise BrokerSetupError(f"Upstox refused the login: {exc}") from exc

    reference = str(tokens.get("user_id") or "upstox")
    account = db.scalar(select(LinkedAccount).where(
        LinkedAccount.user_id == user.id, LinkedAccount.provider == PROVIDER))
    if account is None:
        account = LinkedAccount(user_id=user.id, provider=PROVIDER, account_reference=reference)
        db.add(account)
    account.account_reference = reference
    account.display_name = f"Upstox · {tokens.get('user_name') or reference}"
    account.status = LinkedAccountStatus.ACTIVE
    account.access_token_encrypted = encrypt_secret(tokens["access_token"])
    account.refresh_token_encrypted = None
    account.token_expires_at = upstox_auth.token_expiry()
    account.granted_scopes = {"exchanges": tokens.get("exchanges"), "products": tokens.get("products")}
    account.is_simulated = False
    account.last_sync_error = None
    db.commit()
    return user


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def linked_account(db: Session, user: User) -> LinkedAccount | None:
    return db.scalar(select(LinkedAccount).where(
        LinkedAccount.user_id == user.id, LinkedAccount.provider == PROVIDER))


def access_token(db: Session, user: User) -> tuple[str | None, str]:
    """(token, state): state is connected | expired | not_connected | no_credentials."""
    account = linked_account(db, user)
    if account is None or account.status == LinkedAccountStatus.DISCONNECTED:
        return None, "no_credentials" if _credential(db, user) is None else "not_connected"
    if (account.status in (LinkedAccountStatus.EXPIRED, LinkedAccountStatus.REVOKED)
            or account.token_expires_at is None or account.token_expires_at <= datetime.now(timezone.utc)
            or not account.access_token_encrypted):
        return None, "expired"
    try:
        return decrypt_secret(account.access_token_encrypted), "connected"
    except TokenDecryptionError:
        return None, "expired"


def mark_expired(db: Session, user: User) -> None:
    account = linked_account(db, user)
    if account is not None:
        account.status = LinkedAccountStatus.EXPIRED
        db.commit()


def status(db: Session, user: User) -> dict:
    cred = _credential(db, user)
    account = linked_account(db, user)
    _, state = access_token(db, user)
    return {
        "broker": PROVIDER,
        "credentials_saved": cred is not None,
        "api_key_hint": cred.api_key_hint if cred else None,
        "state": state,
        "display_name": account.display_name if account else None,
        "token_expires_at": account.token_expires_at.isoformat() if account and account.token_expires_at else None,
        "last_successful_sync_at": (account.last_successful_sync_at.isoformat()
                                    if account and account.last_successful_sync_at else None),
        "redirect_uri": settings.upstox_redirect_uri,
        "places_orders": False,
    }


def brokers(db: Session, user: User) -> list[dict]:
    out = []
    for key, spec in SUPPORTED.items():
        item = {"broker": key, **spec}
        if key == PROVIDER:
            item.update(status(db, user))
        out.append(item)
    return out


def disconnect(db: Session, user: User, forget_credentials: bool = False) -> dict:
    account = linked_account(db, user)
    if account is not None:
        account.status = LinkedAccountStatus.DISCONNECTED
        account.access_token_encrypted = None
        account.token_expires_at = None
    if forget_credentials:
        cred = _credential(db, user)
        if cred is not None:
            db.delete(cred)
    db.commit()
    return status(db, user)


# --------------------------------------------------------------------------
# Holdings sync (reuses the linking layer's sync, de-duplication and audit)
# --------------------------------------------------------------------------

class _UpstoxHoldingsAdapter:
    """The two calls `linking_service.sync_account` makes, backed by Upstox."""

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def holdings(self, access_token: str) -> dict:
        if access_token in self._cache:
            return self._cache[access_token]
        from app.integrations.upstox.client import RateLimited as URate, Unavailable
        from app.services.broker_sandbox import ProviderUnavailable, RateLimited, TokenExpired

        try:
            rows = UpstoxClient(access_token).holdings()
        except TokenInvalid as exc:
            raise TokenExpired(str(exc)) from exc
        except URate as exc:
            raise RateLimited(str(exc)) from exc
        except (Unavailable, UpstoxError) as exc:
            raise ProviderUnavailable(str(exc)) from exc
        out = []
        for r in rows:
            qty = float(r.get("quantity") or 0) + float(r.get("t1_quantity") or 0)
            if qty <= 0:
                continue
            out.append({"symbol": r.get("trading_symbol") or r.get("tradingsymbol"),
                        "quantity": qty, "average_price": float(r.get("average_price") or 0)})
        self._cache[access_token] = {"holdings": out, "partial": False}
        return self._cache[access_token]

    def transactions(self, access_token: str, since=None) -> dict:
        # Trade history is not imported: holdings carry the average cost.
        return {"transactions": []}


def sync_holdings(db: Session, user: User) -> dict:
    from app.services import linking_service, market_seed

    account = linked_account(db, user)
    _, state = access_token(db, user)
    if account is None or state != "connected":
        raise BrokerSetupError("Log in to Upstox first; your session is not active.")
    adapter = _UpstoxHoldingsAdapter()
    # Holdings outside the analytics universe can only be analysed once the
    # asset and its real price history exist.
    token = decrypt_secret(account.access_token_encrypted)
    symbols = [h["symbol"] for h in adapter.holdings(token)["holdings"]]
    market_seed.ensure_assets(db, symbols)
    result = linking_service.sync_account(db, user, account.id, trigger="manual", broker=adapter)
    if result and result["run"]["error_kind"] == "token_expired":
        mark_expired(db, user)
    return result
