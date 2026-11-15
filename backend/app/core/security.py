"""Password hashing and JWT issuing/verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

# bcrypt truncates silently at 72 bytes. Rejecting longer input is safer than
# accepting a password whose tail is ignored, which would let a shorter
# prefix authenticate.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8


class PasswordTooLongError(ValueError):
    pass


def hash_password(password: str) -> str:
    """Hash a password with a per-password bcrypt salt."""
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"password exceeds {MAX_PASSWORD_BYTES} bytes, which bcrypt would truncate"
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a password against its hash, in constant time."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # A malformed stored hash must read as a failed login, not a crash.
        return False


def create_access_token(subject: str | int, expires_delta: timedelta | None = None) -> str:
    """Issue a signed JWT for a user id."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Return the token payload, or None if it is invalid or expired."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None

    # Reject any token not minted as an access token, so a future refresh or
    # reset token cannot be replayed against protected endpoints.
    if payload.get("type") != "access":
        return None
    return payload
