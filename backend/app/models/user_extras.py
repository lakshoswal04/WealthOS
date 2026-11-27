"""Per-user settings, AI memory and saved broker credentials."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserSettings(Base, TimestampMixin):
    """Trading preferences, notification choices and the memory switch."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notifications: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    memory_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Memory(Base):
    """One thing the assistant remembers about a user, in a named section."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section: Mapped[str] = mapped_column(String(24), nullable=False)
    text: Mapped[str] = mapped_column(String(280), nullable=False)
    # manual: typed on the Memory page; chat: picked up from a conversation.
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BrokerCredential(Base, TimestampMixin):
    """The API key and secret of a user's own broker developer app.

    Encrypted at rest. Used only to complete the broker's OAuth login, whose
    resulting access token (stored on `LinkedAccount`) reads market data and
    holdings. No order is ever sent to a broker: trading is paper only.
    """

    __tablename__ = "broker_credentials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    broker: Mapped[str] = mapped_column(String(16), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_secret_encrypted: Mapped[str | None] = mapped_column(String(1024))
    client_id_encrypted: Mapped[str | None] = mapped_column(String(1024))
    # The last four characters, so the UI can say which key is saved
    # without ever decrypting it.
    api_key_hint: Mapped[str] = mapped_column(String(8), nullable=False)

    # The pending login's one-time nonce. The OAuth `state` carries it,
    # signed; a callback whose nonce does not match, or arrives after the
    # expiry, is refused. Cleared on use, so a state cannot be replayed.
    oauth_nonce: Mapped[str | None] = mapped_column(String(64))
    oauth_nonce_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "broker", name="uq_broker_credentials_user_broker"),)
