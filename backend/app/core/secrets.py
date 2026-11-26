"""Symmetric encryption for tokens held at rest.

Access tokens are credentials. A database dump, a log line or a backup that
contains one is enough to act on someone's brokerage account, so they are
encrypted before storage and decrypted only at the moment of use.

The key is derived from ``JWT_SECRET_KEY`` rather than configured
separately. That is a deliberate trade-off and worth naming: a dedicated key
would be better practice, because rotating the JWT secret currently
invalidates stored tokens as well as sessions. One secret is chosen here
because two secrets that must both be set correctly is two chances to deploy
with a default, and a token encrypted under the string
"insecure-development-key" is not encrypted. The derivation is
domain-separated so the encryption key is never equal to the signing key.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

__all__ = ["encrypt_secret", "decrypt_secret", "TokenDecryptionError"]

# Domain separation: a distinct label means the encryption key and the JWT
# signing key cannot collide even though both come from the same secret.
_DERIVATION_LABEL = b"wealthos.linked-account.token.v1"


class TokenDecryptionError(RuntimeError):
    """A stored token could not be decrypted.

    Raised rather than returning None so that a caller cannot mistake an
    undecryptable token for an absent one and silently proceed as though the
    account were unlinked.
    """


def _key() -> bytes:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        settings.jwt_secret_key.encode("utf-8"),
        _DERIVATION_LABEL,
        iterations=200_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a token for storage. Returns URL-safe ciphertext."""
    if plaintext is None:
        raise ValueError("refusing to encrypt None; pass a string")
    return Fernet(_key()).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored token.

    Raises ``TokenDecryptionError`` if the ciphertext is corrupt or was
    written under a different secret, which is what happens after a key
    rotation and is a condition the caller must handle rather than ignore.
    """
    try:
        return Fernet(_key()).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise TokenDecryptionError(
            "stored token could not be decrypted; it was probably written "
            "under a different JWT_SECRET_KEY. The account must be "
            "re-authorised."
        ) from exc
